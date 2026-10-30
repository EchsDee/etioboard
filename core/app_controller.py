"""Controlador central: conecta banco, configurações, motor de áudio, biblioteca, presets e atalhos.

As páginas da interface conversam apenas com este objeto (sinais Qt), nunca
diretamente com o motor de áudio.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from audio.audio_loader import AudioLoadError
from audio.engine import AudioEngine, EngineConfig, EngineStatus
from audio.device_manager import DeviceManager
from database.db import Database
from effects.chain import normalize_state
from hotkeys.global_hotkeys import GlobalHotkeyManager
from hotkeys.keymap import normalize_hotkey
from presets.preset_manager import Preset, PresetManager
from settings.settings_manager import SettingsManager
from soundboard.library import Snippet, SnippetLibrary
from utils import autostart
from utils.paths import db_path

log = logging.getLogger(__name__)

GLOBAL_ACTIONS: dict[str, str] = {
    "toggle_mute": "Mutar / desmutar microfone",
    "toggle_voice": "Ativar / desativar modificador de voz",
    "next_preset": "Próximo preset de voz",
    "prev_preset": "Preset de voz anterior",
    "stop_all": "Interromper todos os sons",
    "toggle_playback": "Ativar / desativar playback (ouvir minha voz)",
    "toggle_autotune": "Ativar / desativar Auto-Tune",
    "song_play_pause": "Música do Song Mode: tocar / pausar",
}

TEST_PLAYBACK_ID = -1  # id reservado no soundboard para a gravação de teste

VOLUME_KEYS = ("mixer.mic_volume", "mixer.voice_volume", "mixer.soundboard_volume",
               "mixer.master_volume", "mixer.monitor_volume")


class AppController(QObject):
    engine_status = Signal(object)
    library_changed = Signal()
    presets_changed = Signal()
    active_preset_changed = Signal(object)
    voice_state_changed = Signal()       # estado dos efeitos substituído (ex.: preset carregado)
    voice_modified_changed = Signal(bool)
    voice_enabled_changed = Signal(bool)
    mute_changed = Signal(bool)
    mixer_changed = Signal()
    hotkeys_changed = Signal()
    notify = Signal(str, str)            # nível (info|success|warning|error), mensagem
    show_window_requested = Signal()
    cable_install_progress = Signal(str, float)
    cable_install_finished = Signal(bool, str)
    playback_changed = Signal(bool)
    test_state_changed = Signal(str)      # recording | playing | idle
    _test_recorded = Signal(object)

    _hotkey_fired = Signal(str)
    _status_bg = Signal(object)
    _play_failed = Signal(str)

    def __init__(self, db_file: Path | None = None):
        super().__init__()
        self.db = Database(db_file or db_path())
        self.settings = SettingsManager(self.db)
        self.presets = PresetManager(self.db)
        self.library = SnippetLibrary(self.db)
        if self.db.is_new:
            self.library.seed_defaults()
            self.presets.seed_builtins()
            self.db.mark_seeded()

        self.devices = DeviceManager()
        self.engine = AudioEngine(self.devices)
        from core.autotune_controller import AutoTuneController

        self.autotune = AutoTuneController(self)
        self.hotkeys = GlobalHotkeyManager(self._hotkey_fired.emit)

        self._hotkey_fired.connect(self._on_hotkey)
        self._status_bg.connect(self._on_status)
        self._play_failed.connect(lambda msg: self.notify.emit("error", msg))
        self._test_recorded.connect(self._play_test_recording)
        self._test_state = "idle"
        self.engine.add_status_listener(self._status_bg.emit)

        self._saved_state: dict = {}
        self._modified = False
        self._apply_initial_state()

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(2000)
        self._flush_timer.timeout.connect(self.settings.flush)
        self._flush_timer.start()

    # ================================================================ ciclo de vida
    def _apply_initial_state(self) -> None:
        s = self.settings
        eng = self.engine
        eng.voice.set_mic_gain(s.get("mixer.mic_volume"))
        eng.voice.set_muted(s.get("mic.muted"))
        eng.voice.set_enabled(s.get("voice.enabled"))
        eng.mixer.set_volumes(
            voice=s.get("mixer.voice_volume"), soundboard=s.get("mixer.soundboard_volume"),
            master=s.get("mixer.master_volume"), monitor=s.get("mixer.monitor_volume"),
        )
        eng.mixer.set_monitor_sources(s.get("mixer.monitor_voice"), s.get("mixer.monitor_soundboard"))

        preset = self.presets.get(s.get("voice.active_preset_id")) or self.presets.default()
        if preset:
            self._activate(preset, announce=False)

    def start(self) -> None:
        if self.settings.get("system.start_with_windows"):
            autostart.set_autostart(True)  # atualiza o caminho (app movido/renomeado)
        self.engine.start(self.engine_config())
        self.hotkeys.start()
        self.register_all_hotkeys()
        self.preload_snippets()

    def shutdown(self) -> None:
        log.info("Encerrando...")
        self._flush_timer.stop()
        try:
            self.hotkeys.stop()
            self.autotune.shutdown()
        finally:
            self.engine.shutdown()
            self.settings.flush()
            self.db.close()

    # ================================================================ motor de áudio
    def engine_config(self) -> EngineConfig:
        s = self.settings
        return EngineConfig(
            hostapi=s.get("audio.hostapi"),
            input_device=s.get("audio.input_device"),
            input_hostapi=s.get("audio.input_hostapi"),
            virtual_device=s.get("audio.virtual_device"),
            virtual_enabled=bool(s.get("audio.virtual_enabled", True)),
            monitor_device=s.get("audio.monitor_device"),
            monitor_enabled=bool(s.get("audio.monitor_enabled", True)),
            samplerate=int(s.get("audio.samplerate", 48000)),
            blocksize=int(s.get("audio.blocksize", 256)),
            latency_mode=s.get("audio.latency_mode", "balanced"),
        )

    def restart_audio(self) -> None:
        self.settings.flush()
        self.engine.start(self.engine_config())

    def refresh_devices(self, done=None) -> None:
        self.engine.refresh_devices(done)

    @property
    def status(self) -> EngineStatus:
        return self.engine.status

    def _on_status(self, status: EngineStatus) -> None:
        if status.state in ("running", "degraded"):
            self.autotune.reload_song_audio_if_needed()
        self.engine_status.emit(status)

    # ================================================================ voz
    @property
    def voice_enabled(self) -> bool:
        return bool(self.settings.get("voice.enabled"))

    def set_voice_enabled(self, enabled: bool) -> None:
        self.engine.voice.set_enabled(enabled)
        self.settings.set("voice.enabled", bool(enabled))
        self.voice_enabled_changed.emit(bool(enabled))

    def toggle_voice(self) -> None:
        self.set_voice_enabled(not self.voice_enabled)
        self.notify.emit("info", "Modificador de voz " + ("ativado" if self.voice_enabled else "desativado"))

    @property
    def muted(self) -> bool:
        return bool(self.settings.get("mic.muted"))

    def set_muted(self, muted: bool) -> None:
        self.engine.voice.set_muted(muted)
        self.settings.set("mic.muted", bool(muted))
        self.mute_changed.emit(bool(muted))

    def toggle_mute(self) -> None:
        self.set_muted(not self.muted)
        self.notify.emit("info", "Microfone " + ("mutado" if self.muted else "ativo"))

    def voice_state(self) -> dict:
        return self.engine.voice.state()

    def set_effect_enabled(self, effect_id: str, enabled: bool) -> None:
        self.engine.voice.set_effect_enabled(effect_id, enabled)
        self._update_modified()

    def set_effect_params(self, effect_id: str, params: dict) -> None:
        self.engine.voice.set_effect_params(effect_id, params)
        self._update_modified()

    def _update_modified(self) -> None:
        modified = normalize_state(self.engine.voice.state()) != self._saved_state
        if modified != self._modified:
            self._modified = modified
            self.voice_modified_changed.emit(modified)

    @property
    def voice_modified(self) -> bool:
        return self._modified

    # ================================================================ presets
    @property
    def active_preset_id(self) -> int | None:
        return self.settings.get("voice.active_preset_id")

    def preset_list(self) -> list[Preset]:
        return self.presets.all()

    def _activate(self, preset: Preset, announce: bool = True) -> None:
        self.engine.voice.apply_state(preset.state)
        self._saved_state = normalize_state(preset.state)
        self.settings.set("voice.active_preset_id", preset.id)
        self._modified = False
        self.voice_modified_changed.emit(False)
        self.voice_state_changed.emit()
        self.active_preset_changed.emit(preset.id)
        if announce:
            self.notify.emit("info", f"Preset: {preset.name}")

    def load_preset(self, preset_id: int, announce: bool = False) -> None:
        preset = self.presets.get(preset_id)
        if preset:
            self._activate(preset, announce)

    def cycle_preset(self, step: int) -> None:
        presets = self.presets.all()
        if not presets:
            return
        ids = [p.id for p in presets]
        cur = self.active_preset_id
        idx = ids.index(cur) if cur in ids else -1
        self._activate(presets[(idx + step) % len(presets)], announce=True)

    def revert_changes(self) -> None:
        preset = self.presets.get(self.active_preset_id)
        if preset:
            self._activate(preset, announce=False)

    def save_active_preset(self) -> None:
        pid = self.active_preset_id
        if pid is None or self.presets.get(pid) is None:
            return
        state = self.engine.voice.state()
        self.presets.update_state(pid, state)
        self._saved_state = normalize_state(state)
        self._update_modified()
        self.presets_changed.emit()
        self.notify.emit("success", "Preset salvo")

    def create_preset(self, name: str, from_current: bool = True) -> int:
        from effects.chain import default_state

        state = self.engine.voice.state() if from_current else default_state()
        pid = self.presets.create(self.presets.unique_name(name), state)
        self.presets_changed.emit()
        self.load_preset(pid)
        return pid

    def rename_preset(self, preset_id: int, name: str) -> None:
        self.presets.rename(preset_id, name)
        self.presets_changed.emit()

    def duplicate_preset(self, preset_id: int) -> int | None:
        pid = self.presets.duplicate(preset_id)
        self.presets_changed.emit()
        return pid

    def delete_preset(self, preset_id: int) -> bool:
        if len(self.presets.all()) <= 1:
            self.notify.emit("warning", "É necessário manter pelo menos um preset.")
            return False
        was_active = preset_id == self.active_preset_id
        self.hotkeys.unregister(f"preset:{preset_id}")
        self.presets.delete(preset_id)
        self.presets_changed.emit()
        if was_active:
            p = self.presets.default()
            if p:
                self._activate(p, announce=False)
        return True

    def set_default_preset(self, preset_id: int) -> None:
        self.presets.set_default(preset_id)
        self.presets_changed.emit()

    def reorder_presets(self, ids: list[int]) -> None:
        self.presets.reorder(ids)
        self.presets_changed.emit()

    def restore_builtin_presets(self) -> None:
        n = self.presets.restore_builtins()
        self.presets_changed.emit()
        self.revert_changes()
        self.notify.emit("success", f"{n} presets originais restaurados")

    # ================================================================ mixer
    def volume(self, key: str) -> float:
        return float(self.settings.get(key))

    def set_volume(self, key: str, value: float) -> None:
        value = max(0.0, min(2.0, float(value)))
        self.settings.set(key, value)
        mixer = self.engine.mixer
        if key == "mixer.mic_volume":
            self.engine.voice.set_mic_gain(value)
        elif key == "mixer.voice_volume":
            mixer.set_volumes(voice=value)
        elif key == "mixer.soundboard_volume":
            mixer.set_volumes(soundboard=value)
        elif key == "mixer.master_volume":
            mixer.set_volumes(master=value)
        elif key == "mixer.monitor_volume":
            mixer.set_volumes(monitor=value)
        elif key == "mixer.music_volume":
            mixer.set_music(volume=value)
        self.mixer_changed.emit()

    def set_monitor_sources(self, voice: bool | None = None, soundboard: bool | None = None) -> None:
        if voice is not None:
            self.settings.set("mixer.monitor_voice", bool(voice))
        if soundboard is not None:
            self.settings.set("mixer.monitor_soundboard", bool(soundboard))
        self.engine.mixer.set_monitor_sources(voice, soundboard)
        self.mixer_changed.emit()
        if voice is not None:
            self.playback_changed.emit(bool(voice))

    # ---------------------------------------------------------------- playback
    @property
    def playback(self) -> bool:
        """Playback ao vivo: ouvir a própria voz processada no monitor (fones)."""
        return bool(self.settings.get("mixer.monitor_voice"))

    def set_playback(self, enabled: bool) -> None:
        self.set_monitor_sources(voice=bool(enabled))
        if enabled and self.engine.running and not self.engine.has_monitor:
            self.notify.emit("warning", "Nenhuma saída de monitor ativa. Ative-a em Configurações → Áudio.")

    def toggle_playback(self) -> None:
        self.set_playback(not self.playback)
        self.notify.emit("info", "Playback " + ("ativado" if self.playback else "desativado"))

    @property
    def test_state(self) -> str:
        return self._test_state

    def test_progress(self) -> float:
        if self._test_state == "recording":
            return self.engine.recorder.progress
        if self._test_state == "playing":
            info = self.engine.soundboard.playing.get(TEST_PLAYBACK_ID)
            if info is None:
                self._set_test_state("idle")
                return 0.0
            return info[0]
        return 0.0

    def _set_test_state(self, state: str) -> None:
        if state != self._test_state:
            self._test_state = state
            self.test_state_changed.emit(state)

    def record_test(self, seconds: float = 5.0) -> None:
        """Grava alguns segundos do que os outros ouvem e toca de volta só no monitor."""
        if self._test_state != "idle":
            self.cancel_test()
            return
        if not self.engine.running:
            self.notify.emit("warning", "O áudio não está ativo.")
            return
        if not self.engine.has_monitor:
            self.notify.emit("warning", "Nenhuma saída de monitor ativa para ouvir a gravação. "
                                        "Ative-a em Configurações → Áudio.")
            return
        self.engine.recorder.start(seconds, self.engine.config.samplerate, self._test_recorded.emit)
        self._set_test_state("recording")

    def _play_test_recording(self, data) -> None:
        if self._test_state != "recording":
            return
        self.engine.soundboard.play(TEST_PLAYBACK_ID, data, volume=1.0, preview=True, mode="restart")
        self._set_test_state("playing")

    def cancel_test(self) -> None:
        self.engine.recorder.cancel()
        self.engine.soundboard.stop(TEST_PLAYBACK_ID)
        self._set_test_state("idle")

    def levels(self) -> dict[str, float]:
        return self.engine.levels()

    # ================================================================ soundboard
    def preload_snippets(self) -> None:
        for s in self.library.snippets():
            if s.exists:
                self.engine.cache.request(s.file_path)

    def play_snippet(self, snippet_id: int, preview: bool = False) -> None:
        snippet = self.library.snippet(snippet_id)
        if snippet is None:
            return
        if not snippet.exists:
            self.notify.emit("error", f"Arquivo de '{snippet.name}' não encontrado. Substitua o arquivo.")
            return
        if not self.engine.running:
            self.notify.emit("warning", "O áudio não está ativo. Verifique as configurações de áudio.")
            return
        mode = "overlap" if preview else self.settings.get("soundboard.playback_mode", "restart")
        sb = self.engine.soundboard

        def _start(data, error):
            if error or data is None:
                self._play_failed.emit(f"Falha ao carregar '{snippet.name}': {error}")
                return
            sb.play(snippet.id, data, volume=snippet.volume, speed=snippet.speed,
                    loop=snippet.loop and not preview, preview=preview, mode=mode)

        cached = self.engine.cache.get_cached(snippet.file_path)
        if cached is not None:
            _start(cached, None)
        else:
            self.engine.cache.request(snippet.file_path, _start)

    def stop_snippet(self, snippet_id: int) -> None:
        self.engine.soundboard.stop(snippet_id)

    def stop_all(self) -> None:
        self.engine.soundboard.stop_all()

    def playing(self) -> dict[int, tuple[float, bool]]:
        return self.engine.soundboard.playing

    def import_files(self, paths: list[str], category_id: int | None) -> tuple[int, list[str]]:
        ok, errors = 0, []
        copy_files = bool(self.settings.get("soundboard.copy_files", True))
        for p in paths:
            try:
                snippet = self.library.import_file(p, category_id, copy=copy_files)
                self.engine.cache.request(snippet.file_path)
                ok += 1
            except (AudioLoadError, OSError) as exc:
                errors.append(f"{Path(p).name}: {exc}")
        if ok:
            self.library_changed.emit()
        return ok, errors

    def update_snippet(self, snippet_id: int, **fields) -> None:
        self.library.update_snippet(snippet_id, **fields)
        live = {k: fields[k] for k in ("volume", "speed", "loop") if k in fields}
        if live:
            self.engine.soundboard.update(snippet_id, **live)
        self.library_changed.emit()

    def replace_snippet_file(self, snippet_id: int, path: str) -> bool:
        try:
            old, new = self.library.replace_file(
                snippet_id, path, copy=bool(self.settings.get("soundboard.copy_files", True))
            )
        except (AudioLoadError, OSError) as exc:
            self.notify.emit("error", str(exc))
            return False
        self.engine.soundboard.stop(snippet_id)
        self.engine.cache.invalidate(old)
        self.engine.cache.request(new)
        self.library_changed.emit()
        self.notify.emit("success", "Arquivo substituído")
        return True

    def delete_snippet(self, snippet_id: int) -> None:
        self.engine.soundboard.stop(snippet_id)
        self.hotkeys.unregister(f"snippet:{snippet_id}")
        snippet = self.library.delete_snippet(snippet_id)
        if snippet:
            self.engine.cache.invalidate(snippet.file_path)
        self.library_changed.emit()

    def move_snippet(self, snippet_id: int, category_id: int | None) -> None:
        self.library.move_to_category(snippet_id, category_id)
        self.library_changed.emit()

    def reorder_snippets(self, ids: list[int]) -> None:
        self.library.reorder(ids)
        self.library_changed.emit()

    def create_category(self, name: str, icon: str, color: str) -> int:
        cid = self.library.create_category(name, icon, color)
        self.library_changed.emit()
        return cid

    def update_category(self, category_id: int, name: str, icon: str, color: str) -> None:
        self.library.update_category(category_id, name, icon, color)
        self.library_changed.emit()

    def delete_category(self, category_id: int, delete_snippets: bool) -> None:
        removed = self.library.delete_category(category_id, delete_snippets)
        for s in removed:
            self.engine.soundboard.stop(s.id)
            self.hotkeys.unregister(f"snippet:{s.id}")
            self.engine.cache.invalidate(s.file_path)
        self.library_changed.emit()

    def reorder_categories(self, ids: list[int]) -> None:
        self.library.reorder_categories(ids)
        self.library_changed.emit()

    # ================================================================ atalhos globais
    def action_hotkeys(self) -> dict[str, str]:
        return {r["action"]: r["hotkey"] for r in self.db.query("SELECT action, hotkey FROM hotkeys")}

    def hotkey_owner(self, hotkey: str, exclude: str | None = None) -> str | None:
        """Descrição de quem já usa o atalho (ou None)."""
        hotkey = normalize_hotkey(hotkey)
        if not hotkey:
            return None
        for action, hk in self.action_hotkeys().items():
            if normalize_hotkey(hk) == hotkey and f"action:{action}" != exclude:
                return f"ação '{GLOBAL_ACTIONS.get(action, action)}'"
        for s in self.library.snippets():
            if s.hotkey and normalize_hotkey(s.hotkey) == hotkey and f"snippet:{s.id}" != exclude:
                return f"snippet '{s.name}'"
        for p in self.presets.all():
            if p.hotkey and normalize_hotkey(p.hotkey) == hotkey and f"preset:{p.id}" != exclude:
                return f"preset '{p.name}'"
        return None

    def assign_hotkey(self, owner: str, hotkey: str | None) -> tuple[bool, str]:
        """owner: 'action:<nome>', 'snippet:<id>' ou 'preset:<id>'."""
        hotkey = normalize_hotkey(hotkey) if hotkey else None
        if hotkey:
            other = self.hotkey_owner(hotkey, exclude=owner)
            if other:
                return False, f"'{hotkey}' já está atribuído ao {other}."
        ok, err = self.hotkeys.register(owner, hotkey)
        if not ok:
            return False, err
        kind, _, ident = owner.partition(":")
        if kind == "action":
            if hotkey:
                self.db.execute("INSERT OR REPLACE INTO hotkeys(action, hotkey) VALUES(?, ?)", (ident, hotkey))
            else:
                self.db.execute("DELETE FROM hotkeys WHERE action = ?", (ident,))
        elif kind == "snippet":
            self.library.update_snippet(int(ident), hotkey=hotkey)
            self.library_changed.emit()
        elif kind == "preset":
            self.presets.set_hotkey(int(ident), hotkey)
            self.presets_changed.emit()
        self.hotkeys_changed.emit()
        return True, ""

    def register_all_hotkeys(self) -> list[str]:
        failures = []
        entries = [(f"action:{a}", hk) for a, hk in self.action_hotkeys().items()]
        entries += [(f"snippet:{s.id}", s.hotkey) for s in self.library.snippets() if s.hotkey]
        entries += [(f"preset:{p.id}", p.hotkey) for p in self.presets.all() if p.hotkey]
        for owner, hk in entries:
            ok, err = self.hotkeys.register(owner, hk)
            if not ok:
                failures.append(err)
        if failures:
            self.notify.emit("warning", "Alguns atalhos não puderam ser registrados: " + "; ".join(failures))
        return failures

    def _on_hotkey(self, owner: str) -> None:
        kind, _, ident = owner.partition(":")
        if kind == "snippet":
            self.play_snippet(int(ident))
        elif kind == "preset":
            self.load_preset(int(ident), announce=True)
        elif ident == "toggle_mute":
            self.toggle_mute()
        elif ident == "toggle_voice":
            self.toggle_voice()
        elif ident == "next_preset":
            self.cycle_preset(1)
        elif ident == "prev_preset":
            self.cycle_preset(-1)
        elif ident == "stop_all":
            self.stop_all()
        elif ident == "toggle_playback":
            self.toggle_playback()
        elif ident == "toggle_autotune":
            self.autotune.toggle()
        elif ident == "song_play_pause":
            at = self.autotune
            at.pause() if at.transport()[2] else at.play()

    # ================================================================ cabo virtual
    @property
    def virtual_cable_installed(self) -> bool:
        return self.devices.virtual_driver_installed()

    def install_virtual_cable(self) -> None:
        """Baixa e executa o instalador oficial do VB-CABLE em segundo plano."""
        if getattr(self, "_cable_thread", None) and self._cable_thread.is_alive():
            return
        from audio.virtual_cable_installer import InstallError, install_vb_cable

        def work():
            try:
                install_vb_cable(lambda text, frac: self.cable_install_progress.emit(text, frac))
            except InstallError as exc:
                self.cable_install_finished.emit(False, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("Falha na instalação do VB-CABLE")
                self.cable_install_finished.emit(False, f"Erro inesperado: {exc}")
                return
            self.cable_install_progress.emit("Procurando o novo dispositivo…", 1.0)
            self.settings.set("audio.virtual_device", None)   # volta para detecção automática
            self.settings.set("audio.virtual_enabled", True)
            done = threading.Event()
            self.engine.refresh_devices(done.set)
            done.wait(20)
            if self.devices.virtual_driver_installed():
                self.cable_install_finished.emit(
                    True, "VB-CABLE instalado! No Discord/jogo, escolha “CABLE Output” como microfone.")
            else:
                self.cable_install_finished.emit(
                    False, "O instalador terminou, mas o dispositivo ainda não apareceu. Se a instalação foi "
                           "concluída, reinicie o Windows e abra o etioboard novamente.")

        self._cable_thread = threading.Thread(target=work, name="vbcable-install", daemon=True)
        self._cable_thread.start()

    # ================================================================ sistema
    def set_autostart(self, enabled: bool) -> None:
        if autostart.set_autostart(enabled):
            self.settings.set("system.start_with_windows", bool(enabled))
        else:
            self.notify.emit("error", "Não foi possível alterar a inicialização com o Windows.")

    def snippet(self, snippet_id: int) -> Snippet | None:
        return self.library.snippet(snippet_id)
