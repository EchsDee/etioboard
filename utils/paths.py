"""Caminhos do aplicativo (dados do usuário, recursos empacotados)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "VoiceStudio"
APP_DISPLAY_NAME = "Voice Studio"
APP_VERSION = "1.0.0"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_data_dir() -> Path:
    """Pasta de dados do usuário (%APPDATA%/VoiceStudio). Pode ser sobrescrita por VOICESTUDIO_DATA."""
    override = os.environ.get("VOICESTUDIO_DATA")
    if override:
        path = Path(override)
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def sounds_dir() -> Path:
    path = app_data_dir() / "sounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return app_data_dir() / "voicestudio.db"


def resource_path(relative: str) -> Path:
    """Resolve um recurso empacotado (funciona no modo PyInstaller e no código-fonte)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative
