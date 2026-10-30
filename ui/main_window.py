"""Janela principal: menu lateral, barra superior, páginas, bandeja do sistema e notificações."""
from __future__ import annotations

import sys

from PySide6.QtCore import QByteArray, QProcess, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core.app_controller import AppController
from ui import icons, theme
from ui.pages.dashboard_page import DashboardPage
from ui.pages.mixer_page import MixerPage
from ui.pages.presets_page import PresetsPage
from ui.pages.settings_page import SettingsPage
from ui.pages.voice_page import VoicePage
from ui.widgets.common import button, label
from ui.widgets.hotkey_edit import HotkeyEdit
from ui.widgets.level_meter import ActivityDot, LevelMeter, lin_to_frac
from ui.widgets.toast import Toast
from utils.paths import APP_DISPLAY_NAME, APP_VERSION

NAV = [
    ("Dashboard", "grid"),
    ("Voice Changer", "wave"),
    ("Presets", "layers"),
    ("Mixer", "sliders"),
    ("Configurações", "settings"),
]

STATE_COLORS = {"running": "#22C55E", "degraded": "#F59E0B", "starting": "#3B82F6",
                "error": "#EF4444", "stopped": "#64748B"}
STATE_TEXT = {"running": "Áudio OK", "degraded": "Áudio com avisos", "starting": "Iniciando…",
              "error": "Erro no áudio", "stopped": "Áudio parado"}


