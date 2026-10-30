"""Cadeia de efeitos da voz, em ordem fixa de processamento."""
from __future__ import annotations

import copy

import numpy as np

from effects.base import Effect
from effects.delay import Echo
from effects.distortion import Distortion
from effects.dynamics import Compressor, NoiseGate
from effects.equalizer import Equalizer
from effects.modulation import Chorus, Robot
from effects.pitch import FormantShift, PitchShift
from effects.reverb import Reverb

#: Ordem de processamento do sinal.
PROCESSING_ORDER: tuple[type[Effect], ...] = (
    NoiseGate,
    Equalizer,
    Compressor,
    PitchShift,
    FormantShift,
    Robot,
    Distortion,
    Chorus,
    Echo,
    Reverb,
)

#: Ordem de exibição na interface.
DISPLAY_ORDER: tuple[type[Effect], ...] = (
    PitchShift,
    FormantShift,
    Reverb,
    Echo,
    Distortion,
    Robot,
    Chorus,
    Equalizer,
    NoiseGate,
    Compressor,
)

EFFECT_CLASSES: dict[str, type[Effect]] = {cls.effect_id: cls for cls in PROCESSING_ORDER}

AUTOTUNE_ID = "autotune"
#: Ordem padrão: Gate → Auto-Tune → pitch/formantes → dinâmica/EQ → efeitos criativos → ambiência.
DEFAULT_ORDER: tuple[str, ...] = (
    "noise_gate", AUTOTUNE_ID, "pitch_shift", "formant_shift", "equalizer", "compressor",
    "robot", "distortion", "chorus", "echo", "reverb",
)


def normalize_order(order: list[str] | None) -> list[str]:
    """Garante que a ordem contenha cada processador exatamente uma vez."""
    valid = list(DEFAULT_ORDER)
    result = [e for e in (order or []) if e in valid]
    result = list(dict.fromkeys(result))
    for e in valid:  # processadores ausentes entram na posição padrão relativa
        if e not in result:
            idx = valid.index(e)
            before = [x for x in valid[:idx] if x in result]
            pos = result.index(before[-1]) + 1 if before else 0
            result.insert(pos, e)
    return result


def default_state() -> dict:
    """Estado neutro: todos os efeitos desligados com parâmetros padrão."""
    return {
        cls.effect_id: {"enabled": False, "params": cls.default_params()} for cls in PROCESSING_ORDER
    }


def normalize_state(state: dict | None) -> dict:
    """Completa/limpa um estado de preset (efeitos ausentes, parâmetros novos ou inválidos)."""
    result = default_state()
    for eid, entry in (state or {}).items():
        cls = EFFECT_CLASSES.get(eid)
        if cls is None or not isinstance(entry, dict):
            continue
        result[eid]["enabled"] = bool(entry.get("enabled", False))
        params = entry.get("params", {}) or {}
        for spec in cls.params_spec:
            if spec.key in params:
                result[eid]["params"][spec.key] = spec.clamp(params[spec.key])
    return result


class EffectChain:
    def __init__(self, samplerate: int, blocksize: int, state: dict | None = None,
                 order: list[str] | None = None):
        from autotune.corrector import AutoTune

        self.samplerate = samplerate
        self.blocksize = blocksize
        self.by_id: dict[str, Effect] = {cls.effect_id: cls(samplerate, blocksize) for cls in PROCESSING_ORDER}
        self.autotune = AutoTune(samplerate, blocksize)
        self.by_id[AUTOTUNE_ID] = self.autotune
        self.effects: list[Effect] = []
        self.set_order(order)
        self._state = default_state()
        self._master = True
        self.apply_state(state or self._state)

    # O estado "do usuário" é mantido aqui; o efetivo depende do master on/off.
    def apply_state(self, state: dict) -> None:
        state = normalize_state(state)
        self._state = copy.deepcopy(state)
        for eid, entry in state.items():
            eff = self.by_id[eid]
            eff.set_params(entry["params"])
            eff.set_enabled(entry["enabled"] and self._master)

    def state(self) -> dict:
        return copy.deepcopy(self._state)

    def set_effect_enabled(self, effect_id: str, enabled: bool) -> None:
        self._state[effect_id]["enabled"] = bool(enabled)
        self.by_id[effect_id].set_enabled(bool(enabled) and self._master)

    def set_effect_params(self, effect_id: str, params: dict) -> None:
        self._state[effect_id]["params"].update(params)
        self.by_id[effect_id].set_params(params)

    def set_master(self, enabled: bool) -> None:
        self._master = bool(enabled)
        for eid, entry in self._state.items():
            self.by_id[eid].set_enabled(entry["enabled"] and self._master)

    def set_order(self, order: list[str] | None) -> None:
        # Troca atômica da lista: a thread de DSP sempre itera uma lista completa.
        self.order = normalize_order(order)
        self.effects = [self.by_id[e] for e in self.order]

    @property
    def master(self) -> bool:
        return self._master

    def latency_s(self) -> float:
        return sum(e.latency_s for e in self.effects if e.enabled)

    def process(self, x: np.ndarray) -> np.ndarray:
        y = x
        for eff in self.effects:  # referência local: troca de ordem não afeta o bloco em andamento
            y = eff.process(y)
        return y
