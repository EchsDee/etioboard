"""Voice Studio — modificador de voz em tempo real e soundboard para Windows."""
from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import QLockFile, Qt
from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from utils.logging_setup import setup_logging
from utils.paths import APP_DISPLAY_NAME, APP_NAME, app_data_dir

log = logging.getLogger("voicestudio")
SERVER_NAME = f"{APP_NAME}-single-instance"


def _activate_running_instance() -> bool:
    """Se já houver uma instância aberta, pede para ela aparecer e retorna True."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimized", action="store_true", help="iniciar na bandeja do sistema")
    parser.add_argument("--restart", action="store_true", help=argparse.SUPPRESS)
    args, _ = parser.parse_known_args()

    setup_logging()
    # A thread de DSP disputa o GIL com a interface; trocas mais frequentes reduzem o tempo
    # máximo de espera do DSP (o padrão de 5 ms é quase um bloco de áudio inteiro).
    sys.setswitchinterval(0.001)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VoiceStudio.App")

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # o estilo nativo do Windows 11 ignora parte do QSS (sliders, spinboxes)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 10))

    lock = QLockFile(str(app_data_dir() / "instance.lock"))
    lock.setStaleLockTime(0)
    # Em um reinício, espera a instância anterior terminar de fechar.
    if not lock.tryLock(8000 if args.restart else 100):
        if _activate_running_instance():
            return 0
        lock.removeStaleLockFile()
        if not lock.tryLock(100):
            return 0

    # Imports pesados só depois da verificação de instância única.
    from core.app_controller import AppController
    from ui import icons, theme
    from ui.main_window import MainWindow

    try:
        ctl = AppController()
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha ao iniciar")
        QMessageBox.critical(None, APP_DISPLAY_NAME, f"Não foi possível iniciar o aplicativo:\n{exc}")
        return 1

    theme.set_theme(ctl.settings.get("ui.theme"), ctl.settings.get("ui.accent"))
    app.setStyleSheet(theme.stylesheet(theme.current()))
    app.setWindowIcon(icons.app_icon())

    window = MainWindow(ctl)
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), window.show_normal()))

    ctl.start()
    if not (args.minimized or ctl.settings.get("ui.start_minimized")):
        window.show()

    code = app.exec()
    try:
        ctl.shutdown()
    finally:
        server.close()
        lock.unlock()
    log.info("Encerrado (código %s)", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