class MainWindow(QMainWindow):
    def __init__(self, ctl: AppController):
        super().__init__()
        self.ctl = ctl
        self._quitting = False
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(980, 640)
        self.resize(1360, 840)
        geo = ctl.settings.get("ui.window_geometry")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))

        self._build_tray()
        self._build_ui()
        self.toast = Toast(self)
        ctl.notify.connect(self._notify)

        # Suspende atalhos globais enquanto o usuário captura uma nova combinação.
        HotkeyEdit.capture_hook = self._capture_hook

        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        QShortcut(QKeySequence("Ctrl+M"), self, activated=ctl.toggle_mute)
        QShortcut(QKeySequence("Esc"), self, activated=ctl.stop_all)
        for i in range(len(NAV)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.go(i))

    # ================================================================ construção
    def _build_ui(self) -> None:
        ctl = self.ctl
        p = theme.current()
        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---------- sidebar
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 18, 14, 16)
        sv.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(34, 34))
        brand.addWidget(logo)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        bt.addWidget(label(APP_DISPLAY_NAME, "Brand"))
        bt.addWidget(label("Voice changer & soundboard", "BrandSub"))
        brand.addLayout(bt, 1)
        sv.addLayout(brand)
        sv.addSpacing(22)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for i, (text, icon_name) in enumerate(NAV):
            b = QPushButton("  " + text)
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(icons.icon(icon_name, p.text_dim, 18, active_color=p.accent))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(f"{text} (Ctrl+{i + 1})")
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            self.nav_group.addButton(b, i)
            self.nav_buttons.append(b)
            sv.addWidget(b)
        sv.addStretch(1)

        # mini-status no rodapé da sidebar
        foot = QFrame()
        foot.setObjectName("Card")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(6)
        row = QHBoxLayout()
        self.side_dot = QLabel("●")
        row.addWidget(self.side_dot)
        self.side_status = label("", "H3")
        row.addWidget(self.side_status, 1)
        fl.addLayout(row)
        self.side_detail = label("", "Faint", wrap=True)
        fl.addWidget(self.side_detail)
        sv.addWidget(foot)
        sv.addWidget(label(f"v{APP_VERSION}", "Faint"))
        h.addWidget(side)

        # ---------- área principal
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(self._build_topbar())

        self.pages = QStackedWidget()
        self.dashboard = DashboardPage(ctl)
        self.voice = VoicePage(ctl)
        self.presets_page = PresetsPage(ctl)
        self.mixer = MixerPage(ctl)
        self.settings_page = SettingsPage(ctl)
        for page in (self.dashboard, self.voice, self.presets_page, self.mixer, self.settings_page):
            self.pages.addWidget(page)
        self.presets_page.edit_requested.connect(lambda: self.go(1))
        self.settings_page.theme_changed.connect(self.apply_theme)
        main.addWidget(self.pages, 1)
        h.addLayout(main, 1)

        self.setCentralWidget(root)
        ctl.engine_status.connect(self._on_status)
        ctl.mute_changed.connect(self._sync_quick)
        ctl.voice_enabled_changed.connect(lambda _on: self._sync_quick())
        ctl.playback_changed.connect(lambda _on: self._sync_quick())
        self._on_status(ctl.status)
        self._sync_quick()
        self.go(int(ctl.settings.get("ui.last_page", 0) or 0))

    def _build_topbar(self) -> QWidget:
        p = theme.current()
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(58)
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 8, 20, 8)
        h.setSpacing(10)

        # chips de dispositivos
        self.chip_in = QFrame()
        self.chip_in.setObjectName("Chip")
        ci = QHBoxLayout(self.chip_in)
        ci.setContentsMargins(10, 4, 12, 4)
        ci.setSpacing(8)
        self.mic_dot = ActivityDot(10)
        ci.addWidget(self.mic_dot)
        icn = QLabel()
        icn.setPixmap(icons.pixmap("mic", p.text_dim, 14))
        ci.addWidget(icn)
        self.chip_in_text = QLabel("—")
        self.chip_in_text.setStyleSheet(f"color: {p.text_dim};")
        self.chip_in_text.setMaximumWidth(220)
        ci.addWidget(self.chip_in_text)
        self.top_in_meter = LevelMeter(thickness=5)
        self.top_in_meter.setFixedWidth(70)
        ci.addWidget(self.top_in_meter)
        h.addWidget(self.chip_in)

        self.chip_out = QFrame()
        self.chip_out.setObjectName("Chip")
        self.chip_out.installEventFilter(self)  # clique: abre Configurações quando falta o cabo virtual
        co = QHBoxLayout(self.chip_out)
        co.setContentsMargins(10, 4, 12, 4)
        co.setSpacing(8)
        ocn = QLabel()
        ocn.setPixmap(icons.pixmap("cable", p.text_dim, 14))
        co.addWidget(ocn)
        self.chip_out_text = QLabel("—")
        self.chip_out_text.setStyleSheet(f"color: {p.text_dim};")
        self.chip_out_text.setMaximumWidth(240)
        co.addWidget(self.chip_out_text)
        self.top_out_meter = LevelMeter(thickness=5)
        self.top_out_meter.setFixedWidth(70)
        co.addWidget(self.top_out_meter)
        h.addWidget(self.chip_out)
        h.addStretch(1)

        self.status_chip = QLabel()
        h.addWidget(self.status_chip)

        self.q_playback = button("Playback", "headphones")
        self.q_playback.setObjectName("BigToggle")
        self.q_playback.setCheckable(True)
        self.q_playback.setToolTip("Ouvir sua voz processada ao vivo nos fones (monitor).\n"
                                   "Só você ouve; não afeta o que vai para o Discord/jogo.")
        self.q_playback.clicked.connect(self.ctl.set_playback)
        h.addWidget(self.q_playback)

        self.q_voice = button("Voz", "wave")
        self.q_voice.setObjectName("BigToggle")
        self.q_voice.setCheckable(True)
        self.q_voice.setToolTip("Ativar/desativar o modificador de voz")
        self.q_voice.clicked.connect(self.ctl.set_voice_enabled)
        h.addWidget(self.q_voice)
        self.q_mute = button("", "mic")
        self.q_mute.setObjectName("MuteButton")
        self.q_mute.setCheckable(True)
        self.q_mute.setToolTip("Mutar/desmutar microfone (Ctrl+M)")
        self.q_mute.clicked.connect(self.ctl.set_muted)
        h.addWidget(self.q_mute)
        stop = button("", "stop-all", danger=True, tooltip="Parar todos os sons (Esc)")
        stop.clicked.connect(self.ctl.stop_all)
        h.addWidget(stop)
        return bar

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.tray.setToolTip(APP_DISPLAY_NAME)
        menu = QMenu()
        menu.addAction(f"Abrir {APP_DISPLAY_NAME}", self.show_normal)
        menu.addSeparator()
        self.tray_mute = QAction("Microfone mutado", menu, checkable=True)
        self.tray_mute.triggered.connect(self.ctl.set_muted)
        menu.addAction(self.tray_mute)
        self.tray_voice = QAction("Modificador de voz", menu, checkable=True)
        self.tray_voice.triggered.connect(self.ctl.set_voice_enabled)
        menu.addAction(self.tray_voice)
        self.tray_playback = QAction("Playback (ouvir minha voz)", menu, checkable=True)
        self.tray_playback.triggered.connect(self.ctl.set_playback)
        menu.addAction(self.tray_playback)
        menu.addAction("Parar todos os sons", self.ctl.stop_all)
        menu.addSeparator()
        menu.addAction("Sair", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self._tray_menu = menu

    # ================================================================ comportamento
    def go(self, index: int) -> None:
        index = max(0, min(index, self.pages.count() - 1))
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self.ctl.settings.set("ui.last_page", index)

    def _on_tick(self) -> None:
        if not self.isVisible() or self.isMinimized():
            return
        levels = self.ctl.levels()
        self.top_in_meter.set_level(levels.get("input", 0.0))
        self.top_out_meter.set_level(levels.get("output", 0.0))
        self.mic_dot.set_value(lin_to_frac(levels.get("input", 0.0)) ** 2,
                               "#EF4444" if self.ctl.muted else "#22C55E")
        page = self.pages.currentWidget()
        if hasattr(page, "tick"):
            page.tick(levels)

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "chip_out", None) and event.type() == event.Type.MouseButtonPress:
            if not self.ctl.status.virtual_name:
                self.go(4)
            return True
        return super().eventFilter(obj, event)

    def _maybe_offer_cable(self, st) -> None:
        """Na primeira execução sem cabo virtual, oferece a instalação (uma única vez)."""
        if (st.state not in ("running", "degraded") or not st.virtual_missing or not self.isVisible()
                or self.ctl.settings.get("ui.cable_prompt_shown") or self.ctl.virtual_cable_installed):
            return
        self.ctl.settings.set("ui.cable_prompt_shown", True)
        box = QMessageBox(self)
        box.setWindowTitle("Usar o etioboard como microfone")
        box.setText("Para o Discord e os jogos ouvirem sua voz modificada e o soundboard, o Windows precisa de "
                    "um dispositivo de áudio virtual.")
        box.setInformativeText("O etioboard pode baixar e abrir o instalador oficial do VB-CABLE (gratuito). "
                               "Você só precisa confirmar a permissão do Windows e clicar em “Install Driver”.")
        install = box.addButton("Instalar agora", QMessageBox.AcceptRole)
        box.addButton("Depois", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is install:
            self.go(4)
            self.settings_page._install_cable()

    def _on_status(self, st) -> None:
        QTimer.singleShot(800, lambda: self._maybe_offer_cable(self.ctl.status))
        color = STATE_COLORS.get(st.state, "#64748B")
        text = STATE_TEXT.get(st.state, st.state)
        p = theme.current()
        self.status_chip.setText(f"<span style='color:{color}'>●</span>&nbsp; {text}")
        self.status_chip.setToolTip(st.message + ("\n" + "\n".join(st.warnings) if st.warnings else ""))
        self.status_chip.setStyleSheet(f"color: {p.text_dim}; padding: 0 6px;")
        self.side_dot.setStyleSheet(f"color: {color}; font-size: 12pt;")
        self.side_status.setText(text)
        if st.state in ("running", "degraded"):
            self.side_detail.setText(f"~{st.latency_ms:.0f} ms • {st.samplerate // 1000} kHz")
        elif st.state == "error":
            self.side_detail.setText("Veja Configurações → Áudio")
        else:
            self.side_detail.setText("")
        self.chip_in_text.setText(self._short(st.input_name or "Sem microfone"))
        self.chip_in.setToolTip(f"Entrada: {st.input_name or 'nenhuma'}")
        if st.virtual_name:
            self.chip_out_text.setText(self._short(st.virtual_name))
            self.chip_out_text.setStyleSheet(f"color: {p.text_dim};")
        else:
            self.chip_out_text.setText("Sem saída virtual · instalar")
            self.chip_out_text.setStyleSheet("color: #F59E0B;")
            self.chip_out.setCursor(Qt.PointingHandCursor)
        self.chip_out.setToolTip(f"Saída virtual: {st.virtual_name or 'não encontrada (instale o VB-CABLE)'}\n"
                                 f"Monitor: {st.monitor_name or 'desativado'}")
        if st.state == "error" and not self.isVisible():
            self.tray.showMessage(APP_DISPLAY_NAME, st.message, QSystemTrayIcon.Warning, 4000)

    @staticmethod
    def _short(name: str, n: int = 30) -> str:
        return name if len(name) <= n else name[: n - 1] + "…"

    def _sync_quick(self, *_):
        p = theme.current()
        muted, voice = self.ctl.muted, self.ctl.voice_enabled
        self.q_mute.setChecked(muted)
        self.q_mute.setIcon(icons.icon("mic-off" if muted else "mic", "#F87171" if muted else p.text, 18))
        self.q_voice.setChecked(voice)
        self.q_voice.setText("Voz ON" if voice else "Voz OFF")
        self.q_playback.setChecked(self.ctl.playback)
        self.tray_playback.setChecked(self.ctl.playback)
        self.tray_mute.setChecked(muted)
        self.tray_voice.setChecked(voice)

    def _notify(self, level: str, message: str) -> None:
        if self.isVisible() and not self.isMinimized():
            self.toast.show_message(level, message)
        elif level in ("warning", "error"):
            self.tray.showMessage(APP_DISPLAY_NAME, message,
                                  QSystemTrayIcon.Warning if level == "warning" else QSystemTrayIcon.Critical, 3000)

    def _capture_hook(self, capturing: bool) -> None:
        if capturing:
            self.ctl.hotkeys.unregister_all()
        else:
            self.ctl.register_all_hotkeys()

    def apply_theme(self) -> None:
        """Aplica a folha de estilos na hora; ícones pré-renderizados são atualizados ao reiniciar."""
        s = self.ctl.settings
        theme.set_theme(s.get("ui.theme"), s.get("ui.accent"))
        QApplication.instance().setStyleSheet(theme.stylesheet(theme.current()))
        box = QMessageBox(self)
        box.setWindowTitle("Tema alterado")
        box.setText(f"O tema foi aplicado. Reinicie o {APP_DISPLAY_NAME} para atualizar também os ícones.")
        restart = box.addButton("Reiniciar agora", QMessageBox.AcceptRole)
        box.addButton("Depois", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is restart:
            self.restart_app()

    def restart_app(self) -> None:
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        args = [a for a in args if a != "--restart"] + ["--restart"]
        QProcess.startDetached(sys.executable, args)
        self.quit()

    # ================================================================ janela / bandeja
    def show_normal(self) -> None:
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_normal()

    def changeEvent(self, e) -> None:
        if e.type() == e.Type.WindowStateChange and self.isMinimized():
            if self.ctl.settings.get("ui.minimize_to_tray") and QSystemTrayIcon.isSystemTrayAvailable():
                QTimer.singleShot(0, self.hide)
        super().changeEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast._reposition()
        compact = self.width() < 1180
        self.chip_in_text.setVisible(not compact)
        self.chip_out_text.setVisible(self.width() >= 1050)

    def closeEvent(self, e) -> None:
        self.ctl.settings.set("ui.window_geometry", bytes(self.saveGeometry().toBase64()).decode())
        if (not self._quitting and self.ctl.settings.get("ui.close_to_tray")
                and QSystemTrayIcon.isSystemTrayAvailable()):
            e.ignore()
            self.hide()
            if not self.ctl.settings.get("ui.tray_hint_shown"):
                self.tray.showMessage(APP_DISPLAY_NAME, f"O {APP_DISPLAY_NAME} continua rodando na bandeja do sistema.",
                                      QSystemTrayIcon.Information, 3000)
                self.ctl.settings.set("ui.tray_hint_shown", True)
            return
        e.accept()
        self.quit()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.ctl.settings.set("ui.window_geometry", bytes(self.saveGeometry().toBase64()).decode())
        self._tick.stop()
        self.tray.hide()
        self.close()
        QApplication.instance().quit()
