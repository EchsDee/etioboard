"""Detecção de frequência fundamental (F0) em tempo real com o algoritmo YIN.

A função diferença é calculada via FFT (autocorrelação), com custo O(N log N) por
análise. A detecção roda a cada bloco sobre a janela mais recente do microfone.
"""
from __future__ import annotations

import numpy as np


class YinDetector:
    def __init__(self, samplerate: int, fmin: float = 75.0, fmax: float = 1000.0,
                 window_s: float = 0.025, threshold: float = 0.15, min_rms: float = 0.004):
        self.sr = samplerate
        self.tau_min = max(2, int(samplerate / fmax))
        self.tau_max = int(samplerate / fmin)
        self.W = int(window_s * samplerate)
        self.N = self.W + self.tau_max + 2
        self.threshold = threshold
        self.min_rms = min_rms
        self.fft_n = 1 << int(np.ceil(np.log2(self.N + self.W)))
        self.buf = np.zeros(self.N)
        self.history: list[float] = []
        self.last_f0: float | None = None
        self.last_clarity = 0.0

    def push(self, x: np.ndarray) -> None:
        n = len(x)
        if n >= self.N:
            self.buf[:] = x[-self.N:]
        else:
            self.buf[:-n] = self.buf[n:]
            self.buf[-n:] = x

    def detect(self) -> float | None:
        """Retorna F0 em Hz da janela atual, ou None se não houver voz/periodicidade."""
        x = self.buf
        W, tmax = self.W, self.tau_max
        if np.sqrt(np.mean(np.square(x[-W:]))) < self.min_rms:
            return self._result(None, 0.0)
        frame = x - x.mean()
        a = frame[:W]
        # r(tau) = sum_{j<W} a[j] * frame[j+tau], tau = 0..tmax
        A = np.fft.rfft(a, self.fft_n)
        B = np.fft.rfft(frame, self.fft_n)
        r = np.fft.irfft(np.conj(A) * B, self.fft_n)[: tmax + 1]
        sq = np.concatenate(([0.0], np.cumsum(frame * frame)))
        e0 = sq[W]
        e_tau = sq[np.arange(tmax + 1) + W] - sq[np.arange(tmax + 1)]
        d = e0 + e_tau - 2.0 * r
        d[0] = 0.0
        cum = np.cumsum(d[1:])
        cmnd = np.ones(tmax + 1)
        cmnd[1:] = d[1:] * np.arange(1, tmax + 1) / np.maximum(cum, 1e-12)

        tm = self.tau_min
        below = np.nonzero(cmnd[tm:tmax] < self.threshold)[0]
        if below.size:
            tau = tm + int(below[0])
            while tau + 1 < tmax and cmnd[tau + 1] < cmnd[tau]:
                tau += 1
        else:
            tau = tm + int(np.argmin(cmnd[tm:tmax]))
            if cmnd[tau] > 0.35:
                return self._result(None, 1.0 - float(cmnd[tau]))
        # interpolação parabólica
        if 1 <= tau < tmax:
            y0, y1, y2 = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
            den = y0 - 2 * y1 + y2
            shift = 0.5 * (y0 - y2) / den if abs(den) > 1e-12 else 0.0
            tau_f = tau + max(-1.0, min(1.0, shift))
        else:
            tau_f = float(tau)
        return self._result(self.sr / tau_f, 1.0 - float(cmnd[tau]))

    def _result(self, f0: float | None, clarity: float) -> float | None:
        # Filtro de mediana de 3 para eliminar saltos de oitava isolados.
        self.last_clarity = clarity
        if f0 is None:
            self.history.clear()
            self.last_f0 = None
            return None
        self.history.append(f0)
        if len(self.history) > 3:
            self.history.pop(0)
        self.last_f0 = float(np.median(self.history))
        return self.last_f0
