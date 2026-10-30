"""Preferências do usuário: valores JSON persistidos na tabela `settings` do SQLite.

As escritas são mantidas em memória e gravadas em lote (flush), para que sliders
arrastados não gerem centenas de escritas no disco.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from database.db import Database

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    # Áudio
    "audio.hostapi": None,            # None = escolher automaticamente (WASAPI se disponível)
    "audio.input_device": None,       # None = padrão do sistema
    "audio.input_hostapi": None,      # None = mesma API das saídas
    "audio.virtual_device": None,     # None = detectar automaticamente (VB-CABLE etc.)
    "audio.virtual_enabled": True,
    "audio.monitor_device": None,     # None = saída padrão do sistema
    "audio.monitor_enabled": True,
    "audio.samplerate": 48000,
    "audio.blocksize": 256,
    "audio.latency_mode": "balanced",  # low | balanced | safe
    # Mixer
    "mixer.mic_volume": 1.0,
    "mixer.voice_volume": 1.0,
    "mixer.soundboard_volume": 0.8,
    "mixer.master_volume": 1.0,
    "mixer.monitor_volume": 0.7,
    "mixer.monitor_voice": False,
    "mixer.monitor_soundboard": True,
    # Voz
    "voice.enabled": True,
    "voice.active_preset_id": None,
    "mic.muted": False,
    # Soundboard
    "soundboard.playback_mode": "restart",  # restart | toggle | overlap
    "soundboard.copy_files": True,
    "soundboard.button_size": 120,
    # Interface / sistema
    "ui.theme": "dark",
    "ui.accent": "#8B5CF6",
    "ui.minimize_to_tray": True,
    "ui.close_to_tray": True,
    "ui.start_minimized": False,
    "ui.window_geometry": None,
    "ui.last_page": 0,
    "ui.last_category": "all",
    "system.start_with_windows": False,
}


class SettingsManager:
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.RLock()
        self._values: dict[str, Any] = dict(DEFAULTS)
        self._dirty: set[str] = set()
        self._listeners: list[Callable[[str, Any], None]] = []
        self._load()

    def _load(self) -> None:
        for row in self.db.query("SELECT key, value FROM settings"):
            if row["key"].startswith("__"):
                continue
            try:
                self._values[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                log.warning("Configuração inválida ignorada: %s", row["key"])

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._values:
                return self._values[key]
        return default

    def set(self, key: str, value: Any, notify: bool = True) -> None:
        with self._lock:
            if self._values.get(key) == value and key in self._values:
                return
            self._values[key] = value
            self._dirty.add(key)
        if notify:
            for cb in list(self._listeners):
                try:
                    cb(key, value)
                except Exception:  # noqa: BLE001 - um listener com erro não pode quebrar os demais
                    log.exception("Erro em listener de configuração")

    def add_listener(self, cb: Callable[[str, Any], None]) -> None:
        self._listeners.append(cb)

    def flush(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            rows = [(k, json.dumps(self._values[k])) for k in self._dirty]
            self._dirty.clear()
        self.db.executemany("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", rows)

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    # ------------------------------------------------------------ export/import JSON
    def export_json(self, path: Path | str) -> None:
        data = {k: v for k, v in self.all().items() if k != "ui.window_geometry"}
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def import_json(self, path: Path | str) -> int:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        count = 0
        for key, value in data.items():
            if key in DEFAULTS:
                self.set(key, value)
                count += 1
        self.flush()
        return count
