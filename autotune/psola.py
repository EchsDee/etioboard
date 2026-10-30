"""TD-PSOLA em tempo real (Pitch-Synchronous Overlap-Add).

Cada período da voz vira um "grão" (janela de Hann de 2 períodos centrada numa marca
de análie). Para mudar a afinação, os grãos são recolocados com espaçamento igual ao
período-alvo — sem reamostrar o conteúdo — o que preserva naturalmente as formantes
(o timbre). Com razão 1 a reconstrução é idêntica à entrada (apenas atrasada).

Latência fixa: 2 × o maior período suportado (≈ 26 ms com fmin = 75 Hz).
"""
from __future__ import annotations

from collections import deque

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


class _Mark:
    __slots__ = ("pos", "period", "ratio", "voiced")

    def __init__(self, pos: int, period: int, ratio: float, voiced: bool):
        # ratio = período de saída / período de entrada (1 = sem correção)
        self.pos, self.period, self.ratio, self.voiced = pos, period, ratio, voiced


class PsolaShifter:
    def __init__(self, samplerate: int, fmin: float = 75.0):
        self.sr = samplerate
        self.hmax = int(samplerate / fmin)
        self.latency = 2 * self.hmax
        size = 1
        while size < self.hmax * 12 + 8192:
            size <<= 1
        self.size, self.mask = size, size - 1
        self.inbuf = np.zeros(size)
        self.acc = np.zeros(size)
        self.wsum = np.zeros(size)
        self.t_in = 0
        self.marks: deque[_Mark] = deque()
        self.next_mark: int | None = None
        self.next_syn: float | None = None
        self.unvoiced_period = int(0.005 * samplerate)
        #: 1 = preserva formantes (PSOLA puro); 0 = formantes acompanham o tom (reamostra os grãos)
        self.formant_keep = 1.0
        self._windows: dict[int, np.ndarray] = {}

    # ------------------------------------------------------------------ util
    def _idx(self, start: int, length: int) -> np.ndarray:
        return (np.arange(start, start + length, dtype=np.int64)) & self.mask

    def _window(self, h: int) -> np.ndarray:
        w = self._windows.get(h)
        if w is None:
            w = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(2 * h) / (2 * h))  # Hann periódica: soma 1 a cada h
            self._windows[h] = w
        return w

    def _refine(self, cand: int, prev: _Mark, period: int) -> int:
        """Ajusta a nova marca para manter a fase do período anterior (correlação cruzada)."""
        h = max(8, period // 2)
        s = max(2, period // 8)
        if cand + s + h > self.t_in or not prev.voiced:
            return cand
        template = self.inbuf[self._idx(prev.pos - h, 2 * h)]
        big = self.inbuf[self._idx(cand - s - h, 2 * s + 2 * h)]
        segs = sliding_window_view(big, 2 * h)[: 2 * s + 1]
        norms = np.sqrt(np.einsum("ij,ij->i", segs, segs)) + 1e-9
        score = (segs @ template) / norms
        score -= 0.05 * np.abs(np.arange(-s, s + 1)) / s * (np.abs(score).max() + 1e-9)
        return cand - s + int(np.argmax(score))

    # ------------------------------------------------------------------ processamento
    def process(self, x: np.ndarray, period: float | None, target_period: float | None) -> np.ndarray:
        """`period`: período detectado (amostras) ou None se não houver voz.
        `target_period`: período desejado na saída (None = sem correção)."""
        n = len(x)
        self.inbuf[self._idx(self.t_in, n)] = x
        self.t_in += n
        voiced = period is not None
        p_a = int(round(min(max(period, 16), self.hmax))) if voiced else self.unvoiced_period
        ratio = float(target_period) / float(period) if (voiced and target_period) else 1.0

        # --- marcas de análise
        if self.next_mark is None:
            self.next_mark = self.t_in - n
        while True:
            cand = self.next_mark
            if cand + p_a // 2 + max(2, p_a // 8) > self.t_in:
                break
            if voiced and self.marks:
                cand = self._refine(cand, self.marks[-1], p_a)
            self.marks.append(_Mark(cand, p_a, ratio, voiced))
            self.next_mark = cand + p_a

        # --- marcas de síntese (overlap-add)
        u_end = self.t_in - self.latency
        if self.next_syn is None and self.marks:
            self.next_syn = float(self.marks[0].pos)
        if self.next_syn is not None and self.next_syn < u_end - n - self.hmax:
            self.next_syn = float(u_end - n - self.hmax)  # recupera após pausa longa
        while self.next_syn is not None and self.next_syn < u_end + self.hmax and self.marks:
            s = int(round(self.next_syn))
            while len(self.marks) > 1 and self.marks[1].pos <= s:
                self.marks.popleft()
            a = self.marks[0]
            p_s = a.period * a.ratio
            h = int(min(max(a.period, p_s), self.hmax))
            grain = self.inbuf[self._idx(a.pos - h, 2 * h)]
            if a.voiced and self.formant_keep < 0.999 and abs(a.ratio - 1.0) > 1e-3:
                k = (1.0 / a.ratio) ** (1.0 - self.formant_keep)  # reamostra o grão: formantes acompanham o tom
                pos = h + (np.arange(2 * h) - h) * k
                grain = np.interp(pos, np.arange(2 * h), grain, left=0.0, right=0.0)
            w = self._window(h)
            idx = self._idx(s - h, 2 * h)
            self.acc[idx] += grain * w
            self.wsum[idx] += w
            # Passo = distância real até a próxima marca × razão de período. Com razão 1 as marcas de
            # síntese coincidem com as de análise (reconstrução exata); sem jitter de fase.
            if len(self.marks) > 1:
                step = (self.marks[1].pos - a.pos) * a.ratio
            else:
                step = p_s
            self.next_syn += max(8.0, step)

        # --- saída finalizada: [u_end - n, u_end)
        idx = self._idx(u_end - n, n)
        out = self.acc[idx] / np.maximum(self.wsum[idx], 0.35)
        self.acc[idx] = 0.0
        self.wsum[idx] = 0.0
        if u_end - n < 0:
            out[: min(n, n - u_end)] = 0.0
        return out
