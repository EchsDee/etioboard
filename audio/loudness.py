"""Medição de loudness (ITU-R BS.1770, LUFS) e normalização dos sons do soundboard.

Arquivos de meme/efeito costumam vir masterizados no volume máximo, muito acima da
voz do microfone. Normalizar todos para o mesmo loudness faz "100%" significar o mesmo
volume percebido para qualquer som — próximo ao nível da voz.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import sosfilt

from effects.dsp_utils import biquad_highpass, biquad_highshelf

DEFAULT_TARGET_LUFS = -24.0
MAX_BOOST_DB = 12.0       # sons muito baixos não são amplificados além disso
PEAK_CEILING = 0.98       # nunca amplificar a ponto de estourar


def _k_weighting(sr: int) -> np.ndarray:
    # Pré-filtro "K": shelf de +4 dB acima de ~1,7 kHz + passa-altas em ~38 Hz (BS.1770).
    return np.vstack([biquad_highshelf(1681.97, sr, 3.999), biquad_highpass(38.135, sr, 0.5003)])


def integrated_loudness(data: np.ndarray, sr: int) -> float:
    """Loudness integrado em LUFS (com gates absoluto -70 LUFS e relativo -10 LU)."""
    x = data if data.ndim == 2 else data[:, None]
    if len(x) < int(0.4 * sr):
        x = np.pad(x, ((0, int(0.4 * sr) - len(x)), (0, 0)))
    y = sosfilt(_k_weighting(sr), x.astype(np.float64), axis=0)
    block, hop = int(0.4 * sr), int(0.1 * sr)
    sq = np.concatenate([np.zeros((1, y.shape[1])), np.cumsum(y * y, axis=0)])
    starts = np.arange(0, len(y) - block + 1, hop)
    ms = (sq[starts + block] - sq[starts]) / block           # média quadrática por bloco e canal
    z = ms.sum(axis=1)                                       # canais L/R com peso 1
    with np.errstate(divide="ignore"):
        lk = -0.691 + 10 * np.log10(z)
    gated = z[lk > -70.0]
    if gated.size == 0:
        return -math.inf
    rel = -0.691 + 10 * np.log10(gated.mean()) - 10.0
    final = gated[(-0.691 + 10 * np.log10(gated)) > rel]
    return float(-0.691 + 10 * np.log10(final.mean())) if final.size else -math.inf


def normalization_gain(data: np.ndarray, sr: int, target_lufs: float) -> float:
    """Ganho linear para levar o som ao loudness-alvo (sem amplificar demais nem estourar)."""
    loud = integrated_loudness(data, sr)
    if not math.isfinite(loud):
        return 1.0
    gain_db = min(target_lufs - loud, MAX_BOOST_DB)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak > 0:
        gain_db = min(gain_db, 20 * math.log10(PEAK_CEILING / peak))
    return 10 ** (gain_db / 20)
