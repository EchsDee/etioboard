"""Configuração de logging com arquivo rotativo."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from utils.paths import logs_dir


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        logs_dir() / "etioboard.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if sys.stderr is not None:  # em executáveis sem console, stderr é None
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(fmt)
        root.addHandler(console)
