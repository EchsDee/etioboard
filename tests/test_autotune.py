"""Testes do Auto-Tune Studio: detecção, PSOLA, correção, mapa musical, análise, MIDI e persistência."""
import json
import struct

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import lfilter

from audio.audio_mixer import AudioMixer
from audio.song_player import SongPlayer
from autotune.corrector import AutoTune
from autotune.midi_import import melody_line, read_notes
from autotune.music import estimate_key, hz_to_midi, nearest_in_set, scale_pitch_classes
from autotune.pitch_detector import YinDetector
from autotune.psola import PsolaShifter
from autotune.song_map import SongMap
from effects.chain import DEFAULT_ORDER, normalize_order

SR, BS = 48000, 256


def vowel(f0_fn, secs=1.5):
    """Vogal sintética: trem de pulsos glotais filtrado por três formantes."""
    t = np.arange(int(SR * secs)) / SR
    ph = np.cumsum(f0_fn(t)) / SR
    pulses = np.zeros_like(t)
    pulses[np.nonzero(np.diff(np.floor(ph)) > 0)[0]] = 1.0
    y = lfilter([1], [1, -0.97], pulses)
    for f, bw in ((700, 80), (1220, 90), (2600, 120)):
        r, th = np.exp(-np.pi * bw / SR), 2 * np.pi * f / SR
        y = lfilter([1 - r], [1, -2 * r * np.cos(th), r * r], y)
    return 0.3 * y / np.max(np.abs(y))


def track_midi(y):
    det, out = YinDetector(SR), []
    for i in range(0, len(y) - BS, BS):
        det.push(y[i:i + BS])
        f = det.detect()
        out.append(hz_to_midi(f) if f else np.nan)
    return np.array(out)


def run_autotune(x, params=None, **cfg):
    at = AutoTune(SR, BS)
    at.set_params(params or {})
    at.set_config(**cfg)
    at.set_enabled(True)
    out = [at.process(x[i:i + BS]) for i in range(0, len(x) - BS + 1, BS)]
    return np.concatenate(out), at


# ---------------------------------------------------------------- detecção e PSOLA
@pytest.mark.parametrize("f0", [82.0, 147.0, 220.0, 440.0, 784.0])
def test_yin_accuracy(f0):
    m = track_midi(vowel(lambda t: np.full_like(t, f0)))[20:]
    assert np.nanmedian(np.abs(m - hz_to_midi(f0))) < 0.05


def test_yin_silence_is_unvoiced():
    det = YinDetector(SR)
    det.push(np.zeros(4096))
    assert det.detect() is None


