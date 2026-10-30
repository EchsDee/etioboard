"""Equalizador paramétrico: corte de graves, shelf grave, médio, shelf agudo e corte de agudos."""
from __future__ import annotations

import numpy as np
from scipy.signal import sosfilt

from effects.base import Effect, ParamSpec
from effects.dsp_utils import (
    biquad_highpass,
    biquad_highshelf,
    biquad_lowpass,
    biquad_lowshelf,
    biquad_peak,
)


class Equalizer(Effect):
    effect_id = "equalizer"
    display_name = "Equalizer"
    description = "Equalização de frequências em 5 bandas."
    params_spec = (
        ParamSpec("low_cut_hz", "Corte graves", 20.0, 1000.0, 20.0, 1.0, "Hz", 0, log=True),
        ParamSpec("low_gain_db", "Graves (150 Hz)", -15.0, 15.0, 0.0, 0.5, "dB", 1),
        ParamSpec("mid_freq_hz", "Freq. médios", 200.0, 6000.0, 1200.0, 10.0, "Hz", 0, log=True),
        ParamSpec("mid_gain_db", "Médios", -15.0, 15.0, 0.0, 0.5, "dB", 1),
        ParamSpec("mid_q", "Largura (Q)", 0.3, 5.0, 1.0, 0.05, "", 2),
        ParamSpec("high_gain_db", "Agudos (5 kHz)", -15.0, 15.0, 0.0, 0.5, "dB", 1),
        ParamSpec("high_cut_hz", "Corte agudos", 1000.0, 20000.0, 20000.0, 10.0, "Hz", 0, log=True),
    )

    def configure(self) -> None:
        p, sr = self.params, self.sr
        sections = [
            biquad_highpass(p["low_cut_hz"], sr),
            biquad_lowshelf(150.0, sr, p["low_gain_db"]),
            biquad_peak(p["mid_freq_hz"], sr, p["mid_gain_db"], p["mid_q"]),
            biquad_highshelf(5000.0, sr, p["high_gain_db"]),
            biquad_lowpass(min(p["high_cut_hz"], sr * 0.45), sr),
        ]
        self.sos = np.vstack(sections)
        if not hasattr(self, "zi"):
            self.zi = np.zeros((self.sos.shape[0], 2))

    def reset(self) -> None:
        self.zi = np.zeros((self.sos.shape[0], 2))

    def process_block(self, x: np.ndarray) -> np.ndarray:
        y, self.zi = sosfilt(self.sos, x, zi=self.zi)
        return y
