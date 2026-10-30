"""Buffer circular multicanal para troca de áudio entre callbacks e a thread de DSP.

A seção crítica é só uma cópia de memória (numpy), então o lock é seguro para uso
dentro dos callbacks do PortAudio.
"""
from __future__ import annotations

import threading

import numpy as np


class RingBuffer:
    def __init__(self, capacity: int, channels: int):
        self.capacity = int(capacity)
        self.channels = int(channels)
        self._buf = np.zeros((self.capacity, self.channels), dtype=np.float32)
        self._r = 0
        self._count = 0
        self._lock = threading.Lock()
        self.overflows = 0
        self.underruns = 0

    @property
    def available(self) -> int:
        return self._count

    @property
    def free(self) -> int:
        return self.capacity - self._count

    def write(self, data: np.ndarray) -> None:
        """Escreve (frames, channels) ou (frames,). Em overflow, descarta as amostras mais antigas."""
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        n = len(data)
        if n == 0:
            return
        with self._lock:
            if n >= self.capacity:
                data = data[-self.capacity :]
                n = self.capacity
            overflow = n - (self.capacity - self._count)
            if overflow > 0:
                self._r = (self._r + overflow) % self.capacity
                self._count -= overflow
                self.overflows += 1
            w = (self._r + self._count) % self.capacity
            first = min(n, self.capacity - w)
            self._buf[w : w + first] = data[:first]
            if first < n:
                self._buf[: n - first] = data[first:]
            self._count += n

    def read_into(self, out: np.ndarray) -> int:
        """Copia até len(out) frames para `out`; preenche o restante com zeros. Retorna frames lidos."""
        n = len(out)
        with self._lock:
            k = min(n, self._count)
            first = min(k, self.capacity - self._r)
            out[:first] = self._buf[self._r : self._r + first]
            if first < k:
                out[first:k] = self._buf[: k - first]
            self._r = (self._r + k) % self.capacity
            self._count -= k
        if k < n:
            out[k:] = 0.0
            self.underruns += 1
        return k

    def read(self, n: int) -> np.ndarray:
        out = np.empty((n, self.channels), dtype=np.float32)
        self.read_into(out)
        return out

    def discard(self, n: int) -> None:
        with self._lock:
            n = min(n, self._count)
            self._r = (self._r + n) % self.capacity
            self._count -= n

    def clear(self) -> None:
        with self._lock:
            self._r = 0
            self._count = 0
