"""Player da música de referência do Song Mode (roda dentro da thread de DSP).

A posição é contada em amostras, com precisão de amostra: é ela que o Auto-Tune usa
para saber quais notas são permitidas em cada instante (sincronização por timestamp,
sem depender do BPM).
"""
from __future__ import annotations

import queue

import numpy as np


class SongPlayer:
    def __init__(self, samplerate: int):
        self.samplerate = samplerate
        self._commands: queue.SimpleQueue = queue.SimpleQueue()
        self._data: np.ndarray | None = None
        self.song_id: int | None = None
        self.position = 0          # amostra no início do próximo bloco
        self.block_start = 0       # amostra no início do último bloco renderizado
        self.playing = False
        self.peak = 0.0

    # ------------------------------------------------------- comandos (qualquer thread)
    def load(self, song_id: int, data: np.ndarray) -> None:
        self._commands.put(("load", song_id, data))

    def unload(self) -> None:
        self._commands.put(("unload",))

    def play(self) -> None:
        self._commands.put(("play",))

    def pause(self) -> None:
        self._commands.put(("pause",))

    def stop(self) -> None:
        self._commands.put(("stop",))

    def seek(self, seconds: float) -> None:
        self._commands.put(("seek", seconds))

    @property
    def duration(self) -> float:
        d = self._data
        return len(d) / self.samplerate if d is not None else 0.0

    @property
    def position_s(self) -> float:
        return self.position / self.samplerate

    @property
    def loaded(self) -> bool:
        return self._data is not None

    def set_samplerate(self, sr: int) -> None:
        if sr != self.samplerate:
            self._commands.put(("unload",))
        self.samplerate = sr

    # ------------------------------------------------------- thread de DSP
    def _apply(self) -> None:
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                return
            kind = cmd[0]
            if kind == "load":
                self.song_id, self._data = cmd[1], cmd[2]
                self.position = 0
                self.playing = False
            elif kind == "unload":
                self.song_id, self._data, self.playing, self.position = None, None, False, 0
            elif kind == "play" and self._data is not None:
                if self.position >= len(self._data):
                    self.position = 0
                self.playing = True
            elif kind == "pause":
                self.playing = False
            elif kind == "stop":
                self.playing = False
                self.position = 0
            elif kind == "seek" and self._data is not None:
                self.position = int(min(max(cmd[1], 0.0) * self.samplerate, len(self._data)))

    def render(self, n: int) -> np.ndarray | None:
        """Bloco estéreo (n, 2) ou None se não estiver tocando."""
        self._apply()
        self.block_start = self.position
        data = self._data
        if not self.playing or data is None:
            self.peak = 0.0
            return None
        end = min(self.position + n, len(data))
        out = np.zeros((n, 2), dtype=np.float32)
        out[: end - self.position] = data[self.position:end]
        self.position = end
        if end >= len(data):
            self.playing = False
        self.peak = float(np.max(np.abs(out))) if out.size else 0.0
        return out
