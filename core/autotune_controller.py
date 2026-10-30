"""Controlador do Auto-Tune Studio: parâmetros, presets, músicas, análise e sincronização."""
from __future__ import annotations

import copy
import logging
import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from audio.audio_loader import AudioLoadError, load_audio
from autotune.library import (
    DEFAULT_PARAMS,
    AutoTunePresetManager,
    SongLibrary,
    normalize_preset_data,
)
from autotune.music import NOTE_NAMES, SCALES, estimate_key, key_name
from autotune.song_map import SongMap

log = logging.getLogger(__name__)

CORRECTION_MODES = {"scale": "Scale Mode", "chord": "Chord Mode", "melody": "Melody Mode"}


class AutoTuneController(QObject):
    changed = Signal()                 # parâmetros/estado alterados
    presets_changed = Signal()
    songs_changed = Signal()
    song_loaded = Signal(object)       # id da música carregada (ou None)
    analysis_changed = Signal(int)     # id da música cuja análise mudou
    key_learning = Signal(bool)
    notify = Signal(str, str)

    _analysis_done = Signal(int, object, str)
    _song_audio_ready = Signal(int, object, str)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.settings = app.settings
        self.engine = app.engine
        self.presets = AutoTunePresetManager(app.db)
        self.songs = SongLibrary(app.db)
        self.presets.seed_builtins()
        self._pool: ProcessPoolExecutor | None = None
        self._analyzing: set[int] = set()
        self.current_song_id: int | None = None
        self.song_map: SongMap | None = None
        self._analysis_done.connect(self._on_analysis_done)
        self._song_audio_ready.connect(self._on_song_audio)
        self.notify.connect(app.notify.emit)
        # Músicas interrompidas no meio da análise (app fechado) voltam para a fila.
        for s in self.songs.all():
            if s.status in ("pending", "analyzing"):
                self.analyze_song(s.id)
        if self.preset_id is None:  # primeira execução: começa com um preset suave
            light = next((p for p in self.presets.all() if p.builtin_key == "light"), None)
            if light:
                self._set("preset_id", light.id)
                self._set("params", light.data["params"])
        self._apply_all()

    # ================================================================ estado
    def _get(self, key: str, default):
        v = self.settings.get(f"autotune.{key}")
        return default if v is None else v

    def _set(self, key: str, value) -> None:
        self.settings.set(f"autotune.{key}", value)

    @property
    def enabled(self) -> bool:
        return bool(self._get("enabled", False))

    @property
    def params(self) -> dict:
        p = dict(DEFAULT_PARAMS)
        p.update(self._get("params", {}))
        return p

    @property
    def key(self) -> int:
        return int(self._get("key", 0))

    @property
    def scale(self) -> str:
        return self._get("scale", "chromatic")

    @property
    def source(self) -> str:
        return self._get("source", "realtime")

    @property
    def song_mode(self) -> str:
        return self._get("song_mode", "chord")

    @property
    def preset_id(self) -> int | None:
        return self._get("preset_id", None)

    def _apply_all(self) -> None:
        v = self.engine.voice
        v.set_autotune_params(self.params)
        v.set_autotune_config(key=self.key, scale=self.scale, source=self.source,
                              song_mode=self.song_mode, song_map=self.song_map)
        v.set_autotune_enabled(self.enabled)
        mixer = self.engine.mixer
        mixer.set_music(volume=float(self.settings.get("mixer.music_volume") or 0.8),
                        to_virtual=bool(self.settings.get("mixer.music_to_virtual")))
        order = self.settings.get("voice.effect_order")
        if order:
            v.set_order(order)

    def set_enabled(self, enabled: bool) -> None:
        self._set("enabled", bool(enabled))
        self.engine.voice.set_autotune_enabled(enabled)
        self.changed.emit()

    def toggle(self) -> None:
        self.set_enabled(not self.enabled)
        self.notify.emit("info", "Auto-Tune " + ("ativado" if self.enabled else "desativado"))

    def set_params(self, values: dict) -> None:
        p = self.params
        p.update(values)
        self._set("params", p)
        self.engine.voice.set_autotune_params(values)
        self.changed.emit()

    def set_key(self, key: int | None = None, scale: str | None = None) -> None:
        if key is not None:
            self._set("key", int(key) % 12)
        if scale is not None and scale in SCALES:
            self._set("scale", scale)
        self.engine.voice.set_autotune_config(key=self.key, scale=self.scale)
        self.changed.emit()

    def set_source(self, source: str) -> None:
        self._set("source", source)
        self.engine.voice.set_autotune_config(source=source)
        self.changed.emit()

    def set_song_mode(self, mode: str) -> None:
        if mode not in CORRECTION_MODES:
            return
        self._set("song_mode", mode)
        self.engine.voice.set_autotune_config(song_mode=mode)
        if self.current_song_id is not None:
            self.songs.update(self.current_song_id, correction_mode=mode)
        self.changed.emit()

    def set_music_volume(self, v: float) -> None:
        self.settings.set("mixer.music_volume", float(v))
        self.engine.mixer.set_music(volume=float(v))
        self.app.mixer_changed.emit()

    def set_music_to_virtual(self, on: bool) -> None:
        self.settings.set("mixer.music_to_virtual", bool(on))
        self.engine.mixer.set_music(to_virtual=bool(on))
        self.app.mixer_changed.emit()

    # ---------------------------------------------------------------- ordem dos efeitos
    def effect_order(self) -> list[str]:
        return self.engine.voice.order()

    def set_effect_order(self, order: list[str] | None) -> None:
        self.engine.voice.set_order(order)
        self.settings.set("voice.effect_order", self.engine.voice.order() if order else None)

    # ---------------------------------------------------------------- telemetria
    def telemetry(self) -> dict:
        at = self.engine.voice.autotune
        if at is None:
            return {}
        chord = ""
        t = at.song_time
        if self.source == "song" and self.song_map is not None and t is not None:
            chord = self.song_map.at(max(0.0, t)).chord_label  # acorde atual mesmo sem ninguém cantando
        return {
            "detected": at.detected_midi, "target": at.target_midi, "output": at.output_midi,
            "allowed": at.allowed_pcs, "chord": chord, "song_time": t, "active": at.enabled,
        }

    # ================================================================ detecção de tonalidade pela voz
    def detect_key_from_voice(self, seconds: float = 8.0) -> None:
        at = self.engine.voice.autotune
        if at is None or not self.engine.running:
            self.notify.emit("warning", "O áudio precisa estar ativo para detectar a tonalidade.")
            return
        at.start_key_learning()
        self.key_learning.emit(True)
        QTimer.singleShot(int(seconds * 1000), self._finish_key_learning)

    def _finish_key_learning(self) -> None:
        self.key_learning.emit(False)
        at = self.engine.voice.autotune
        hist = at.stop_key_learning() if at else None
        if hist is None or hist.sum() < 5:
            self.notify.emit("warning", "Não ouvi notas suficientes. Cante uma melodia por alguns segundos.")
            return
        tonic, mode, conf = estimate_key(hist)
        self.set_key(tonic, mode)
        self.notify.emit("success", f"Tonalidade detectada: {key_name(tonic, mode)} "
                                    f"(confiança {conf * 100:.0f}%)")

    # ================================================================ presets
    def preset_list(self):
        return self.presets.all()

    def current_preset_data(self) -> dict:
        return normalize_preset_data({"params": self.params, "key": self.key, "scale": self.scale,
                                      "song_mode": self.song_mode})

    def load_preset(self, pid: int, announce: bool = True) -> None:
        p = self.presets.get(pid)
        if not p:
            return
        d = p.data
        self._set("preset_id", pid)
        self._set("params", d["params"])
        self.engine.voice.set_autotune_params(d["params"])
        # Em Song Mode a tonalidade vem da música; o preset define o modo de correção.
        if self.source != "song" or self.current_song_id is None:
            self.set_key(d["key"], d["scale"])
        self.set_song_mode(d["song_mode"])
        self.changed.emit()
        if announce:
            self.notify.emit("info", f"Preset de Auto-Tune: {p.name}")

    def save_preset(self) -> None:
        if self.preset_id is None or not self.presets.get(self.preset_id):
            return
        self.presets.update(self.preset_id, self.current_preset_data())
        self.presets_changed.emit()
        self.notify.emit("success", "Preset de Auto-Tune salvo")

    def create_preset(self, name: str) -> int:
        pid = self.presets.create(name, self.current_preset_data())
        self._set("preset_id", pid)
        self.presets_changed.emit()
        return pid

    def rename_preset(self, pid: int, name: str) -> None:
        self.presets.rename(pid, name)
        self.presets_changed.emit()

    def delete_preset(self, pid: int) -> None:
        self.presets.delete(pid)
        if self.preset_id == pid:
            self._set("preset_id", None)
        self.presets_changed.emit()

    # ================================================================ músicas
    def song_list(self):
        return self.songs.all()

    def import_song(self, path: str) -> int | None:
        try:
            song = self.songs.import_file(path)
        except (AudioLoadError, OSError) as exc:
            self.notify.emit("error", f"Não foi possível importar: {exc}")
            return None
        self.songs_changed.emit()
        self.analyze_song(song.id)
        return song.id

    def _executor(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        return self._pool

    def analyze_song(self, sid: int) -> None:
        song = self.songs.get(sid)
        if not song or sid in self._analyzing:
            return
        self._analyzing.add(sid)
        self.songs.set_status(sid, "analyzing")
        self.songs_changed.emit()
        from autotune.song_analysis import analyze  # função de nível de módulo, sem Qt (processo filho)

        fut = self._executor().submit(analyze, song.file_path)

        def done(f):
            try:
                self._analysis_done.emit(sid, f.result(), "")
            except Exception as exc:  # noqa: BLE001
                log.exception("Falha na análise da música %s", sid)
                self._analysis_done.emit(sid, None, str(exc))
        fut.add_done_callback(done)

    def _on_analysis_done(self, sid: int, analysis, error: str) -> None:
        self._analyzing.discard(sid)
        if self.songs.get(sid) is None:
            return
        if analysis is None:
            self.songs.set_status(sid, "error", error)
            self.notify.emit("error", f"Falha ao analisar a música: {error}")
        else:
            self.songs.save_auto_analysis(sid, analysis)
            self.notify.emit("success", f"Análise concluída: {analysis['bpm']:.0f} BPM, {analysis['key']['name']}")
            if sid == self.current_song_id:
                self._rebuild_map()
        self.songs_changed.emit()
        self.analysis_changed.emit(sid)

    def is_analyzing(self, sid: int) -> bool:
        return sid in self._analyzing

    def load_song(self, sid: int) -> None:
        song = self.songs.get(sid)
        if not song:
            return
        self.current_song_id = sid
        self._set("song_id", sid)
        self.engine.song.stop()
        sr = self.engine.config.samplerate

        def work():
            try:
                self._song_audio_ready.emit(sid, load_audio(song.file_path, sr), "")
            except Exception as exc:  # noqa: BLE001
                self._song_audio_ready.emit(sid, None, str(exc))
        threading.Thread(target=work, name="song-loader", daemon=True).start()
        self._rebuild_map()
        self._set("song_mode", song.correction_mode)
        self.engine.voice.set_autotune_config(song_mode=song.correction_mode)
        if song.preset_id and self.presets.get(song.preset_id):
            self.load_preset(song.preset_id, announce=False)
            self.set_song_mode(song.correction_mode)
        if self.source != "song":
            self.set_source("song")
        self.song_loaded.emit(sid)
        self.changed.emit()

    def _on_song_audio(self, sid: int, data, error: str) -> None:
        if sid != self.current_song_id:
            return
        if data is None:
            self.notify.emit("error", f"Não foi possível carregar a música: {error}")
            return
        self.engine.song.load(sid, data)
        self.song_loaded.emit(sid)

    def reload_song_audio_if_needed(self) -> None:
        """Após reiniciar o motor (ex.: troca de sample rate), recarrega a música atual."""
        if self.current_song_id is not None and self.engine.song.song_id != self.current_song_id:
            self.load_song(self.current_song_id)

    def _rebuild_map(self) -> None:
        song = self.songs.get(self.current_song_id)
        self.song_map = SongMap(song.analysis) if song and song.analysis else None
        self.engine.voice.set_autotune_config(song_map=self.song_map)

    def current_song(self):
        return self.songs.get(self.current_song_id)

    def update_analysis(self, sid: int, analysis: dict) -> None:
        """Salva edições do usuário (tonalidade, acordes, melodia) e aplica imediatamente."""
        self.songs.save_analysis(sid, analysis)
        if sid == self.current_song_id:
            self._rebuild_map()
        self.analysis_changed.emit(sid)

    def restore_analysis(self, sid: int) -> None:
        if self.songs.restore_auto(sid) is not None:
            if sid == self.current_song_id:
                self._rebuild_map()
            self.analysis_changed.emit(sid)
            self.notify.emit("info", "Análise automática restaurada")

    def set_song_key(self, sid: int, tonic: int, scale: str) -> None:
        """Define manualmente a tonalidade da música inteira (substitui as mudanças detectadas)."""
        song = self.songs.get(sid)
        if not song or not song.analysis:
            return
        a = copy.deepcopy(song.analysis)
        name = key_name(tonic, scale)
        a["key"] = {"tonic": tonic, "scale": scale, "name": name, "confidence": 1.0, "manual": True}
        a["key_segments"] = [{"start": 0.0, "end": a["duration"], "tonic": tonic, "scale": scale, "name": name}]
        self.update_analysis(sid, a)

    def import_melody_midi(self, sid: int, path: str) -> None:
        from autotune.midi_import import MidiError, melody_line, read_notes
        song = self.songs.get(sid)
        if not song or not song.analysis:
            return
        try:
            notes = melody_line(read_notes(path))
        except (MidiError, OSError, IndexError) as exc:
            self.notify.emit("error", f"MIDI inválido: {exc}")
            return
        a = copy.deepcopy(song.analysis)
        a["melody"] = notes
        a["melody_source"] = "midi"
        self.update_analysis(sid, a)
        self.notify.emit("success", f"{len(notes)} notas de referência importadas do MIDI")

    def link_preset(self, sid: int, preset_id: int | None) -> None:
        self.songs.update(sid, preset_id=preset_id)
        self.songs_changed.emit()

    def rename_song(self, sid: int, name: str) -> None:
        self.songs.update(sid, name=name)
        self.songs_changed.emit()

    def delete_song(self, sid: int) -> None:
        if sid == self.current_song_id:
            self.engine.song.unload()
            self.current_song_id = None
            self.song_map = None
            self.engine.voice.set_autotune_config(song_map=None)
            self.song_loaded.emit(None)
        self.songs.delete(sid)
        self.songs_changed.emit()

    # ---------------------------------------------------------------- transporte
    def play(self) -> None:
        if not self.engine.song.loaded:
            self.notify.emit("warning", "Carregue uma música primeiro.")
            return
        self.engine.song.play()

    def pause(self) -> None:
        self.engine.song.pause()

    def stop(self) -> None:
        self.engine.song.stop()

    def seek(self, seconds: float) -> None:
        self.engine.song.seek(seconds)

    def transport(self) -> tuple[float, float, bool]:
        s = self.engine.song
        return s.position_s, s.duration, s.playing

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)


def key_options() -> list[tuple[str, int]]:
    return [(n, i) for i, n in enumerate(NOTE_NAMES)]
