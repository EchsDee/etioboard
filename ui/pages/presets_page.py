"""Gerenciamento de presets de voz."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.app_controller import AppController
from effects.chain import EFFECT_CLASSES
from presets.preset_manager import Preset
from ui import theme
from ui.widgets.common import Card, button, label, tool_button
from ui.widgets.hotkey_edit import HotkeyEdit


class PresetRow(QFrame):
    def __init__(self, page: "PresetsPage", preset: Preset, active: bool, first: bool, last: bool):
        super().__init__()
        self.page = page
        self.preset = preset
        ctl = page.ctl
        p = theme.current()
        self.setObjectName("Card")
        if active:
            self.setStyleSheet(f"#Card {{ border: 1px solid {p.accent}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(10)

        info = QVBoxLayout()
        info.setSpacing(3)
        title = QHBoxLayout()
        title.setSpacing(8)
        title.addWidget(label(preset.name, "H3"))
        if active:
            title.addWidget(label("Ativo", "Badge"))
        if preset.is_default:
            title.addWidget(label("★ Padrão", "Badge"))
        title.addStretch(1)
        info.addLayout(title)
        enabled = [EFFECT_CLASSES[eid].display_name for eid, e in preset.state.items() if e["enabled"]]
        info.addWidget(label(", ".join(enabled) if enabled else "Sem efeitos", "Faint", wrap=True))
        lay.addLayout(info, 1)

        self.hotkey = HotkeyEdit(preset.hotkey)
        self.hotkey.setToolTip("Atalho global para ativar este preset")
        self.hotkey.hotkeyChanged.connect(self._hotkey_changed)
        self.hotkey.setFixedWidth(190)
        lay.addWidget(self.hotkey)

        activate = button("Ativar" if not active else "Editar", "play" if not active else "edit", accent=not active)
        activate.clicked.connect(self._activate)
        lay.addWidget(activate)

        up = tool_button("chevron-up", "Mover para cima", 16)
        up.setEnabled(not first)
        up.clicked.connect(lambda: page.move(preset.id, -1))
        down = tool_button("chevron-down", "Mover para baixo", 16)
        down.setEnabled(not last)
        down.clicked.connect(lambda: page.move(preset.id, 1))
        rename = tool_button("edit", "Renomear", 16)
        rename.clicked.connect(self._rename)
        dup = tool_button("copy", "Duplicar", 16)
        dup.clicked.connect(lambda: ctl.duplicate_preset(preset.id))
        default = tool_button("star", "Definir como padrão (carregado ao abrir o app)", 16,
                              color="#FBBF24" if preset.is_default else None)
        default.clicked.connect(lambda: ctl.set_default_preset(preset.id))
        delete = tool_button("trash", "Excluir", 16, color="#F87171")
        delete.clicked.connect(self._delete)
        for w in (up, down, rename, dup, default, delete):
            lay.addWidget(w)

    def _activate(self) -> None:
        ctl = self.page.ctl
        if ctl.active_preset_id != self.preset.id:
            ctl.load_preset(self.preset.id, announce=True)
        else:
            self.page.edit_requested.emit()

    def _rename(self) -> None:
        name, ok = QInputDialog.getText(self, "Renomear preset", "Nome:", text=self.preset.name)
        if ok and name.strip():
            self.page.ctl.rename_preset(self.preset.id, name.strip())

    def _delete(self) -> None:
        if QMessageBox.question(self, "Excluir preset", f"Excluir o preset “{self.preset.name}”?") == QMessageBox.Yes:
            self.page.ctl.delete_preset(self.preset.id)

    def _hotkey_changed(self, hotkey) -> None:
        ok, err = self.page.ctl.assign_hotkey(f"preset:{self.preset.id}", hotkey)
        if not ok:
            QMessageBox.warning(self, "Conflito de atalho", err)
            self.hotkey.setHotkey(self.preset.hotkey)


class PresetsPage(QWidget):
    edit_requested = Signal()

    def __init__(self, ctl: AppController, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctl = ctl

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Presets de voz", "H1"))
        titles.addWidget(label("Crie, organize e alterne entre combinações de efeitos. "
                               "Atribua atalhos para trocar de voz durante o jogo.", "Dim", wrap=True))
        head.addLayout(titles, 1)
        new_blank = button("Novo vazio", "plus")
        new_blank.clicked.connect(lambda: self._new(False))
        head.addWidget(new_blank)
        new_cur = button("Novo a partir do atual", "copy", accent=True)
        new_cur.clicked.connect(lambda: self._new(True))
        head.addWidget(new_cur)

        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 8, 0)
        self.list_lay.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.list_host)

        tip = Card(padding=12)
        tip.body.addWidget(label("Dica: os atalhos “Próximo/Anterior preset” podem ser configurados em "
                                 "Configurações → Atalhos globais.", "Faint", wrap=True))

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        root.addLayout(head)
        root.addWidget(scroll, 1)
        root.addWidget(tip)

        ctl.presets_changed.connect(self.reload)
        ctl.active_preset_changed.connect(lambda _id: self.reload())
        self.reload()

    def reload(self) -> None:
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        presets = self.ctl.preset_list()
        active = self.ctl.active_preset_id
        for i, p in enumerate(presets):
            self.list_lay.addWidget(PresetRow(self, p, p.id == active, i == 0, i == len(presets) - 1))
        self.list_lay.addStretch(1)

    def move(self, preset_id: int, step: int) -> None:
        ids = [p.id for p in self.ctl.preset_list()]
        i = ids.index(preset_id)
        j = i + step
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            self.ctl.reorder_presets(ids)

    def _new(self, from_current: bool) -> None:
        name, ok = QInputDialog.getText(self, "Novo preset", "Nome do preset:")
        if ok and name.strip():
            self.ctl.create_preset(name.strip(), from_current=from_current)
            self.edit_requested.emit()
