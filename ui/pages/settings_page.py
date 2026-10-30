"""Configurações: áudio, dispositivo virtual, soundboard, atalhos, interface e dados."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from audio.device_manager import VB_CABLE_URL
from core.app_controller import GLOBAL_ACTIONS, AppController
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from ui import icons
from ui.theme import ACCENTS
from ui.widgets.common import Card, button, label
from ui.widgets.hotkey_edit import HotkeyEdit
from ui.widgets.param_slider import ParamSlider
from utils.paths import app_data_dir

AUTO = "__auto__"
DEFAULT = "__default__"


def _form() -> QFormLayout:
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    f.setHorizontalSpacing(18)
    f.setVerticalSpacing(10)
    f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    return f


def _color_dot(color: str) -> QIcon:
    pm = QPixmap(28, 28)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(4, 4, 20, 20)
    p.end()
    return QIcon(pm)


class SettingsPage(QWidget):
    theme_changed = Signal()

    def __init__(self, ctl: AppController, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctl = ctl
        s = ctl.settings

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 10, 0)
        col.setSpacing(14)
        col.addWidget(label("Configurações", "H1"))

        # ============================================================ banner VB-CABLE
        self.banner = Card(padding=14)
        self.banner.setObjectName("Banner")
        bh = QHBoxLayout()
        bi = QLabel()
        bi.setPixmap(icons.pixmap("alert", "#F59E0B", 22))
        bh.addWidget(bi, 0, Qt.AlignTop)
        bt = QVBoxLayout()
        bt.addWidget(label("Dispositivo de áudio virtual não encontrado", "H3"))
        bt.addWidget(label(
            "Para que Discord, jogos e outros apps recebam sua voz modificada e o soundboard como microfone, "
            "instale um cabo de áudio virtual gratuito como o VB-CABLE. Depois de instalar, clique em "
            "“Atualizar dispositivos”, selecione “CABLE Input” como saída virtual aqui e escolha "
            "“CABLE Output” como microfone no Discord/jogo.", "Dim", wrap=True))
        bb = QHBoxLayout()
        get = button("Baixar VB-CABLE", "external", accent=True)
        get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(VB_CABLE_URL)))
        bb.addWidget(get)
        refresh = button("Atualizar dispositivos", "refresh")
        refresh.clicked.connect(self._refresh_devices)
        bb.addWidget(refresh)
        bb.addStretch(1)
        bt.addLayout(bb)
        bh.addLayout(bt, 1)
        self.banner.body.addLayout(bh)
        col.addWidget(self.banner)

        # ============================================================ áudio
        audio = Card(padding=18)
        ah = QHBoxLayout()
        ah.addWidget(label("Áudio", "H2"))
        ah.addStretch(1)
        rb = button("Atualizar dispositivos", "refresh")
        rb.clicked.connect(self._refresh_devices)
        ah.addWidget(rb)
        audio.body.addLayout(ah)
        f = _form()
        self.api = QComboBox()
        self.api.currentIndexChanged.connect(self._api_changed)
        f.addRow("API de áudio", self.api)
        self.input = QComboBox()
        f.addRow("Microfone (entrada)", self.input)
        self.virtual = QComboBox()
        self.virtual_enabled = QCheckBox("Enviar para a saída virtual")
        vrow = QHBoxLayout()
        vrow.addWidget(self.virtual, 1)
        vrow.addWidget(self.virtual_enabled)
        f.addRow("Dispositivo virtual", vrow)
        self.monitor = QComboBox()
        self.monitor_enabled = QCheckBox("Ativar monitor")
        mrow = QHBoxLayout()
        mrow.addWidget(self.monitor, 1)
        mrow.addWidget(self.monitor_enabled)
        f.addRow("Saída (fones/monitor)", mrow)
        self.samplerate = QComboBox()
        for sr in (44100, 48000):
            self.samplerate.addItem(f"{sr} Hz", sr)
        f.addRow("Sample rate", self.samplerate)
        self.blocksize = QComboBox()
        for bs in (128, 256, 512, 1024):
            self.blocksize.addItem(str(bs), bs)
        self.block_ms = label("", "Faint")
        brow = QHBoxLayout()
        brow.addWidget(self.blocksize, 1)
        brow.addWidget(self.block_ms)
        f.addRow("Buffer size (amostras)", brow)
        self.latency = QComboBox()
        self.latency.addItem("Baixa latência (pode estalar em PCs lentos)", "low")
        self.latency.addItem("Equilibrada (recomendado)", "balanced")
        self.latency.addItem("Segura (mais estável, mais atraso)", "safe")
        f.addRow("Latência", self.latency)
        audio.body.addLayout(f)
        self.samplerate.currentIndexChanged.connect(self._update_block_ms)
        self.blocksize.currentIndexChanged.connect(self._update_block_ms)

        arow = QHBoxLayout()
        self.audio_info = label("", "Faint", wrap=True)
        arow.addWidget(self.audio_info, 1)
        apply = button("Aplicar e reiniciar áudio", "check", accent=True)
        apply.clicked.connect(self._apply_audio)
        arow.addWidget(apply)
        audio.body.addLayout(arow)
        col.addWidget(audio)

        # ============================================================ soundboard
        sb = Card(padding=18)
        sb.body.addWidget(label("Soundboard", "H2"))
        f2 = _form()
        self.play_mode = QComboBox()
        self.play_mode.addItem("Reiniciar o som", "restart")
        self.play_mode.addItem("Parar o som (liga/desliga)", "toggle")
        self.play_mode.addItem("Sobrepor (tocar outra cópia)", "overlap")
        self.play_mode.setCurrentIndex(max(0, self.play_mode.findData(s.get("soundboard.playback_mode"))))
        self.play_mode.currentIndexChanged.connect(
            lambda: s.set("soundboard.playback_mode", self.play_mode.currentData()))
        f2.addRow("Ao clicar em um som que já está tocando", self.play_mode)
        self.copy_files = QCheckBox("Copiar arquivos importados para a pasta do aplicativo (recomendado)")
        self.copy_files.setChecked(bool(s.get("soundboard.copy_files", True)))
        self.copy_files.toggled.connect(lambda on: s.set("soundboard.copy_files", on))
        f2.addRow("Importação", self.copy_files)
        self.btn_size = ParamSlider("Tamanho dos botões", 90, 180, s.get("soundboard.button_size", 120), 1, "px", 0)
        self.btn_size.valueChanged.connect(self._button_size)
        f2.addRow("", self.btn_size)
        sb.body.addLayout(f2)
        col.addWidget(sb)

        # ============================================================ atalhos
        hk = Card(padding=18)
        hk.body.addWidget(label("Atalhos globais", "H2"))
        hk.body.addWidget(label("Funcionam mesmo com o app minimizado ou em segundo plano. Os atalhos de cada som "
                                "são definidos no próprio som (botão direito → Editar) e os de presets na página "
                                "Presets. Conflitos são detectados automaticamente.", "Faint", wrap=True))
        f3 = _form()
        self.hotkey_edits: dict[str, HotkeyEdit] = {}
        current = ctl.action_hotkeys()
        for action, text in GLOBAL_ACTIONS.items():
            edit = HotkeyEdit(current.get(action))
            edit.hotkeyChanged.connect(lambda h, a=action: self._set_hotkey(a, h))
            self.hotkey_edits[action] = edit
            f3.addRow(text, edit)
        hk.body.addLayout(f3)
        col.addWidget(hk)

        # ============================================================ interface
        ui = Card(padding=18)
        ui.body.addWidget(label("Interface e sistema", "H2"))
        f4 = _form()
        self.theme_box = QComboBox()
        self.theme_box.addItem("Escuro", "dark")
        self.theme_box.addItem("Claro", "light")
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(s.get("ui.theme"))))
        self.theme_box.currentIndexChanged.connect(self._theme)
        f4.addRow("Tema", self.theme_box)
        self.accent = QComboBox()
        for name, color in ACCENTS.items():
            self.accent.addItem(_color_dot(color), name, color)
        self.accent.setCurrentIndex(max(0, self.accent.findData(s.get("ui.accent"))))
        self.accent.currentIndexChanged.connect(self._theme)
        f4.addRow("Cor de destaque", self.accent)
        self.tray_min = QCheckBox("Minimizar para a bandeja do sistema")
        self.tray_min.setChecked(bool(s.get("ui.minimize_to_tray")))
        self.tray_min.toggled.connect(lambda on: s.set("ui.minimize_to_tray", on))
        self.tray_close = QCheckBox("Fechar a janela mantém o app rodando na bandeja")
        self.tray_close.setChecked(bool(s.get("ui.close_to_tray")))
        self.tray_close.toggled.connect(lambda on: s.set("ui.close_to_tray", on))
        self.start_min = QCheckBox("Iniciar minimizado")
        self.start_min.setChecked(bool(s.get("ui.start_minimized")))
        self.start_min.toggled.connect(lambda on: s.set("ui.start_minimized", on))
        self.autostart = QCheckBox("Iniciar com o Windows")
        self.autostart.setChecked(bool(s.get("system.start_with_windows")))
        self.autostart.toggled.connect(ctl.set_autostart)
        for w in (self.tray_min, self.tray_close, self.start_min, self.autostart):
            f4.addRow("", w)
        ui.body.addLayout(f4)
        col.addWidget(ui)

        # ============================================================ dados
        data = Card(padding=18)
        data.body.addWidget(label("Dados", "H2"))
        data.body.addWidget(label(f"Banco de dados, sons e logs ficam em: {app_data_dir()}", "Faint", wrap=True))
        drow = QHBoxLayout()
        open_btn = button("Abrir pasta de dados", "folder")
        open_btn.clicked.connect(lambda: os.startfile(str(app_data_dir())))
        exp = button("Exportar configurações (JSON)", "upload")
        exp.clicked.connect(self._export)
        imp = button("Importar configurações", "folder")
        imp.clicked.connect(self._import)
        restore = button("Restaurar presets originais", "undo")
        restore.clicked.connect(self._restore_presets)
        for b in (open_btn, exp, imp, restore):
            drow.addWidget(b)
        drow.addStretch(1)
        data.body.addLayout(drow)
        col.addWidget(data)
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 14, 18)
        root.addWidget(scroll)

        ctl.engine_status.connect(lambda _s: self._update_info())
        self.load_audio_settings()
        self._info_timer = QTimer(self)
        self._info_timer.setInterval(1000)
        self._info_timer.timeout.connect(self._update_info)
        self._info_timer.start()

    # ------------------------------------------------------------------ áudio
    def load_audio_settings(self) -> None:
        s, dm = self.ctl.settings, self.ctl.devices
        self.api.blockSignals(True)
        self.api.clear()
        for name in dm.hostapis():
            note = " (recomendado)" if name == "Windows WASAPI" else ""
            self.api.addItem(name + note, name)
        chosen = s.get("audio.hostapi") or dm.preferred_hostapi()
        self.api.setCurrentIndex(max(0, self.api.findData(chosen)))
        self.api.blockSignals(False)
        self._fill_devices()
        self.virtual_enabled.setChecked(bool(s.get("audio.virtual_enabled", True)))
        self.monitor_enabled.setChecked(bool(s.get("audio.monitor_enabled", True)))
        self.samplerate.setCurrentIndex(max(0, self.samplerate.findData(int(s.get("audio.samplerate")))))
        self.blocksize.setCurrentIndex(max(0, self.blocksize.findData(int(s.get("audio.blocksize")))))
        self.latency.setCurrentIndex(max(0, self.latency.findData(s.get("audio.latency_mode"))))
        self._update_block_ms()
        self.banner.setVisible(not dm.virtual_driver_installed())
        self._update_info()

    def _fill_devices(self) -> None:
        s, dm = self.ctl.settings, self.ctl.devices
        api = self.api.currentData()

        self.input.clear()
        self.input.addItem("Padrão do sistema", DEFAULT)
        for d in dm.inputs(api):
            self.input.addItem(d.name, (d.name, api))
        others = [d for d in dm.inputs(None) if d.hostapi != api]
        if others:
            self.input.insertSeparator(self.input.count())
            for d in others:
                self.input.addItem(f"{d.name}  [{d.hostapi}]", (d.name, d.hostapi))
        saved_in = s.get("audio.input_device")
        saved_api = s.get("audio.input_hostapi") or api
        idx = self.input.findData((saved_in, saved_api)) if saved_in else 0
        self.input.setCurrentIndex(max(0, idx))

        self.virtual.clear()
        detected = dm.detect_virtual_output(api)
        self.virtual.addItem(f"Detectar automaticamente ({detected.name if detected else 'nenhum encontrado'})", AUTO)
        for d in dm.outputs(api):
            tag = f"  ✓ {d.virtual_kind()}" if d.virtual_kind() else ""
            self.virtual.addItem(d.name + tag, d.name)
        saved_v = s.get("audio.virtual_device")
        self.virtual.setCurrentIndex(max(0, self.virtual.findData(saved_v)) if saved_v else 0)

        self.monitor.clear()
        self.monitor.addItem("Saída padrão do sistema", DEFAULT)
        for d in dm.outputs(api):
            if not d.virtual_kind():
                self.monitor.addItem(d.name, d.name)
        saved_m = s.get("audio.monitor_device")
        self.monitor.setCurrentIndex(max(0, self.monitor.findData(saved_m)) if saved_m else 0)

    def _api_changed(self) -> None:
        self._fill_devices()

    def _update_block_ms(self) -> None:
        sr = self.samplerate.currentData() or 48000
        bs = self.blocksize.currentData() or 256
        self.block_ms.setText(f"≈ {bs / sr * 1000:.1f} ms por bloco")

    def _apply_audio(self) -> None:
        s = self.ctl.settings
        s.set("audio.hostapi", self.api.currentData())
        inp = self.input.currentData()
        if inp == DEFAULT or inp is None:
            s.set("audio.input_device", None)
            s.set("audio.input_hostapi", None)
        else:
            s.set("audio.input_device", inp[0])
            s.set("audio.input_hostapi", inp[1] if inp[1] != self.api.currentData() else None)
        v = self.virtual.currentData()
        s.set("audio.virtual_device", None if v == AUTO else v)
        s.set("audio.virtual_enabled", self.virtual_enabled.isChecked())
        m = self.monitor.currentData()
        s.set("audio.monitor_device", None if m == DEFAULT else m)
        s.set("audio.monitor_enabled", self.monitor_enabled.isChecked())
        s.set("audio.samplerate", self.samplerate.currentData())
        s.set("audio.blocksize", self.blocksize.currentData())
        s.set("audio.latency_mode", self.latency.currentData())
        self.ctl.restart_audio()
        self.ctl.notify.emit("info", "Reiniciando áudio com as novas configurações…")

    def _refresh_devices(self) -> None:
        self.ctl.notify.emit("info", "Procurando dispositivos…")
        self.ctl.refresh_devices(done=lambda: QTimer.singleShot(0, self, self._after_refresh))

    def _after_refresh(self) -> None:
        self.load_audio_settings()
        found = self.ctl.devices.virtual_driver_installed()
        self.ctl.notify.emit("success" if found else "warning",
                             "Dispositivos atualizados" + ("" if found else " — nenhum cabo virtual encontrado"))

    def _update_info(self) -> None:
        if not self.isVisible():
            return
        st = self.ctl.status
        eng = self.ctl.engine
        parts = [f"Estado: {st.message or st.state}"]
        if st.state in ("running", "degraded"):
            parts.append(f"Latência estimada: {eng.current_latency_ms():.0f} ms")
            parts.append(f"Uso do DSP: {eng.dsp_load() * 100:.0f}%")
            parts.append(f"Falhas de buffer: {eng.xruns()}")
        if st.warnings:
            parts.append("Avisos: " + " | ".join(st.warnings))
        self.audio_info.setText("  •  ".join(parts))

    def showEvent(self, e) -> None:
        self._update_info()
        super().showEvent(e)

    # ------------------------------------------------------------------ outros
    def _button_size(self, v: float) -> None:
        self.ctl.settings.set("soundboard.button_size", int(v))
        self.ctl.library_changed.emit()

    def _set_hotkey(self, action: str, hotkey) -> None:
        ok, err = self.ctl.assign_hotkey(f"action:{action}", hotkey)
        if not ok:
            QMessageBox.warning(self, "Conflito de atalho", err)
            self.hotkey_edits[action].setHotkey(self.ctl.action_hotkeys().get(action))

    def _theme(self) -> None:
        self.ctl.settings.set("ui.theme", self.theme_box.currentData())
        self.ctl.settings.set("ui.accent", self.accent.currentData())
        self.theme_changed.emit()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar configurações", "voicestudio-config.json",
                                              "JSON (*.json)")
        if path:
            self.ctl.settings.export_json(path)
            self.ctl.notify.emit("success", "Configurações exportadas")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar configurações", "", "JSON (*.json)")
        if not path:
            return
        try:
            n = self.ctl.settings.import_json(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Erro", f"Arquivo inválido: {exc}")
            return
        self.ctl.notify.emit("success", f"{n} configurações importadas. Reinicie o app para aplicar todas.")
        self.load_audio_settings()

    def _restore_presets(self) -> None:
        if QMessageBox.question(self, "Restaurar presets",
                                "Restaurar os 8 presets originais? Alterações feitas neles serão perdidas; "
                                "seus presets personalizados não serão afetados.") == QMessageBox.Yes:
            self.ctl.restore_builtin_presets()
