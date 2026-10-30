"""Noise Gate e Compressor.

A detecção de nível é feita em sub-blocos de poucas amostras (laço Python curto,
~8-16 iterações por bloco) e o ganho resultante é interpolado amostra a amostra.
"""
from __future__ import annotations

import math

import numpy as np

from effects.base import Effect, ParamSpec, arange, db_to_lin

SUB = 32


def _subblock_levels(x: np.ndarray, peak: bool) -> tuple[np.ndarray, np.ndarray]:
    """Retorna (níveis em dB por sub-bloco, posição da última amostra de cada sub-bloco)."""
    n = len(x)
    m = max(1, -(-n // SUB))
    if m * SUB != n:
        padded = np.zeros(m * SUB, dtype=np.float64)
        padded[:n] = x
        frames = padded.reshape(m, SUB)
    else:
        frames = x.reshape(m, SUB)
    if peak:
        lvl = np.abs(frames).max(axis=1)
    else:
        lvl = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    ends = np.minimum((np.arange(m) + 1) * SUB - 1, n - 1).astype(np.float64)
    return 20.0 * np.log10(np.maximum(lvl, 1e-9)), ends


def _interp_gain(prev: float, gains: np.ndarray, ends: np.ndarray, n: int) -> np.ndarray:
    xp = np.concatenate(([-1.0], ends))
    fp = np.concatenate(([prev], gains))
    return np.interp(arange(n), xp, fp)


class NoiseGate(Effect):
    effect_id = "noise_gate"
    display_name = "Noise Gate"
    description = "Silencia o microfone abaixo do limiar, eliminando ruído de fundo."
    params_spec = (
        ParamSpec("threshold_db", "Limiar", -80.0, 0.0, -48.0, 0.5, "dB", 1),
        ParamSpec("attack_ms", "Ataque", 0.5, 50.0, 2.0, 0.5, "ms", 1),
        ParamSpec("hold_ms", "Retenção", 0.0, 500.0, 120.0, 5.0, "ms", 0),
        ParamSpec("release_ms", "Liberação", 10.0, 1000.0, 150.0, 5.0, "ms", 0),
        ParamSpec("range_db", "Atenuação", -90.0, 0.0, -70.0, 1.0, "dB", 0),
    )

    def configure(self) -> None:
        p = self.params
        sub_s = SUB / self.sr
        self.att = 1.0 - math.exp(-sub_s / (p["attack_ms"] / 1000.0))
        self.rel = 1.0 - math.exp(-sub_s / (p["release_ms"] / 1000.0))
        self.hold_subs = int(p["hold_ms"] / 1000.0 / sub_s)
        self.floor = db_to_lin(p["range_db"])
        self.thr = p["threshold_db"]

    def reset(self) -> None:
        self.g = self.floor if hasattr(self, "floor") else 0.0
        self.hold = 0
        self.open = False
        self.level_db = -120.0  # exposto para a UI

    def process_block(self, x: np.ndarray) -> np.ndarray:
        levels, ends = _subblock_levels(x, peak=False)
        gains = np.empty(len(levels))
        g, hold, is_open = self.g, self.hold, self.open
        thr, close_thr = self.thr, self.thr - 6.0
        for i, lv in enumerate(levels):
            if lv > thr:
                is_open = True
                hold = self.hold_subs
            elif lv < close_thr:
                if hold > 0:
                    hold -= 1
                else:
                    is_open = False
            elif hold > 0:
                hold -= 1
            target = 1.0 if is_open else self.floor
            g += (target - g) * (self.att if target > g else self.rel)
            gains[i] = g
        env = _interp_gain(self.g, gains, ends, len(x))
        self.g, self.hold, self.open = g, hold, is_open
        self.level_db = float(levels.max())
        return x * env


class Compressor(Effect):
    effect_id = "compressor"
    display_name = "Compressor"
    description = "Controla a dinâmica: reduz picos e equilibra o volume da voz."
    params_spec = (
        ParamSpec("threshold_db", "Limiar", -60.0, 0.0, -20.0, 0.5, "dB", 1),
        ParamSpec("ratio", "Razão", 1.0, 20.0, 4.0, 0.1, ":1", 1),
        ParamSpec("attack_ms", "Ataque", 0.1, 100.0, 5.0, 0.1, "ms", 1),
        ParamSpec("release_ms", "Liberação", 10.0, 1000.0, 120.0, 5.0, "ms", 0),
        ParamSpec("knee_db", "Joelho", 0.0, 24.0, 6.0, 0.5, "dB", 1),
        ParamSpec("makeup_db", "Ganho", 0.0, 24.0, 6.0, 0.5, "dB", 1),
    )

    def configure(self) -> None:
        p = self.params
        sub_s = SUB / self.sr
        self.att = 1.0 - math.exp(-sub_s / (p["attack_ms"] / 1000.0))
        self.rel = 1.0 - math.exp(-sub_s / (p["release_ms"] / 1000.0))
        self.makeup = p["makeup_db"]

    def reset(self) -> None:
        self.gr_db = 0.0
        self.prev_gain = db_to_lin(self.params["makeup_db"])

    def _static_curve(self, level: np.ndarray) -> np.ndarray:
        thr, ratio, knee = self.params["threshold_db"], self.params["ratio"], self.params["knee_db"]
        slope = 1.0 - 1.0 / ratio
        over = level - thr
        gr = np.where(over > knee / 2, over * slope, 0.0)
        if knee > 0:
            in_knee = np.abs(over) <= knee / 2
            gr = np.where(in_knee, slope * (over + knee / 2) ** 2 / (2 * knee), gr)
        return gr  # redução de ganho em dB (positiva)

    def process_block(self, x: np.ndarray) -> np.ndarray:
        levels, ends = _subblock_levels(x, peak=True)
        targets = self._static_curve(levels)
        smoothed = np.empty(len(targets))
        gr = self.gr_db
        att, rel = self.att, self.rel
        for i, t in enumerate(targets):
            gr += (t - gr) * (att if t > gr else rel)
            smoothed[i] = gr
        self.gr_db = gr
        gains = 10.0 ** ((self.makeup - smoothed) / 20.0)
        env = _interp_gain(self.prev_gain, gains, ends, len(x))
        self.prev_gain = float(gains[-1])
        return x * env