def test_psola_identity_is_exact():
    x = vowel(lambda t: 160 + 10 * np.sin(2 * np.pi * 5 * t))
    ps, det, out = PsolaShifter(SR), YinDetector(SR), []
    for i in range(0, len(x) - BS + 1, BS):
        det.push(x[i:i + BS])
        f = det.detect()
        out.append(ps.process(x[i:i + BS], SR / f if f else None, SR / f if f else None))
    y = np.concatenate(out)
    L = ps.latency
    seg = slice(SR // 2, SR)
    np.testing.assert_allclose(y[L:][seg], x[: len(y) - L][seg], atol=1e-6)


@pytest.mark.parametrize("semis", [-3.0, -0.5, 0.5, 4.0])
def test_psola_shift_accuracy(semis):
    x = vowel(lambda t: np.full_like(t, 200.0))
    ps, out = PsolaShifter(SR), []
    det = YinDetector(SR)
    for i in range(0, len(x) - BS + 1, BS):
        det.push(x[i:i + BS])
        f = det.detect()
        p = SR / f if f else None
        out.append(ps.process(x[i:i + BS], p, p / 2 ** (semis / 12) if p else None))
    m = track_midi(np.concatenate(out))[60:]
    assert abs(np.nanmedian(m) - (hz_to_midi(200.0) + semis)) < 0.05


# ---------------------------------------------------------------- correção
def test_hard_tune_pulls_detuned_voice_to_note():
    x = vowel(lambda t: 196 * 2 ** ((0.4 * np.sin(2 * np.pi * 0.6 * t)) / 12), secs=3)  # G3 ±40 cents
    y, _ = run_autotune(x, {"retune_ms": 0, "humanize": 0, "flex_cents": 0, "amount": 1})
    before = np.nanmean(np.abs(track_midi(x)[40:] - 55))
    after = np.nanmean(np.abs(track_midi(y)[60:] - 55))
    assert before > 0.2 and after < 0.1


def test_amount_zero_keeps_original_pitch():
    x = vowel(lambda t: np.full_like(t, 200.0))  # entre G3 e G#3
    y, _ = run_autotune(x, {"amount": 0.0, "retune_ms": 0})
    assert abs(np.nanmedian(track_midi(y)[60:]) - hz_to_midi(200.0)) < 0.05


def test_scale_restricts_target_notes():
    x = vowel(lambda t: 261.63 * 2 ** (4 * np.clip(t / 3, 0, 1) / 12), secs=3.2)  # glissando C4 -> E4
    y, _ = run_autotune(x, {"retune_ms": 0, "humanize": 0}, key=0, scale="major")
    notes = np.round(track_midi(y)[80:])
    notes = notes[~np.isnan(notes)]
    vals, counts = np.unique(notes, return_counts=True)
    sustained = {int(v) for v, c in zip(vals, counts) if c > 10}
    assert sustained <= {60, 62, 64} and 61 not in sustained and 63 not in sustained


def test_chord_mode_prefers_chord_tones_and_melody_mode_follows_reference():
    analysis = {"duration": 10, "key": {"tonic": 0, "scale": "major"},
                "key_segments": [{"start": 0, "end": 10, "tonic": 0, "scale": "major"}],
                "chords": [{"start": 0, "end": 10, "root": 0, "quality": "maj", "label": "C"}],
                "melody": [{"start": 0, "end": 10, "midi": 69}]}
    at = AutoTune(SR, BS)
    at.set_config(source="song", song_mode="chord", song_map=SongMap(analysis))
    at.song_time = 1.0
    # 62.3 (D4 +30 cents): na escala o mais próximo é D (62); no Chord Mode o E (64) do acorde não vence,
    # mas 63.2 vai para E (nota do acorde) em vez de D#/D.
    assert at._choose_target(62.3) == 62
    at.current_note = None
    assert at._choose_target(63.2) == 64
    at.current_note = None
    at.set_config(song_mode="melody")
    assert at._choose_target(56.6) == 57  # A (melodia 69), oitava mais próxima do que é cantado


def test_key_estimation_from_histogram():
    hist = np.zeros(12)
    for pc, w in zip((7, 9, 11, 0, 2, 4, 6), (5, 2, 3, 2, 3, 2, 1)):  # G maior
        hist[pc] = w
    tonic, mode, _ = estimate_key(hist)
    assert (tonic, mode) == (7, "major")
    assert nearest_in_set(61.4, scale_pitch_classes(0, "major")) == 62


# ---------------------------------------------------------------- mapa musical, análise e MIDI
def test_song_map_lookup():
    a = {"duration": 8, "key": {"tonic": 0, "scale": "major"},
         "key_segments": [{"start": 0, "end": 4, "tonic": 0, "scale": "major"},
                          {"start": 4, "end": 8, "tonic": 2, "scale": "major"}],
         "chords": [{"start": 0, "end": 2, "root": 0, "quality": "maj", "label": "C"},
                    {"start": 2, "end": 8, "root": 9, "quality": "min", "label": "Am"}],
         "melody": [{"start": 1, "end": 2, "midi": 64}]}
    sm = SongMap(a)
    assert sm.at(1.5).chord_label == "C" and sm.at(1.5).melody_midi == 64
    assert sm.at(3.0).chord_pcs == frozenset({9, 0, 4}) and sm.at(3.0).melody_midi is None
    assert sm.at(5.0).key_tonic == 2


@pytest.fixture(scope="module")
def synth_song(tmp_path_factory):
    """Música sintética: C-Am-F-G em C maior, depois D-Bm-G-A em D maior, 112 BPM, com bumbo."""
    sr, bpm = 44100, 112
    beat = 60 / bpm
    quals = {"maj": (0, 4, 7), "min": (0, 3, 7)}
    bars = [[(60, "maj"), (57, "min"), (53, "maj"), (55, "maj")][i % 4] for i in range(12)]
    bars += [[(62, "maj"), (59, "min"), (55, "maj"), (57, "maj")][i % 4] for i in range(12)]
    y = np.zeros(int((len(bars) * 4 * beat + 1) * sr))
    truth = []
    for b, (root, q) in enumerate(bars):
        t0 = b * 4 * beat
        truth.append((t0, t0 + 4 * beat, root % 12, q))
        for k in range(4):
            s = int((t0 + k * beat) * sr)
            tt = np.arange(int(beat * 0.95 * sr)) / sr
            env = np.minimum(1, tt / 0.01) * np.exp(-tt * 1.5)
            for iv in quals[q]:
                f = 440 * 2 ** ((root + iv - 69) / 12)
                y[s:s + len(tt)] += 0.08 * env * sum(0.6 ** h * np.sin(2 * np.pi * f * (h + 1) * tt) for h in range(6))
            kt = np.arange(int(0.12 * sr)) / sr
            y[s:s + len(kt)] += 0.5 * np.sin(2 * np.pi * 60 * kt) * np.exp(-kt * 30)
    path = tmp_path_factory.mktemp("song") / "song.wav"
    sf.write(path, y / np.max(np.abs(y)) * 0.9, sr)
    return str(path), truth, bpm, 12 * 4 * beat


def test_song_analysis_bpm_key_chords_and_modulation(synth_song):
    from autotune.song_analysis import analyze

    path, truth, bpm, modulation = synth_song
    a = analyze(path)
    json.dumps(a)  # precisa ser serializável para o banco
    assert abs(a["bpm"] - bpm) < 2
    keys = [(k["tonic"], k["scale"]) for k in a["key_segments"]]
    assert keys[0] == (0, "major") and keys[-1] == (2, "major")
    assert abs(a["key_segments"][-1]["start"] - modulation) < 8
    sm = SongMap(a)
    ok = n = 0
    quals = {"maj": (0, 4, 7), "min": (0, 3, 7)}
    for t0, t1, root, q in truth:
        for t in np.linspace(t0 + 0.3, t1 - 0.3, 4):
            n += 1
            h = sm.at(t)
            ok += h.chord_pcs is not None and frozenset((root + i) % 12 for i in quals[q]) <= h.chord_pcs
    assert ok / n > 0.85
    assert all(c["notes"] and c["scale_notes"] for c in a["chords"] if c["root"] is not None)
    assert a["sections"] and a["melody"]


def _midi_bytes() -> bytes:
    def track(events: bytes) -> bytes:
        return b"MTrk" + struct.pack(">I", len(events)) + events
    tempo = b"\x00\xff\x51\x03\x07\xa1\x20"  # 500000 us/semínima
    notes = b""
    for i, n in enumerate((60, 62, 64)):
        notes += (b"\x00" if i == 0 else b"\x00") + bytes([0x90, n, 100]) + b"\x83\x60" + bytes([0x80, n, 0])
    notes += b"\x00\x90\x48\x64\x00\x90\x34\x64\x83\x60\x80\x48\x00\x00\x80\x34\x00"  # acorde: skyline = 72
    end = b"\x00\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 1, 1, 480) + track(tempo + notes + end)


def test_midi_import_and_skyline(tmp_path):
    p = tmp_path / "m.mid"
    p.write_bytes(_midi_bytes())
    notes = read_notes(p)
    assert [n["midi"] for n in notes][:3] == [60, 62, 64]
    assert notes[1]["start"] == pytest.approx(0.5) and notes[1]["end"] == pytest.approx(1.0)
    line = melody_line(notes)
    assert [n["midi"] for n in line] == [60, 62, 64, 72]


# ---------------------------------------------------------------- cadeia, player e mixer
def test_effect_order_normalization():
    assert normalize_order(None) == list(DEFAULT_ORDER)
    custom = normalize_order(["reverb", "autotune", "bogus", "reverb"])
    # ordem do usuário preservada; ausentes voltam à posição padrão relativa (noise_gate no início)
    assert custom[:3] == ["noise_gate", "reverb", "autotune"] and sorted(custom) == sorted(DEFAULT_ORDER)


def test_song_player_play_seek_stop():
    sp = SongPlayer(48000)
    sp.load(1, np.ones((48000, 2), np.float32))
    sp.play()
    assert sp.render(256) is not None and sp.position == 256
    sp.seek(0.5)
    sp.render(256)
    assert sp.block_start == 24000
    sp.stop()
    assert sp.render(256) is None and sp.position == 0


def test_music_goes_to_monitor_only_unless_enabled():
    m = AudioMixer()
    m.set_volumes(voice=1, soundboard=1, master=1, monitor=1)
    m.monitor.current = m.soundboard.current = 1.0
    m.music.current = m.music.target = 1.0
    voice = np.zeros(64, np.float32)
    zeros = np.zeros((64, 2), np.float32)
    music = np.full((64, 2), 0.3, np.float32)
    out, mon = m.mix(voice, zeros, zeros, True, music)
    assert np.max(np.abs(out)) == 0.0 and mon[-1, 0] == pytest.approx(0.3, abs=1e-5)
    m.set_music(to_virtual=True)
    m.mix(voice, zeros, zeros, True, music)
    out, _ = m.mix(voice, zeros, zeros, True, music)
    assert out[-1, 0] == pytest.approx(0.3, abs=1e-5)


# ---------------------------------------------------------------- persistência / controlador
def test_autotune_controller_presets_songs_and_edits(qapp, data_dir, synth_song):
    from core.app_controller import AppController

    ctl = AppController(data_dir / "at.db")
    try:
        at = ctl.autotune
        names = [p.name for p in at.preset_list()]
        assert names == ["Natural Correction", "Light Auto-Tune", "Hard Auto-Tune", "Robotic", "Pop Vocal",
                         "Trap Vocal", "R&B Vocal"]
        hard = next(p for p in at.preset_list() if p.name == "Hard Auto-Tune")
        at.load_preset(hard.id, announce=False)
        assert at.params["retune_ms"] == 0 and ctl.engine.voice._at_params["retune_ms"] == 0
        at.set_params({"humanize": 0.5})
        pid = at.create_preset("Meu")
        assert at.presets.get(pid).data["params"]["humanize"] == 0.5

        song = at.songs.import_file(synth_song[0])
        from autotune.song_analysis import analyze
        at.songs.save_auto_analysis(song.id, analyze(song.file_path))
        at.current_song_id = song.id
        at._rebuild_map()
        at.set_song_key(song.id, 9, "minor")
        assert at.song_map.global_key == (9, "minor") and at.song_map.key_at(30.0) == (9, "minor")
        at.restore_analysis(song.id)
        restored = at.songs.get(song.id)
        assert restored.analysis == restored.analysis_auto and not restored.analysis["key"].get("manual")
        at.link_preset(song.id, pid)
        assert at.songs.get(song.id).preset_id == pid
        at.delete_song(song.id)
        assert at.songs.get(song.id) is None
    finally:
        ctl.autotune.shutdown()
        ctl.engine.shutdown()
        ctl.db.close()
