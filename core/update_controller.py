"""Verificação, download e instalação de atualizações em segundo plano."""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, Signal

from utils import updater
from utils.paths import APP_VERSION

log = logging.getLogger(__name__)

AUTO_CHECK_INTERVAL_S = 6 * 3600


class UpdateController(QObject):
    # estado: idle | checking | available | uptodate | downloading | ready | error
    state_changed = Signal(str, str)        # estado, mensagem
    progress = Signal(int, int)             # bytes baixados, total
    install_requested = Signal()            # pronto: a janela deve fechar o app

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.state = "idle"
        self.message = ""
        self.info: updater.UpdateInfo | None = None
        self._build = None
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self.state_changed.connect(self._remember)

    @property
    def current_version(self) -> str:
        return APP_VERSION

    def _remember(self, state: str, message: str) -> None:
        self.state, self.message = state, message

    def _busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self, target) -> None:
        self._thread = threading.Thread(target=target, name="updater", daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- verificação
    def check_on_startup(self) -> None:
        if not self.settings.get("updates.check_on_start", True):
            return
        last = float(self.settings.get("updates.last_check", 0) or 0)
        if time.time() - last < AUTO_CHECK_INTERVAL_S:
            return
        self.check(silent=True)

    def check(self, silent: bool = False) -> None:
        if self._busy():
            return
        self.state_changed.emit("checking", "Procurando atualizações…")

        def work():
            try:
                info = updater.check()
            except updater.UpdateError as exc:
                log.info("Verificação de atualização falhou: %s", exc)
                self.state_changed.emit("idle" if silent else "error", "" if silent else str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("Erro ao procurar atualizações")
                self.state_changed.emit("idle" if silent else "error", "" if silent else f"Erro inesperado: {exc}")
                return
            self.settings.set("updates.last_check", time.time())
            self.info = info
            if info is None:
                self.state_changed.emit("uptodate", f"Você já está na versão mais recente ({APP_VERSION}).")
            elif silent and self.settings.get("updates.skipped_version") == info.version:
                self.state_changed.emit("idle", "")
            else:
                self.state_changed.emit("available", f"Nova versão disponível: {info.version}")

        self._run(work)

    def skip_version(self) -> None:
        if self.info:
            self.settings.set("updates.skipped_version", self.info.version)

    # ---------------------------------------------------------------- instalação
    def can_install(self) -> tuple[bool, str]:
        return updater.can_self_update()

    def download_and_install(self) -> None:
        info = self.info
        if info is None or self._busy():
            return
        ok, reason = updater.can_self_update()
        if not ok:
            self.state_changed.emit("error", reason)
            return
        self._cancel.clear()
        self.state_changed.emit("downloading", f"Baixando a versão {info.version}…")

        def work():
            try:
                stage = updater.staging_dir()
                zip_path = updater.download(info, stage, lambda d, t: self.progress.emit(d, t), self._cancel)
                self.state_changed.emit("downloading", "Preparando a instalação…")
                self._build = updater.extract(zip_path, stage / "extracted")
                zip_path.unlink(missing_ok=True)
            except updater.UpdateError as exc:
                self.state_changed.emit("error", str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("Erro ao baixar a atualização")
                self.state_changed.emit("error", f"Erro inesperado: {exc}")
                return
            self.state_changed.emit("ready", f"Versão {info.version} pronta. O etioboard vai reiniciar.")
            self.install_requested.emit()

        self._run(work)

    def cancel(self) -> None:
        self._cancel.set()

    def apply_and_quit(self) -> bool:
        """Chamado pela janela: inicia o instalador; o app deve encerrar em seguida."""
        if self._build is None:
            return False
        try:
            updater.launch_installer(self._build)
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao iniciar o instalador")
            self.state_changed.emit("error", f"Não foi possível iniciar a instalação: {exc}")
            return False
        return True
