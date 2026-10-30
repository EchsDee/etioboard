"""Decodificação de arquivos de áudio (WAV/MP3/OGG/FLAC via libsndfile) e cache em memória.

A decodificação e a reamostragem acontecem em threads de trabalho, nunca na thread
de DSP nem na interface.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from math import gcd
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".wav", ".mp3", ".ogg", ".flac")


class AudioLoadError(Exception):
    pass


def probe(path: str | Path) -> float:
    """Valida o arquivo e retorna a duração em segundos."""
    try:
        info = sf.info(str(path))
    except Exception as exc:  # noqa: BLE001
        raise AudioLoadError(f"Formato não suportado ou arquivo corrompido: {exc}") from exc
    if info.frames <= 0 or info.samplerate <= 0:
        # Alguns MP3 não informam o número de frames; decodifica para medir.
        data, sr = _read(path)
        return len(data) / sr
    return info.frames / info.samplerate


def _read(path: str | Path) -> tuple[np.ndarray, int]:
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:  # noqa: BLE001
        raise AudioLoadError(f"Não foi possível decodificar '{Path(path).name}': {exc}") from exc
    if len(data) == 0:
        raise AudioLoadError("O arquivo não contém áudio.")
    return data, sr


def load_audio(path: str | Path, samplerate: int) -> np.ndarray:
    """Carrega o arquivo como float32 estéreo (frames, 2) na taxa de amostragem do motor."""
    data, sr = _read(path)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    if sr != samplerate:
        g = gcd(int(sr), int(samplerate))
        data = resample_poly(data, samplerate // g, sr // g, axis=0).astype(np.float32)
    peak = float(np.max(np.abs(data))) if len(data) else 0.0
    if peak > 1.0:
        data /= peak
    return np.ascontiguousarray(data, dtype=np.float32)


class SampleCache:
    """Cache LRU dos áudios decodificados, com pré-carregamento assíncrono."""

    def __init__(self, max_bytes: int = 768 * 1024 * 1024):
        self.max_bytes = max_bytes
        self.samplerate = 48000
        self._items: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self._pending: dict[tuple, Future] = {}
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audio-loader")

    def set_samplerate(self, sr: int) -> None:
        with self._lock:
            if sr != self.samplerate:
                self.samplerate = sr
                self._items.clear()
                self._bytes = 0

    def _key(self, path: str) -> tuple:
        return (str(path), self.samplerate)

    def get_cached(self, path: str) -> np.ndarray | None:
        key = self._key(path)
        with self._lock:
            data = self._items.get(key)
            if data is not None:
                self._items.move_to_end(key)
            return data

    def _store(self, key: tuple, data: np.ndarray) -> None:
        with self._lock:
            if key[1] != self.samplerate:
                return
            if key in self._items:
                return
            self._items[key] = data
            self._bytes += data.nbytes
            while self._bytes > self.max_bytes and len(self._items) > 1:
                _, old = self._items.popitem(last=False)
                self._bytes -= old.nbytes

    def request(
        self, path: str, callback: Callable[[np.ndarray | None, str | None], None] | None = None
    ) -> Future:
        """Carrega em segundo plano; o callback recebe (dados, erro) na thread de trabalho."""
        key = self._key(path)
        cached = self.get_cached(path)
        fut: Future
        if cached is not None:
            fut = Future()
            fut.set_result(cached)
        else:
            with self._lock:
                fut = self._pending.get(key)
                if fut is None:
                    fut = self._pool.submit(self._load, key)
                    self._pending[key] = fut
        if callback is not None:
            def _done(f: Future):
                try:
                    callback(f.result(), None)
                except Exception as exc:  # noqa: BLE001
                    callback(None, str(exc))
            fut.add_done_callback(_done)
        return fut

    def _load(self, key: tuple) -> np.ndarray:
        try:
            data = load_audio(key[0], key[1])
            self._store(key, data)
            return data
        finally:
            with self._lock:
                self._pending.pop(key, None)

    def invalidate(self, path: str) -> None:
        with self._lock:
            for key in [k for k in self._items if k[0] == str(path)]:
                self._bytes -= self._items.pop(key).nbytes

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
