"""Mapa musical de uma música: consulta por tempo das notas permitidas, acorde e melodia."""
from __future__ import annotations

import bisect
from dataclasses import dataclass

from autotune.music import chord_pitch_classes, scale_pitch_classes


@dataclass(frozen=True)
class HarmonyAt:
    scale_pcs: frozenset[int]
    chord_pcs: frozenset[int] | None   # None = sem acorde (N)
    melody_midi: int | None            # nota de referência, se houver
    key_tonic: int
    key_mode: str
    chord_label: str


class SongMap:
    """Constrói estruturas de busca a partir do dicionário de análise (já com edições do usuário)."""

    def __init__(self, analysis: dict):
        key = analysis.get("key") or {"tonic": 0, "mode": "major"}
        self.global_key = (int(key.get("tonic", 0)), key.get("scale") or key.get("mode", "major"))
        segs = analysis.get("key_segments") or []
        self.key_starts = [float(s["start"]) for s in segs]
        self.keys = [(int(s["tonic"]), s.get("scale") or s.get("mode", "major")) for s in segs]
        chords = analysis.get("chords") or []
        self.chord_starts = [float(c["start"]) for c in chords]
        self.chord_ends = [float(c["end"]) for c in chords]
        self.chords = [(c.get("root"), c.get("quality"), c.get("label", "N")) for c in chords]
        melody = sorted(analysis.get("melody") or [], key=lambda n: n["start"])
        self.mel_starts = [float(n["start"]) for n in melody]
        self.mel_ends = [float(n["end"]) for n in melody]
        self.mel_notes = [int(n["midi"]) for n in melody]
        self._scale_cache: dict[tuple[int, str], frozenset[int]] = {}

    def _scale(self, tonic: int, mode: str) -> frozenset[int]:
        k = (tonic, mode)
        if k not in self._scale_cache:
            self._scale_cache[k] = scale_pitch_classes(tonic, mode)
        return self._scale_cache[k]

    def key_at(self, t: float) -> tuple[int, str]:
        i = bisect.bisect_right(self.key_starts, t) - 1
        return self.keys[i] if i >= 0 else self.global_key

    def at(self, t: float) -> HarmonyAt:
        tonic, mode = self.key_at(t)
        chord_pcs, label = None, "N"
        i = bisect.bisect_right(self.chord_starts, t) - 1
        if 0 <= i < len(self.chords) and t < self.chord_ends[i]:
            root, quality, label = self.chords[i]
            if root is not None and quality:
                chord_pcs = chord_pitch_classes(int(root), quality)
        mel = None
        j = bisect.bisect_right(self.mel_starts, t) - 1
        if 0 <= j < len(self.mel_notes) and t < self.mel_ends[j]:
            mel = self.mel_notes[j]
        return HarmonyAt(self._scale(tonic, mode), chord_pcs, mel, tonic, mode, label)
