"""Caminhos do aplicativo (dados do usuário, recursos empacotados)."""
from __future__ import annotations

import os
import sys
import shutil
import sqlite3
from pathlib import Path

APP_NAME = "etioboard"
APP_DISPLAY_NAME = "etioboard"
LEGACY_APP_NAME = "VoiceStudio"  # nome antigo (dados migrados na 1ª execução)
APP_VERSION = "1.0.0"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_data_dir() -> Path:
    """Pasta de dados do usuário (%APPDATA%/etioboard). Pode ser sobrescrita por ETIOBOARD_DATA."""
    override = os.environ.get("ETIOBOARD_DATA")
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
    return app_data_dir() / "etioboard.db"


def resource_path(relative: str) -> Path:
    """Resolve um recurso empacotado (funciona no modo PyInstaller e no código-fonte)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def migrate_legacy_data() -> bool:
    """Copia os dados do nome antigo (%APPDATA%/VoiceStudio) para a pasta nova, uma única vez.

    A pasta antiga é mantida intacta como backup. Os caminhos dos sons no banco são
    reescritos para apontar para a nova pasta. Retorna True se migrou.
    """
    if os.environ.get("ETIOBOARD_DATA"):
        return False
    base = Path(os.environ.get("APPDATA") or str(Path.home()))
    old, new = base / LEGACY_APP_NAME, base / APP_NAME
    old_db = old / "voicestudio.db"
    if new.exists() or not old_db.exists():
        return False
    tmp = base / (APP_NAME + ".migrating")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    # Cópia consistente do banco (inclui o WAL) via API de backup do SQLite.
    src = sqlite3.connect(str(old_db))
    dst = sqlite3.connect(str(tmp / "etioboard.db"))
    try:
        src.backup(dst)
        dst.execute(
            "UPDATE snippets SET file_path = REPLACE(file_path, ?, ?)",
            (str(old / "sounds"), str(new / "sounds")),
        )
        dst.commit()
    finally:
        src.close()
        dst.close()
    if (old / "sounds").is_dir():
        shutil.copytree(old / "sounds", tmp / "sounds")
    tmp.rename(new)
    return True
