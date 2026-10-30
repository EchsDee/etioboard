"""Classe base dos efeitos de áudio em tempo real.

Todos os efeitos processam blocos mono float32 e mantêm estado entre blocos.
Os parâmetros são alterados de forma thread-safe pela interface (`set_params`)
e aplicados pela thread de DSP no início do próximo bloco. Ativar/desativar
um efeito faz um crossfade curto (~10 ms) para evitar estalos.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    minimum: float
    maximum: float
    default: float
    step: float = 0.01
    unit: str = ""
    decimals: int = 2
    log: bool = False  # slider em escala logarítmica (frequências)

    def clamp(self, value: float) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return self.default
        if math.isnan(value):
            return self.default
        return min(self.maximum, max(self.minimum, value))


_ARANGE_CACHE: dict[int, np.ndarray] = {}


def arange(n: int) -> np.ndarray:
    """np.arange(n) em float64, com cache (evita alocações na thread de DSP)."""
    arr = _ARANGE_CACHE.get(n)
    if arr is None:
        arr = np.arange(n, dtype=np.float64)
        _ARANGE_CACHE[n] = arr
    return arr


class Effect:
    effect_id: str = ""
    display_name: str = ""
    description: str = ""
    params_spec: tuple[ParamSpec, ...] = ()
    #: latência adicionada pelo efeito, em segundos (informativo)
    latency_s: float = 0.0

    FADE_S = 0.010

    def __init__(self, samplerate: int, blocksize: int):
        self.sr = float(samplerate)
        self.blocksize = int(blocksize)
        self.params: dict[str, float] = {p.key: p.default for p in self.params_spec}
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._enabled = False
        self._gain = 0.0
        self._fade_step = 1.0 / max(1.0, self.FADE_S * self.sr)
        self.configure()
        self.reset()

    # ----------------------------------------------------------- API pública
    @classmethod
    def default_params(cls) -> dict[str, float]:
        return {p.key: p.default for p in cls.params_spec}

    @classmethod
    def spec(cls, key: str) -> ParamSpec:
        for p in cls.params_spec:
            if p.key == key:
                return p
        raise KeyError(key)

    def set_params(self, values: dict) -> None:
        clean = {}
        for p in self.params_spec:
            if p.key in values:
                clean[p.key] = p.clamp(values[p.key])
        if clean:
            with self._lock:
                self._pending.update(clean)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def active(self) -> bool:
        return self._enabled or self._gain > 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        if self._pending:
            with self._lock:
                pending, self._pending = self._pending, {}
            self.params.update(pending)
            self.configure()

        target = 1.0 if self._enabled else 0.0
        if target == 0.0 and self._gain == 0.0:
            return x

        y = self.process_block(x)
        if self._gain == target:
            return y

        n = len(x)
        direction = 1.0 if target > self._gain else -1.0
        g = self._gain + direction * self._fade_step * (arange(n) + 1.0)
        np.clip(g, 0.0, 1.0, out=g)
        self._gain = float(g[-1])
        out = (x + (y - x) * g).astype(np.float32, copy=False)
        if self._gain == 0.0:
            self.reset()
        return out

    # ------------------------------------------------- implementado pelos efeitos
    def configure(self) -> None:
        """Recalcula coeficientes a partir de self.params."""

    def reset(self) -> None:
        """Limpa o estado interno (buffers, filtros)."""

    def process_block(self, x: np.ndarray) -> np.ndarray:
        raise NotImplementedError


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def lin_to_db(x: np.ndarray | float) -> np.ndarray | float:
    return 20.0 * np.log10(np.maximum(x, 1e-9))
