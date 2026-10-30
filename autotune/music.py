"""Teoria musical: notas, escalas, tonalidades, acordes e perfis de tonalidade."""
from __future__ import annotations

import math

import numpy as np

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SCALES: dict[str, tuple[str, tuple[int, ...]]] = {
    "chromatic": ("Chromatic", tuple(range(12))),
    "major": ("Major", (0, 2, 4, 5, 7, 9, 11)),
    "minor": ("Minor", (0, 2, 3, 5, 7, 8, 10)),
    "harmonic_minor": ("Harmonic Minor", (0, 2, 3, 5, 7, 8, 11)),
    "melodic_minor": ("Melodic Minor", (0, 2, 3, 5, 7, 9, 11)),
    "pentatonic_major": ("Pentatonic Major", (0, 2, 4, 7, 9)),
    "pentatonic_minor": ("Pentatonic Minor", (0, 3, 5, 7, 10)),
    "blues": ("Blues", (0, 3, 5, 6, 7, 10)),
}

CHORD_QUALITIES: dict[str, tuple[str, tuple[int, ...]]] = {
    "maj": ("", (0, 4, 7)),
    "min": ("m", (0, 3, 7)),
    "7": ("7", (0, 4, 7, 10)),
    "m7": ("m7", (0, 3, 7, 10)),
}

# Perfis de Krumhansl-Kessler (probe-tone ratings)
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def hz_to_midi(f: float, ref: float = 440.0) -> float:
    return 69.0 + 12.0 * math.log2(f / ref)


def midi_to_hz(m: float, ref: float = 440.0) -> float:
    return ref * 2.0 ** ((m - 69.0) / 12.0)


def note_name(midi: float | None, with_octave: bool = True) -> str:
    if midi is None:
        return "—"
    n = int(round(midi))
    name = NOTE_NAMES[n % 12]
    return f"{name}{n // 12 - 1}" if with_octave else name


def scale_pitch_classes(tonic: int, scale: str) -> frozenset[int]:
    intervals = SCALES.get(scale, SCALES["chromatic"])[1]
    return frozenset((tonic + i) % 12 for i in intervals)


def chord_pitch_classes(root: int, quality: str) -> frozenset[int]:
    intervals = CHORD_QUALITIES.get(quality, CHORD_QUALITIES["maj"])[1]
    return frozenset((root + i) % 12 for i in intervals)


def chord_name(root: int | None, quality: str | None) -> str:
    if root is None or quality is None:
        return "N"
    return NOTE_NAMES[root % 12] + CHORD_QUALITIES.get(quality, ("", ()))[0]


def key_name(tonic: int, mode: str) -> str:
    return f"{NOTE_NAMES[tonic % 12]} {SCALES.get(mode, (mode,))[0]}"


def nearest_in_set(midi: float, pcs: frozenset[int] | set[int]) -> float:
    """Nota (MIDI inteiro) mais próxima de `midi` cuja classe pertence a `pcs`."""
    if not pcs:
        return float(round(midi))
    base = math.floor(midi)
    best, best_d = None, 99.0
    for cand in range(base - 6, base + 8):
        if cand % 12 in pcs:
            d = abs(cand - midi)
            if d < best_d:
                best, best_d = cand, d
    return float(best if best is not None else round(midi))


def key_scores(chroma: np.ndarray) -> np.ndarray:
    """Correlação de um vetor de croma (12) com as 24 tonalidades: [0..11]=maior, [12..23]=menor."""
    c = np.asarray(chroma, dtype=np.float64)
    if c.std() < 1e-9:
        return np.zeros(24)
    scores = np.empty(24)
    for t in range(12):
        scores[t] = np.corrcoef(c, np.roll(KK_MAJOR, t))[0, 1]
        scores[12 + t] = np.corrcoef(c, np.roll(KK_MINOR, t))[0, 1]
    return np.nan_to_num(scores)


def estimate_key(chroma: np.ndarray) -> tuple[int, str, float]:
    """(tônica, 'major'|'minor', confiança 0..1) a partir de um histograma de classes de altura."""
    s = key_scores(chroma)
    order = np.argsort(s)[::-1]
    best = int(order[0])
    conf = float(max(0.0, min(1.0, (s[order[0]] - s[order[1]]) * 4 + max(0.0, s[order[0]]) * 0.5)))
    return best % 12, ("major" if best < 12 else "minor"), conf
