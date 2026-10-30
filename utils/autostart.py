"""Inicialização com o Windows (chave Run do registro do usuário)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from utils.paths import APP_NAME, is_frozen

log = logging.getLogger(__name__)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _command() -> str:
    if is_frozen():
        return f'"{sys.executable}" --minimized'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{pythonw if pythonw.exists() else exe}" "{main}" --minimized'


def set_autostart(enabled: bool) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.exception("Falha ao configurar inicialização com o Windows")
        return False


def is_autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False
