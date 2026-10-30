"""Utilitários de DSP: biquads (RBJ Audio EQ Cookbook) e linhas de atraso."""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter

from effects.base import arange


def _norm(b0, b1, b2, a0, a1, a2) -> np.ndarray:
    return np.array([b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0], dtype=np.float64)


def _w0(freq: float, sr: float) -> float:
    freq = min(max(freq, 5.0), sr * 0.49)
    return 2.0 * math.pi * freq / sr


def biquad_lowpass(freq: float, sr: float, q: float = 0.7071) -> np.ndarray:
    w0 = _w0(freq, sr)
    alpha = math.sin(w0) / (2 * q)
    c = math.cos(w0)
    return _norm((1 - c) / 2, 1 - c, (1 - c) / 2, 1 + alpha, -2 * c, 1 - alpha)


def biquad_highpass(freq: float, sr: float, q: float = 0.7071) -> np.ndarray:
    w0 = _w0(freq, sr)
    alpha = math.sin(w0) / (2 * q)
    c = math.cos(w0)
    return _norm((1 + c) / 2, -(1 + c), (1 + c) / 2, 1 + alpha, -2 * c, 1 - alpha)


def biquad_peak(freq: float, sr: float, gain_db: float, q: float = 1.0) -> np.ndarray:
    a = 10 ** (gain_db / 40)
    w0 = _w0(freq, sr)
    alpha = math.sin(w0) / (2 * q)
    c = math.cos(w0)
    return _norm(1 + alpha * a, -2 * c, 1 - alpha * a, 1 + alpha / a, -2 * c, 1 - alpha / a)


def biquad_lowshelf(freq: float, sr: float, gain_db: float) -> np.ndarray:
    a = 10 ** (gain_db / 40)
    w0 = _w0(freq, sr)
    c = math.cos(w0)
    alpha = math.sin(w0) / 2 * math.sqrt(2)  # S = 1
    sq = 2 * math.sqrt(a) * alpha
    return _norm(
        a * ((a + 1) - (a - 1) * c + sq),
        2 * a * ((a - 1) - (a + 1) * c),
        a * ((a + 1) - (a - 1) * c - sq),
        (a + 1) + (a - 1) * c + sq,
        -2 * ((a - 1) + (a + 1) * c),
        (a + 1) + (a - 1) * c - sq,
    )


def biquad_highshelf(freq: float, sr: float, gain_db: float) -> np.ndarray:
    a = 10 ** (gain_db / 40)
    w0 = _w0(freq, sr)
    c = math.cos(w0)
    alpha = math.sin(w0) / 2 * math.sqrt(2)
    sq = 2 * math.sqrt(a) * alpha
    return _norm(
        a * ((a + 1) + (a - 1) * c + sq),
        -2 * a * ((a - 1) + (a + 1) * c),
        a * ((a + 1) + (a - 1) * c - sq),
        (a + 1) - (a - 1) * c + sq,
        2 * ((a - 1) - (a + 1) * c),
        (a + 1) - (a - 1) * c - sq,
    )


class OnePoleLowpass:
    """Passa-baixas de 1 polo com estado (para amortecimento em realimentações)."""

    def __init__(self):
        self.coef = 0.0
        self.zi = np.zeros(1)

    def set_damping(self, d: float) -> None:
        self.coef = float(min(max(d, 0.0), 0.99))

    def set_cutoff(self, freq: float, sr: float) -> None:
        self.set_damping(math.exp(-2 * math.pi * min(freq, sr * 0.49) / sr))

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.coef <= 0.0:
            return x
        y, self.zi = lfilter([1.0 - self.coef], [1.0, -self.coef], x, zi=self.zi)
        return y

    def reset(self) -> None:
        self.zi = np.zeros(1)


class DelayLine:
    """Buffer circular com leitura fracionária (interpolação linear)."""

    def __init__(self, max_delay: int):
        size = 1
        while size < max_delay + 8:
            size <<= 1
        self.size = size
        self.mask = size - 1
        self.buf = np.zeros(size, dtype=np.float64)
        self.w = 0  # contador absoluto de escrita

    def write(self, x: np.ndarray) -> None:
        n = len(x)
        start = self.w & self.mask
        end = start + n
        if end <= self.size:
            self.buf[start:end] = x
        else:
            k = self.size - start
            self.buf[start:] = x[:k]
            self.buf[: n - k] = x[k:]
        self.w += n

    def read_fractional(self, delays: np.ndarray, n: int) -> np.ndarray:
        """Lê n amostras do último bloco escrito, com atraso (em amostras) por amostra."""
        pos = (self.w - n) + arange(n) - delays
        i0 = np.floor(pos)
        frac = pos - i0
        i0 = i0.astype(np.int64)
        a = self.buf[i0 & self.mask]
        b = self.buf[(i0 + 1) & self.mask]
        return a + (b - a) * frac

    def read_fixed(self, delay: int, n: int) -> np.ndarray:
        """Lê n amostras atrasadas de `delay` amostras em relação à próxima escrita."""
        start = (self.w - delay) & self.mask
        end = start + n
        if end <= self.size:
            return self.buf[start:end].copy()
        k = self.size - start
        return np.concatenate((self.buf[start:], self.buf[: n - k]))

    def reset(self) -> None:
        self.buf[:] = 0.0
        self.w = 0


class FeedbackComb:
    """Filtro pente realimentado y[n] = x[n] + fb * lp(y[n-D]), vetorizado em blocos <= D."""

    def __init__(self, delay: int):
        self.line = DelayLine(max(delay, 1) + 4096)
        self.delay = max(1, int(delay))
        self.feedback = 0.5
        self.lp = OnePoleLowpass()

    def process(self, x: np.ndarray) -> np.ndarray:
        out = np.empty(len(x), dtype=np.float64)
        pos = 0
        n = len(x)
        d = self.delay
        while pos < n:
            k = min(d, n - pos)
            delayed = self.line.read_fixed(d, k)
            y = x[pos : pos + k] + self.feedback * self.lp.process(delayed)
            self.line.write(y)
            out[pos : pos + k] = y
            pos += k
        return out

    def reset(self) -> None:
        self.line.reset()
        self.lp.reset()
