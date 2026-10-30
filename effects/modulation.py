"""Efeitos de modulação: Chorus e Robot Voice."""
from __future__ import annotations

import math

import numpy as np

from effects.base import Effect, ParamSpec, arange
from effects.dsp_utils import DelayLine, FeedbackComb


class Chorus(Effect):
    effect_id = "chorus"
    display_name = "Chorus"
    description = "Multiplica a voz com cópias levemente desafinadas e atrasadas."
    params_spec = (
        ParamSpec("rate_hz", "Velocidade", 0.1, 5.0, 1.2, 0.05, "Hz", 2),
        ParamSpec("depth_ms", "Profundidade", 0.5, 10.0, 3.0, 0.1, "ms", 1),
        ParamSpec("delay_ms", "Atraso", 5.0, 30.0, 14.0, 0.5, "ms", 1),
        ParamSpec("voices", "Vozes", 1.0, 4.0, 2.0, 1.0, "", 0),
        ParamSpec("mix", "Mix", 0.0, 1.0, 0.5, 0.01, "", 2),
    )

    def configure(self) -> None:
        p = self.params
        self.voices = int(round(p["voices"]))
        self.inc = p["rate_hz"] / self.sr
        self.base = p["delay_ms"] / 1000.0 * self.sr
        self.depth = p["depth_ms"] / 1000.0 * self.sr

    def reset(self) -> None:
        self.line = DelayLine(int(0.045 * self.sr) + self.blocksize * 8)
        self.lfo = 0.0

    def process_block(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        self.line.write(x)
        t = self.lfo + self.inc * arange(n)
        wet = np.zeros(n)
        for v in range(self.voices):
            ph = t + v / self.voices
            delays = self.base + self.depth * np.sin(2 * math.pi * ph)
            wet += self.line.read_fractional(delays, n)
        wet /= self.voices
        self.lfo = (self.lfo + self.inc * n) % 1.0
        mix = self.params["mix"]
        return x * (1.0 - mix) + wet * mix


class Robot(Effect):
    """Voz robótica: ressonador em pente (zumbido metálico) + modulação em anel."""

    effect_id = "robot"
    display_name = "Robot Voice"
    description = "Efeito robótico/metálico por modulação em anel e ressonância."
    params_spec = (
        ParamSpec("freq_hz", "Frequência", 20.0, 400.0, 70.0, 1.0, "Hz", 0, log=True),
        ParamSpec("resonance", "Metálico", 0.0, 0.95, 0.6, 0.01, "", 2),
        ParamSpec("mix", "Mix", 0.0, 1.0, 1.0, 0.01, "", 2),
    )

    def configure(self) -> None:
        f = self.params["freq_hz"]
        self.inc = f / self.sr
        delay = max(16, int(round(self.sr / f)))
        if not hasattr(self, "comb"):
            self.comb = FeedbackComb(int(self.sr / 20.0) + 1)
        self.comb.delay = delay
        self.comb.feedback = self.params["resonance"]
        self.comb.lp.set_damping(0.2)

    def reset(self) -> None:
        self.phase = 0.0
        self.comb.reset()

    def process_block(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        fb = self.params["resonance"]
        y = self.comb.process(x) * (1.0 - fb * 0.85) if fb > 0 else x
        carrier = np.sin(2 * math.pi * (self.phase + self.inc * arange(n)))
        self.phase = (self.phase + self.inc * n) % 1.0
        ring = y * carrier * 1.6
        mix = self.params["mix"]
        return x * (1.0 - mix) + ring * mix
