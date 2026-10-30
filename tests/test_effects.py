"""Testes do processamento de voz: correção, estabilidade e orçamento de tempo real."""
import time

import numpy as np
import pytest

from effects.chain import EFFECT_CLASSES, EffectChain, default_state, normalize_state
from presets.builtin import BUILTIN_PRESETS

SR, BS = 48000, 256


def _run(state, x, bs=BS):
    chain = EffectChain(SR, bs, state)
    out = [chain.process(x[i:i + bs]) for i in range(0, len(x) - bs + 1, bs)]
    return np.concatenate(out), chain


def _tone(freq=220.0, seconds=1.5, amp=0.3):
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _peak_freq(y):
    y = y[SR // 2:]
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    return np.argmax(spec) * SR / len(y)


@pytest.mark.parametrize("eid", list(EFFECT_CLASSES))
def test_each_effect_is_finite_and_bounded(eid):
    st = default_state()
    st[eid]["enabled"] = True
    noise = (np.random.default_rng(0).standard_normal(SR) * 0.2).astype(np.float32)
    y, _ = _run(st, noise)
    assert np.all(np.isfinite(y))
    assert np.max(np.abs(y)) < 4.0


@pytest.mark.parametrize("semitones", [-12, -5, 3, 7, 12])
def test_pitch_shift_accuracy_and_no_amplitude_ripple(semitones):
    st = default_state()
    st["pitch_shift"] = {"enabled": True, "params": {"semitones": semitones}}
    y, _ = _run(st, _tone())
    expected = 220 * 2 ** (semitones / 12)
    assert abs(_peak_freq(y) - expected) < 2.0
    seg = y[SR // 2:]
    env = np.abs(seg[: len(seg) // 480 * 480]).reshape(-1, 480).max(axis=1)
    assert env.min() > 0.27 and env.max() < 0.33


def test_formant_shift_preserves_pitch():
    st = default_state()
    st["formant_shift"] = {"enabled": True, "params": {"shift": 5}}
    y, _ = _run(st, _tone())
    assert abs(_peak_freq(y) - 220) < 1.5


def test_disabled_chain_is_bit_exact_passthrough():
    x = _tone()
    y, _ = _run(default_state(), x)
    np.testing.assert_array_equal(y, x[: len(y)])


def test_toggle_effect_crossfades_without_clicks():
    x = _tone(seconds=1.0)
    chain = EffectChain(SR, BS, default_state())
    out = []
    for i in range(0, len(x) - BS + 1, BS):
        if i == BS * 40:
            chain.set_effect_enabled("distortion", True)
        out.append(chain.process(x[i:i + BS]))
    y = np.concatenate(out)
    assert np.max(np.abs(np.diff(y))) < 0.2  # sem descontinuidades bruscas


def test_master_bypass_turns_effects_off():
    st = default_state()
    st["robot"]["enabled"] = True
    chain = EffectChain(SR, BS, st)
    chain.set_master(False)
    x = _tone(seconds=0.5)
    outs = [chain.process(x[i:i + BS]) for i in range(0, len(x) - BS + 1, BS)]
    np.testing.assert_allclose(outs[-1], x[len(outs) * BS - BS: len(outs) * BS], atol=1e-6)


def test_normalize_state_fills_missing_and_clamps():
    st = normalize_state({"pitch_shift": {"enabled": True, "params": {"semitones": 99}}, "bogus": {}})
    assert st["pitch_shift"]["params"]["semitones"] == 12.0
    assert set(st) == set(EFFECT_CLASSES)
    assert st["reverb"]["enabled"] is False


@pytest.mark.parametrize("key,name,state", BUILTIN_PRESETS)
def test_builtin_presets_fit_realtime_budget(key, name, state):
    x = (np.random.default_rng(1).standard_normal(SR * 2) * 0.2).astype(np.float32)
    chain = EffectChain(SR, BS, state)
    for i in range(0, SR // 2, BS):  # aquecimento
        chain.process(x[i:i + BS])
    times = []
    for i in range(SR // 2, len(x) - BS + 1, BS):
        t0 = time.perf_counter()
        y = chain.process(x[i:i + BS])
        times.append(time.perf_counter() - t0)
        assert np.all(np.isfinite(y))
    budget = BS / SR
    assert np.mean(times) < budget * 0.35, f"{name}: média {np.mean(times)*1000:.2f} ms"
    assert chain.latency_s() < 0.035
