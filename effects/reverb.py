"""Reverb no estilo Freeverb (8 filtros pente + 4 passa-tudo), vetorizado em sub-blocos."""
from __future__ import annotations

import numpy as np

from effects.base import Effect, ParamSpec
from effects.dsp_utils import DelayLine, OnePoleLowpass

_COMBS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
_ALLPASSES = (556, 441, 341, 225)


class _Comb:
    def __init__(self, delay: int):
        self.delay = delay
        self.line = DelayLine(delay + 8)
        self.lp = OnePoleLowpass()
        self.feedback = 0.84

    def process(self, x: np.ndarray) -> np.ndarray:
        delayed = self.line.read_fixed(self.delay, len(x))
        self.line.write(x + self.feedback * self.lp.process(delayed))
        return delayed


class _Allpass:
    def __init__(self, delay: int):
        self.delay = delay
        self.line = DelayLine(delay + 8)

    def process(self, x: np.ndarray) -> np.ndarray:
        delayed = self.line.read_fixed(self.delay, len(x))
        self.line.write(x + delayed * 0.5)
        return delayed - x


class Reverb(Effect):
    effect_id = "reverb"
    display_name = "Reverb"
    description = "Reverberação (ambiente/sala)."
    params_spec = (
        ParamSpec("room_size", "Tamanho", 0.0, 1.0, 0.6, 0.01, "", 2),
        ParamSpec("damping", "Amortecimento", 0.0, 1.0, 0.5, 0.01, "", 2),
        ParamSpec("mix", "Mix", 0.0, 1.0, 0.25, 0.01, "", 2),
    )

    def _build(self) -> None:
        scale = self.sr / 44100.0
        self.combs = [_Comb(int(d * scale)) for d in _COMBS]
        self.allpasses = [_Allpass(int(d * scale)) for d in _ALLPASSES]
        self.chunk = min(a.delay for a in self.allpasses)

    def configure(self) -> None:
        if not hasattr(self, "combs"):
            self._build()
        fb = self.params["room_size"] * 0.28 + 0.7
        damp = self.params["damping"] * 0.4
        for c in self.combs:
            c.feedback = fb
            c.lp.set_damping(damp)

    def reset(self) -> None:
        for c in self.combs:
            c.line.reset()
            c.lp.reset()
        for a in self.allpasses:
            a.line.reset()

    def process_block(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        wet = np.empty(n)
        pos = 0
        while pos < n:
            k = min(self.chunk, n - pos)
            inp = x[pos : pos + k] * 0.015
            acc = self.combs[0].process(inp)
            for c in self.combs[1:]:
                acc = acc + c.process(inp)
            for a in self.allpasses:
                acc = a.process(acc)
            wet[pos : pos + k] = acc
            pos += k
        mix = self.params["mix"]
        return x * (1.0 - mix * 0.5) + wet * (3.0 * mix)
