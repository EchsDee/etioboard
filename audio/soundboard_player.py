"""Reprodutor polifônico de snippets, executado dentro da thread de DSP.

A interface envia comandos por uma fila; a thread de DSP os aplica no início de
cada bloco. Nenhuma decodificação acontece aqui: os dados já chegam prontos.
"""
from __future__ import annotations

import queue
from dataclasses import dataclass

import numpy as np

from effects.base import arange

MAX_VOICES = 32
FADE_S = 0.012


@dataclass
class _Voice:
    voice_id: int
    snippet_id: int
    data: np.ndarray
    volume: float
    speed: float
    loop: bool
    preview: bool
    pos: float = 0.0
    gain: float = 0.0          # ganho atual (suavizado)
    stopping: bool = False
    done: bool = False


class SoundboardPlayer:
    def __init__(self, samplerate: int):
        self.samplerate = samplerate
        self._commands: queue.SimpleQueue = queue.SimpleQueue()
        self._voices: list[_Voice] = []
        self._next_id = 1
        self._fade_step = 1.0 / max(1.0, FADE_S * samplerate)
        #: snapshot publicado para a interface: {snippet_id: (progresso 0..1, preview)}
        self.playing: dict[int, tuple[float, bool]] = {}
        self.peak = 0.0

    def set_samplerate(self, sr: int) -> None:
        self.samplerate = sr
        self._fade_step = 1.0 / max(1.0, FADE_S * sr)

    # ------------------------------------------------- comandos (qualquer thread)
    def play(self, snippet_id: int, data: np.ndarray, volume: float = 1.0, speed: float = 1.0,
             loop: bool = False, preview: bool = False, mode: str = "restart") -> None:
        self._commands.put(("play", snippet_id, data, volume, speed, loop, preview, mode))

    def stop(self, snippet_id: int) -> None:
        self._commands.put(("stop", snippet_id))

    def stop_all(self) -> None:
        self._commands.put(("stop_all",))

    def update(self, snippet_id: int, volume: float | None = None, speed: float | None = None,
               loop: bool | None = None) -> None:
        self._commands.put(("update", snippet_id, volume, speed, loop))

    def clear(self) -> None:
        """Descarta tudo imediatamente (usado ao reiniciar o motor)."""
        while not self._commands.empty():
            try:
                self._commands.get_nowait()
            except queue.Empty:
                break
        self._voices = []
        self.playing = {}

    def is_playing(self, snippet_id: int) -> bool:
        return snippet_id in self.playing

    # ------------------------------------------------- thread de DSP
    def _apply_commands(self) -> None:
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                return
            kind = cmd[0]
            if kind == "play":
                _, sid, data, volume, speed, loop, preview, mode = cmd
                existing = [v for v in self._voices if v.snippet_id == sid and not v.stopping]
                if mode == "toggle" and existing:
                    for v in existing:
                        v.stopping = True
                    continue
                if mode == "restart":
                    for v in existing:
                        v.stopping = True
                voice = _Voice(self._next_id, sid, data, float(volume), max(0.1, float(speed)),
                               bool(loop), bool(preview))
                voice.gain = float(volume)  # início imediato (o arquivo já começa do seu jeito)
                self._next_id += 1
                self._voices.append(voice)
                active = [v for v in self._voices if not v.stopping]
                if len(active) > MAX_VOICES:
                    active[0].stopping = True
            elif kind == "stop":
                for v in self._voices:
                    if v.snippet_id == cmd[1]:
                        v.stopping = True
            elif kind == "stop_all":
                for v in self._voices:
                    v.stopping = True
            elif kind == "update":
                _, sid, volume, speed, loop = cmd
                for v in self._voices:
                    if v.snippet_id == sid:
                        if volume is not None:
                            v.volume = float(volume)
                        if speed is not None:
                            v.speed = max(0.1, float(speed))
                        if loop is not None:
                            v.loop = bool(loop)

    def render(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Retorna (mix principal, mix só de prévia), ambos (n, 2) float32."""
        self._apply_commands()
        main = np.zeros((n, 2), dtype=np.float32)
        preview = np.zeros((n, 2), dtype=np.float32)
        if not self._voices:
            if self.playing:
                self.playing = {}
            self.peak = 0.0
            return main, preview

        steps = arange(n)
        playing: dict[int, tuple[float, bool]] = {}
        for v in self._voices:
            data = v.data
            length = len(data)
            if v.speed == 1.0 and v.pos == int(v.pos):
                idx = int(v.pos) + steps.astype(np.int64)
                if v.loop:
                    idx %= length
                    chunk = data[idx]
                else:
                    valid = idx < length
                    chunk = np.zeros((n, 2), dtype=np.float32)
                    chunk[valid] = data[idx[valid]]
            else:
                p = v.pos + v.speed * steps
                if v.loop:
                    p %= length
                i0 = np.floor(p).astype(np.int64)
                frac = (p - i0)[:, None].astype(np.float32)
                valid = i0 < length
                i0c = np.minimum(i0, length - 1)
                i1 = i0c + 1
                i1 = np.where(i1 >= length, 0 if v.loop else length - 1, i1)
                chunk = data[i0c] * (1.0 - frac) + data[i1] * frac
                chunk[~valid] = 0.0

            target = 0.0 if v.stopping else v.volume
            if v.gain != target:
                direction = 1.0 if target > v.gain else -1.0
                g = v.gain + direction * self._fade_step * (steps + 1.0)
                g = np.clip(g, min(v.gain, target), max(v.gain, target)).astype(np.float32)
                v.gain = float(g[-1])
                chunk = chunk * g[:, None]
            elif v.gain != 1.0:
                chunk = chunk * v.gain

            (preview if v.preview else main)[:] += chunk
            v.pos += v.speed * n
            if v.loop:
                v.pos %= length
            elif v.pos >= length:
                v.done = True
            if v.stopping and v.gain <= 0.0:
                v.done = True
            if not v.done:
                prog = min(1.0, v.pos / length)
                prev = playing.get(v.snippet_id)
                if prev is None or prog > prev[0]:
                    playing[v.snippet_id] = (prog, v.preview)

        self._voices = [v for v in self._voices if not v.done]
        self.playing = playing
        self.peak = float(max(np.abs(main).max(), np.abs(preview).max()))
        return main, preview
