"""Auto-Tune: correção de afinação em tempo real (YIN + TD-PSOLA).

Distingue explicitamente três coisas, expostas para a interface:
  * a nota que o usuário está cantando (detected_midi, contínua);
  * as notas permitidas pela escala/harmonia naquele instante;
  * a nota de destino escolhida pelo algoritmo (target_midi).
"""
from __future__ import annotations

import math
import threading

import numpy as np

from autotune.music import hz_to_midi, nearest_in_set, scale_pitch_classes
from autotune.pitch_detector import YinDetector
from autotune.psola import PsolaShifter
from autotune.song_map import SongMap
from effects.base import Effect, ParamSpec

CHORD_PREFERENCE = 0.35   # semitons de "vantagem" das notas do acorde no Chord Mode
HYSTERESIS = 0.12         # semitons além do meio-caminho antes de trocar de nota
UNVOICED_HOLD_S = 0.06


class AutoTune(Effect):
    effect_id = "autotune"
    display_name = "Auto-Tune"
    description = "Correção automática de afinação."
    params_spec = (
        ParamSpec("amount", "Correction Amount", 0.0, 1.0, 1.0, 0.01, "", 2),
        ParamSpec("retune_ms", "Retune Speed", 0.0, 400.0, 40.0, 1.0, "ms", 0),
        ParamSpec("humanize", "Humanize", 0.0, 1.0, 0.3, 0.01, "", 2),
        ParamSpec("flex_cents", "Flex Tune", 0.0, 100.0, 0.0, 1.0, "cents", 0),
        ParamSpec("formant", "Formant Preservation", 0.0, 1.0, 1.0, 0.01, "", 2),
        ParamSpec("ref_hz", "Reference Pitch", 415.0, 466.0, 440.0, 0.1, "Hz", 1),
    )

    def __init__(self, samplerate: int, blocksize: int):
        self._cfg_lock = threading.Lock()
        self.key = 0
        self.scale = "chromatic"
        self.source = "realtime"        # realtime | song
        self.song_mode = "scale"        # scale | chord | melody
        self.song_map: SongMap | None = None
        self.song_time: float | None = None   # posição (s) da música no bloco atual, já compensada
        # telemetria (lida pela interface)
        self.detected_midi: float | None = None
        self.target_midi: float | None = None
        self.output_midi: float | None = None
        self.allowed_pcs: frozenset[int] = frozenset(range(12))
        self.chord_label = ""
        self._learn: np.ndarray | None = None
        super().__init__(samplerate, blocksize)
        self.latency_s = self.psola.latency / self.sr

    # ------------------------------------------------------------ configuração
    def set_config(self, **cfg) -> None:
        with self._cfg_lock:
            for k in ("key", "scale", "source", "song_mode"):
                if k in cfg and cfg[k] is not None:
                    setattr(self, k, cfg[k])
            if "song_map" in cfg:
                self.song_map = cfg["song_map"]
            self._scale_pcs = scale_pitch_classes(int(self.key), self.scale)

    def start_key_learning(self) -> None:
        self._learn = np.zeros(12)

    def stop_key_learning(self) -> np.ndarray | None:
        hist, self._learn = self._learn, None
        return hist

    def configure(self) -> None:
        if not hasattr(self, "psola"):
            self.psola = PsolaShifter(int(self.sr))
            self.detector = YinDetector(int(self.sr))
            self._scale_pcs = scale_pitch_classes(int(self.key), self.scale)
        self.psola.formant_keep = self.params["formant"]

    def reset(self) -> None:
        self.psola = PsolaShifter(int(self.sr))
        self.psola.formant_keep = self.params["formant"]
        self.detector = YinDetector(int(self.sr))
        self.shift = 0.0            # correção aplicada (semitons), suavizada
        self.slow_midi = None       # média lenta da voz (para o Humanize)
        self.current_note = None    # nota-alvo atual (com histerese)
        self.unvoiced_time = 0.0
        self.detected_midi = self.target_midi = self.output_midi = None

    # ------------------------------------------------------------ escolha da nota
    def _candidates(self) -> tuple[frozenset[int], frozenset[int] | None, int | None]:
        """(notas permitidas, notas do acorde preferidas, nota de melodia)."""
        if self.source == "song" and self.song_map is not None:
            t = self.song_time
            if t is None:  # música parada: tonalidade global da música
                tonic, mode = self.song_map.global_key
                self.chord_label = ""
                return scale_pitch_classes(tonic, mode), None, None
            h = self.song_map.at(t)
            self.chord_label = h.chord_label
            if self.song_mode == "scale":
                return h.scale_pcs, None, None
            if self.song_mode == "chord":
                return h.scale_pcs, h.chord_pcs, None
            return h.scale_pcs, h.chord_pcs, h.melody_midi
        self.chord_label = ""
        return self._scale_pcs, None, None

    def _choose_target(self, midi: float) -> float:
        scale_pcs, chord_pcs, melody = self._candidates()
        self.allowed_pcs = chord_pcs if (chord_pcs and self.song_mode in ("chord", "melody")) else scale_pcs
        if melody is not None:
            # melodia de referência: mesma classe de nota, oitava mais próxima do que está sendo cantado
            target = melody + 12 * round((midi - melody) / 12)
            self.allowed_pcs = frozenset({melody % 12})
            self.current_note = float(target)
            return float(target)
        cur = self.current_note
        if cur is not None and abs(midi - cur) < 0.5 + HYSTERESIS:
            pcs_ok = int(cur) % 12 in scale_pcs or (chord_pcs is not None and int(cur) % 12 in chord_pcs)
            if pcs_ok:
                return cur
        best = nearest_in_set(midi, scale_pcs)
        if chord_pcs:
            chord_best = nearest_in_set(midi, chord_pcs)
            if abs(chord_best - midi) - CHORD_PREFERENCE <= abs(best - midi):
                best = chord_best
        self.current_note = best
        return best

    # ------------------------------------------------------------ processamento
    def process_block(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        dt = n / self.sr
        p = self.params
        det = self.detector
        det.push(x)
        f0 = det.detect()
        with self._cfg_lock:
            if f0 is not None:
                self.unvoiced_time = 0.0
                midi = hz_to_midi(f0, p["ref_hz"])
                if self._learn is not None:
                    self._learn[int(round(midi)) % 12] += max(0.1, det.last_clarity)
                target = self._choose_target(midi)
                # Humanize: preserva as variações rápidas (vibrato) em torno da nota corrigida
                if self.slow_midi is None or abs(midi - self.slow_midi) > 1.5:
                    self.slow_midi = midi
                else:
                    self.slow_midi += (midi - self.slow_midi) * (1 - math.exp(-dt / 0.18))
                deviation = target - midi
                flex = p["flex_cents"]
                if flex > 0:
                    cents = abs(deviation) * 100
                    deviation *= min(1.0, (cents / flex) ** 2)
                desired = p["amount"] * (deviation + p["humanize"] * (midi - self.slow_midi))
                tau = p["retune_ms"] / 1000.0
                self.shift = desired if tau <= 1e-4 else self.shift + (desired - self.shift) * (1 - math.exp(-dt / tau))
                self.detected_midi, self.target_midi = midi, target
                self.output_midi = midi + self.shift
                period = self.sr / f0
                target_period = period / (2.0 ** (self.shift / 12.0))
                return self.psola.process(x, period, target_period)

            self.unvoiced_time += dt
            if self.unvoiced_time > UNVOICED_HOLD_S:
                self.shift *= math.exp(-dt / 0.03)
                self.detected_midi = self.target_midi = self.output_midi = None
                self.current_note = None
            return self.psola.process(x, None, None)
