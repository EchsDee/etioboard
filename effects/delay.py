"""Echo/Delay com realimentação e amortecimento."""
from __future__ import annotations

import numpy as np

from effects.base import Effect, ParamSpec
from effects.dsp_utils import DelayLine, OnePoleLowpass


class Echo(Effect):
    effect_id = "echo"
    display_name = "Echo / Delay"
    description = "Repetições da voz com realimentação."
    params_spec = (
        ParamSpec("delay_ms", "Tempo", 40.0, 1500.0, 280.0, 5.0, "ms", 0),
        ParamSpec("feedback", "Realimentação", 0.0, 0.9, 0.35, 0.01, "", 2),
        ParamSpec("tone_hz", "Tom", 1000.0, 12000.0, 5000.0, 10.0, "Hz", 0, log=True),
        ParamSpec("mix", "Mix", 0.0, 1.0, 0.35, 0.01, "", 2),
    )

    def configure(self) -> None:
        p = self.params
        self.delay = max(int(p["delay_ms"] / 1000.0 * self.sr), 16)
        if not hasattr(self, "lp"):
            self.lp = OnePoleLowpass()
        self.lp.set_cutoff(p["tone_hz"], self.sr)

    def reset(self) -> None:
        self.line = DelayLine(int(1.6 * self.sr) + self.blocksize * 8)
        self.lp.reset()

    def process_block(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        out = np.empty(n)
        fb = self.params["feedback"]
        d = self.delay
        pos = 0
        while pos < n:
            k = min(d, n - pos)
            delayed = self.line.read_fixed(d, k)
            self.line.write(x[pos : pos + k] + fb * self.lp.process(delayed))
            out[pos : pos + k] = delayed
            pos += k
        return x + out * self.params["mix"]
