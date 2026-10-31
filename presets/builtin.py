"""Presets de voz incluídos no aplicativo.

Nenhum vem com noise gate: Discord e afins já têm supressão de ruído (Krisp), e dois gates em
série cortam início/fim das palavras. O usuário pode ligá-lo quando quiser.
"""
from __future__ import annotations

from effects.chain import normalize_state


def _preset(**effects) -> dict:
    state = {eid: {"enabled": True, "params": params} for eid, params in effects.items()}
    return normalize_state(state)


BUILTIN_PRESETS: list[tuple[str, str, dict]] = [
    ("normal", "Normal Voice", _preset()),
    (
        "deep",
        "Deep Voice",
        _preset(
            pitch_shift={"semitones": -4.0},
            formant_shift={"shift": -3.0},
            equalizer={"low_gain_db": 3.0, "high_gain_db": -2.0},
            compressor={"threshold_db": -22.0, "ratio": 3.0, "makeup_db": 4.0},
        ),
    ),
    (
        "high",
        "High Voice",
        _preset(
            pitch_shift={"semitones": 5.0},
            formant_shift={"shift": 3.5},
            equalizer={"low_cut_hz": 120.0, "low_gain_db": -3.0},
        ),
    ),
    (
        "radio",
        "Radio",
        _preset(
            equalizer={"low_cut_hz": 350.0, "mid_freq_hz": 1600.0, "mid_gain_db": 6.0,
                       "high_cut_hz": 4000.0},
            compressor={"threshold_db": -28.0, "ratio": 8.0, "makeup_db": 10.0},
            distortion={"drive_db": 10.0, "tone_hz": 3800.0, "mix": 0.35, "output_db": -4.0},
        ),
    ),
    (
        "robot",
        "Robot",
        _preset(
            robot={"freq_hz": 65.0, "resonance": 0.65, "mix": 1.0},
            chorus={"rate_hz": 0.4, "depth_ms": 1.0, "delay_ms": 8.0, "voices": 2, "mix": 0.25},
            compressor={"threshold_db": -20.0, "ratio": 4.0, "makeup_db": 5.0},
        ),
    ),
    (
        "demon",
        "Demon",
        _preset(
            pitch_shift={"semitones": -9.0},
            formant_shift={"shift": -5.0},
            distortion={"drive_db": 14.0, "tone_hz": 3000.0, "mix": 0.35, "output_db": -6.0},
            equalizer={"low_gain_db": 5.0, "high_gain_db": -4.0},
            reverb={"room_size": 0.75, "damping": 0.6, "mix": 0.22},
        ),
    ),
    (
        "alien",
        "Alien",
        _preset(
            pitch_shift={"semitones": 3.0},
            formant_shift={"shift": 5.0},
            robot={"freq_hz": 28.0, "resonance": 0.0, "mix": 0.45},
            chorus={"rate_hz": 2.5, "depth_ms": 5.0, "delay_ms": 12.0, "voices": 3, "mix": 0.5},
            echo={"delay_ms": 160.0, "feedback": 0.3, "mix": 0.25},
        ),
    ),
    (
        "telephone",
        "Telephone",
        _preset(
            equalizer={"low_cut_hz": 500.0, "mid_freq_hz": 1800.0, "mid_gain_db": 5.0,
                       "high_cut_hz": 3000.0},
            distortion={"drive_db": 8.0, "tone_hz": 3200.0, "mix": 0.3, "output_db": -3.0},
            compressor={"threshold_db": -25.0, "ratio": 6.0, "makeup_db": 8.0},
        ),
    ),
]
