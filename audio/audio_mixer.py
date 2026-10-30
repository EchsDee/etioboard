"""Mixer: combina voz processada e soundboard para a saída virtual e para o monitor."""
from __future__ import annotations

import numpy as np

from audio.voice_processor import SmoothedGain


def soft_limit(x: np.ndarray, threshold: float = 0.9) -> np.ndarray:
    """Limitador suave: transparente abaixo do limiar, satura com tanh acima (evita clipping)."""
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak <= threshold:
        return x
    headroom = 1.0 - threshold
    mag = np.abs(x)
    over = mag > threshold
    limited = np.where(
        over, np.sign(x) * (threshold + headroom * np.tanh((mag - threshold) / headroom)), x
    )
    return limited.astype(np.float32, copy=False)


class AudioMixer:
    def __init__(self):
        self.voice = SmoothedGain(1.0)
        self.soundboard = SmoothedGain(0.8)
        self.master = SmoothedGain(1.0)
        self.monitor = SmoothedGain(0.7)
        # ganhos separados para o monitor (para não compartilhar estado de rampa)
        self.monitor_voice_gain = SmoothedGain(0.0)
        self.monitor_sb_gain = SmoothedGain(1.0)
        self.monitor_voice = False
        self.monitor_soundboard = True
        self.levels = {"voice": 0.0, "soundboard": 0.0, "output": 0.0, "monitor": 0.0}

    def set_volumes(self, voice=None, soundboard=None, master=None, monitor=None) -> None:
        if voice is not None:
            self.voice.set(voice)
        if soundboard is not None:
            self.soundboard.set(soundboard)
        if master is not None:
            self.master.set(master)
        if monitor is not None:
            self.monitor.set(monitor)

    def set_monitor_sources(self, voice: bool | None = None, soundboard: bool | None = None) -> None:
        if voice is not None:
            self.monitor_voice = bool(voice)
            self.monitor_voice_gain.set(1.0 if voice else 0.0)
        if soundboard is not None:
            self.monitor_soundboard = bool(soundboard)
            self.monitor_sb_gain.set(1.0 if soundboard else 0.0)

    def mix(self, voice_mono: np.ndarray, sb_main: np.ndarray, sb_preview: np.ndarray,
            want_monitor: bool) -> tuple[np.ndarray, np.ndarray | None]:
        voice = self.voice.apply(voice_mono.astype(np.float32, copy=False))
        voice_st = np.repeat(voice[:, None], 2, axis=1)
        sb = self.soundboard.apply(sb_main)

        out = self.master.apply(voice_st + sb)
        out = soft_limit(out)
        self.levels["voice"] = float(np.max(np.abs(voice))) if voice.size else 0.0
        self.levels["soundboard"] = float(np.max(np.abs(sb))) if sb.size else 0.0
        self.levels["output"] = float(np.max(np.abs(out))) if out.size else 0.0

        mon = None
        if want_monitor:
            mon = self.monitor_voice_gain.apply(voice_st) + self.monitor_sb_gain.apply(sb) + sb_preview
            mon = soft_limit(self.monitor.apply(mon))
            self.levels["monitor"] = float(np.max(np.abs(mon))) if mon.size else 0.0
        return out.astype(np.float32, copy=False), mon
