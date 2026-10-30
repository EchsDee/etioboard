"""Processamento da voz: ganho do microfone, mute e cadeia de efeitos."""
from __future__ import annotations

import copy
import threading

import numpy as np

from effects.base import arange
from effects.chain import EffectChain, default_state, normalize_state


class SmoothedGain:
    """Ganho com rampa linear por bloco (evita estalos ao mover faders ou ao mutar)."""

    def __init__(self, value: float = 1.0):
        self.target = float(value)
        self.current = float(value)

    def set(self, value: float) -> None:
        self.target = float(value)

    def apply(self, x: np.ndarray) -> np.ndarray:
        if self.current == self.target:
            if self.current == 1.0:
                return x
            return x * self.current
        n = len(x)
        ramp = self.current + (self.target - self.current) * (arange(n) + 1.0) / n
        self.current = self.target
        if x.ndim == 2:
            return x * ramp[:, None].astype(np.float32)
        return x * ramp


class VoiceProcessor:
    """Mantém o estado da voz independentemente do motor (sobrevive a reinícios de stream)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = default_state()
        self._master = True
        self._muted = False
        self._mic_gain = 1.0
        self.chain: EffectChain | None = None
        self.mic = SmoothedGain(1.0)
        self.level_in = 0.0
        self.level_out = 0.0

    # ----------------------------------------------------- ciclo de vida (motor)
    def prepare(self, samplerate: int, blocksize: int) -> None:
        with self._lock:
            chain = EffectChain(samplerate, blocksize, self._state)
            chain.set_master(self._master)
            self.chain = chain
            self.mic = SmoothedGain(0.0 if self._muted else self._mic_gain)

    # ----------------------------------------------------- controle (interface)
    def apply_state(self, state: dict) -> None:
        with self._lock:
            self._state = normalize_state(state)
            if self.chain:
                self.chain.apply_state(self._state)

    def state(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._state)

    def set_effect_enabled(self, effect_id: str, enabled: bool) -> None:
        with self._lock:
            self._state[effect_id]["enabled"] = bool(enabled)
            if self.chain:
                self.chain.set_effect_enabled(effect_id, enabled)

    def set_effect_params(self, effect_id: str, params: dict) -> None:
        with self._lock:
            self._state[effect_id]["params"].update(params)
            if self.chain:
                self.chain.set_effect_params(effect_id, params)

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._master = bool(enabled)
            if self.chain:
                self.chain.set_master(self._master)

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self.mic.set(0.0 if self._muted else self._mic_gain)

    def set_mic_gain(self, gain: float) -> None:
        self._mic_gain = float(gain)
        if not self._muted:
            self.mic.set(self._mic_gain)

    def latency_s(self) -> float:
        chain = self.chain
        return chain.latency_s() if chain else 0.0

    # ----------------------------------------------------- thread de DSP
    def process(self, mic_block: np.ndarray) -> np.ndarray:
        x = self.mic.apply(mic_block.astype(np.float64, copy=False))
        self.level_in = float(np.max(np.abs(x))) if len(x) else 0.0
        chain = self.chain
        y = chain.process(x) if chain else x
        self.level_out = float(np.max(np.abs(y))) if len(y) else 0.0
        return y
