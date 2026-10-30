"""Testes do soundboard, mixer, buffers e carregamento de arquivos."""
import numpy as np
import pytest

from audio.audio_loader import AudioLoadError, SampleCache, load_audio, probe
from audio.audio_mixer import AudioMixer, soft_limit
from audio.device_manager import DeviceInfo
from audio.ring_buffer import RingBuffer
from audio.soundboard_player import SoundboardPlayer


def test_ring_buffer_roundtrip_and_overflow():
    rb = RingBuffer(10, 2)
    rb.write(np.ones((6, 2), np.float32))
    rb.write(np.full((6, 2), 2, np.float32))  # 2 frames antigas descartadas
    assert rb.available == 10 and rb.overflows == 1
    out = rb.read(12)
    assert out[:4, 0].tolist() == [1, 1, 1, 1] and out[4:10, 0].tolist() == [2] * 6
    assert np.all(out[10:] == 0) and rb.underruns == 1


@pytest.mark.parametrize("fmt,ext", [("WAV", "wav"), ("FLAC", "flac"), ("OGG", "ogg"), ("MP3", "mp3")])
def test_load_all_supported_formats(tone_file, fmt, ext):
    path = tone_file(f"t.{ext}", seconds=0.5, sr=44100, fmt=fmt)
    assert probe(path) == pytest.approx(0.5, abs=0.06)
    data = load_audio(path, 48000)
    assert data.shape[1] == 2 and data.dtype == np.float32
    assert len(data) == pytest.approx(24000, rel=0.1)  # reamostrado para 48 kHz


def test_load_rejects_garbage(tmp_path):
    bad = tmp_path / "x.mp3"
    bad.write_bytes(b"not audio at all" * 100)
    with pytest.raises(AudioLoadError):
        probe(bad)


def test_sample_cache_async_and_invalidate(tone_file):
    path = str(tone_file())
    cache = SampleCache()
    cache.set_samplerate(48000)
    data = cache.request(path).result(timeout=5)
    assert cache.get_cached(path) is data
    cache.invalidate(path)
    assert cache.get_cached(path) is None
    cache.shutdown()


def _sb_data(n=4800, value=0.5):
    return np.full((n, 2), value, np.float32)


def test_soundboard_plays_mixes_and_finishes():
    sb = SoundboardPlayer(48000)
    sb.play(1, _sb_data(1000), volume=1.0)
    sb.play(2, _sb_data(1000, 0.25), volume=1.0)
    main, prev = sb.render(256)
    assert main[0, 0] == pytest.approx(0.75)  # vários sons simultâneos
    assert set(sb.playing) == {1, 2}
    for _ in range(5):
        sb.render(256)
    assert sb.playing == {}


def test_soundboard_stop_all_fades_out():
    sb = SoundboardPlayer(48000)
    sb.play(1, _sb_data(48000), loop=True)
    sb.render(256)
    sb.stop_all()
    main, _ = sb.render(256)
    assert main[0, 0] > main[-1, 0]  # rampa de saída (sem estalo)
    for _ in range(4):
        sb.render(256)
    assert sb.playing == {}


def test_soundboard_loop_speed_and_preview_routing():
    sb = SoundboardPlayer(48000)
    ramp = np.repeat(np.linspace(0, 1, 100, dtype=np.float32)[:, None], 2, axis=1)
    sb.play(1, ramp, loop=True, speed=2.0)
    sb.play(2, _sb_data(1000), preview=True)
    main, prev = sb.render(256)
    assert 1 in sb.playing and sb.playing[2][1] is True
    assert np.all(prev[:, 0] == pytest.approx(0.5))
    assert np.max(main) <= 1.0 and np.min(main) >= 0.0


def test_soundboard_restart_and_toggle_modes():
    sb = SoundboardPlayer(48000)
    sb.play(1, _sb_data(48000), mode="toggle")
    sb.render(64)
    sb.play(1, _sb_data(48000), mode="toggle")  # segundo clique para o som
    for _ in range(4):
        sb.render(256)
    assert 1 not in sb.playing
    sb.play(1, _sb_data(48000), mode="restart")
    sb.play(1, _sb_data(48000), mode="restart")
    sb.render(64)
    active = [v for v in sb._voices if not v.stopping]
    assert len(active) == 1


def test_mixer_routes_voice_and_soundboard():
    mixer = AudioMixer()
    mixer.set_volumes(voice=1.0, soundboard=1.0, master=1.0, monitor=1.0)
    mixer.soundboard.current = 1.0
    mixer.set_monitor_sources(voice=False, soundboard=True)
    mixer.monitor_voice_gain.current = 0.0
    voice = np.full(64, 0.2, np.float32)
    sb = np.full((64, 2), 0.1, np.float32)
    prev = np.full((64, 2), 0.05, np.float32)
    out, mon = mixer.mix(voice, sb, prev, want_monitor=True)
    assert out[-1, 0] == pytest.approx(0.3, abs=1e-5)        # voz + soundboard na saída virtual
    assert mon[-1, 0] == pytest.approx(0.15, abs=1e-5)  # soundboard + prévia, sem a voz


def test_soft_limiter_never_exceeds_one():
    x = np.linspace(-3, 3, 1000, dtype=np.float32)
    y = soft_limit(x)
    assert np.max(np.abs(y)) <= 1.0
    small = np.full(10, 0.5, np.float32)
    assert soft_limit(small) is small


@pytest.mark.parametrize("name,kind", [
    ("CABLE Input (VB-Audio Virtual Cable)", "VB-CABLE"),
    ("CABLE-A Input (VB-Audio Cable A)", "VB-CABLE"),
    ("Voicemeeter Input (VB-Audio Voicemeeter VAIO)", "Voicemeeter"),
    ("Voicemeeter AUX Input (VB-Audio Voicemeeter AUX VAIO)", "Voicemeeter"),
    ("Speakers (Realtek(R) Audio)", None),
])
def test_virtual_device_detection(name, kind):
    d = DeviceInfo(0, name, "Windows WASAPI", 0, 2, 48000.0)
    assert d.virtual_kind() == kind
