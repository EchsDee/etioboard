"""Distorção por saturação suave (tanh) com controle de tom."""
from __future__ import annotations

import numpy as np
from scipy.signal import sosfilt

from effects.base import Effect, ParamSpec, db_to_lin
from effects.dsp_utils import biquad_lowpass


class Distortion(Effect):
    effect_id = "distortion"
    display_name = "Distortion"
    description = "Saturação/distorção da voz."
    params_spec = (
        ParamSpec("drive_db", "Drive", 0.0, 40.0, 18.0, 0.5, "dB", 1),
        ParamSpec("tone_hz", "Tom", 800.0, 12000.0, 5000.0, 10.0, "Hz", 0, log=True),
        ParamSpec("output_db", "Saída", -24.0, 6.0, -6.0, 0.5, "dB", 1),
        ParamSpec("mix", "Mix", 0.0, 1.0, 1.0, 0.01, "", 2),
    )

    def configure(self) -> None:
        p = self.params
        self.drive = db_to_lin(p["drive_db"])
        self.out_gain = db_to_lin(p["output_db"])
        self.sos = biquad_lowpass(p["tone_hz"], self.sr).reshape(1, 6)

    def reset(self) -> None:
        self.zi = np.zeros((1, 2))

    def process_block(self, x: np.ndarray) -> np.ndarray:
        shaped = np.tanh(x * self.drive)
        shaped, self.zi = sosfilt(self.sos, shaped, zi=self.zi)
        shaped *= self.out_gain
        mix = self.params["mix"]
        return x * (1.0 - mix) + shaped * mix
