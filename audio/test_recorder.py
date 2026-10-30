"""Gravação curta do que sai para a saída virtual, para o usuário ouvir como os outros o escutam."""
from __future__ import annotations

import threading
from typing import Callable

import numpy as np


class TestRecorder:
    """Alimentado pela thread de DSP; entrega a gravação pronta ao callback (na thread de DSP)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buf: np.ndarray | None = None
        self._pos = 0
        self._on_done: Callable[[np.ndarray], None] | None = None

    @property
    def active(self) -> bool:
        return self._buf is not None

    @property
    def progress(self) -> float:
        buf = self._buf
        return self._pos / len(buf) if buf is not None and len(buf) else 0.0

    def start(self, seconds: float, samplerate: int, on_done: Callable[[np.ndarray], None]) -> None:
        with self._lock:
            self._buf = np.zeros((max(1, int(seconds * samplerate)), 2), dtype=np.float32)
            self._pos = 0
            self._on_done = on_done

    def cancel(self) -> None:
        with self._lock:
            self._buf = None
            self._on_done = None

    def feed(self, block: np.ndarray) -> None:
        if self._buf is None:
            return
        with self._lock:
            buf = self._buf
            if buf is None:
                return
            n = min(len(block), len(buf) - self._pos)
            buf[self._pos : self._pos + n] = block[:n]
            self._pos += n
            if self._pos < len(buf):
                return
            callback, self._on_done, self._buf = self._on_done, None, None
        if callback:
            callback(buf)
