"""Diálogo de edição de snippet."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from core.app_controller import AppController
from soundboard.library import SNIPPET_COLORS
from ui.widgets.common import button, label
from ui.widgets.hotkey_edit import HotkeyEdit
from ui.widgets.param_slider import ParamSlider
from ui.widgets.pickers import ColorSwatches, EmojiPicker

AUDIO_FILTER = "Áudio (*.wav *.mp3 *.ogg *.flac)"


class SnippetDialog(QDialog):
    def __init__(self, controller: AppController, snippet_id: int, parent=None):
        super().__init__(parent)
        self.ctl = controller
        self.snippet = controller.snippet(snippet_id)
        s = self.snippet
        self.setWindowTitle("Editar som")
        self.setMinimumWidth(520)

        self.name = QLineEdit(s.name)
        self.name.setMaxLength(60)

        self.category = QComboBox()
        self.category.addItem("Sem categoria", None)
        for c in controller.library.categories():
            self.category.addItem(f"{c.icon}  {c.name}", c.id)
        self.category.setCurrentIndex(max(0, self.category.findData(s.category_id)))

        self.icon_picker = EmojiPicker()
        self.icon_picker.select(s.icon)
        self.colors = ColorSwatches(SNIPPET_COLORS, columns=15)
        self.colors.select(s.color)

        self.volume = ParamSlider("Volume", 0.0, 2.0, s.volume, percent=True)
        self.speed = ParamSlider("Velocidade", 0.5, 2.0, s.speed, step=0.05, unit="x", decimals=2)
        self.loop = QCheckBox("Repetir em loop")
        self.loop.setChecked(s.loop)
        self.favorite = QCheckBox("Favorito")
        self.favorite.setChecked(s.favorite)
        self.hotkey = HotkeyEdit(s.hotkey)

        self.file_label = label(s.original_filename or s.file_path, "Faint", wrap=True)
        replace_btn = button("Substituir arquivo…", "upload")
        replace_btn.clicked.connect(self._replace)
        preview_btn = button("Prévia", "headphones", tooltip="Ouvir só no monitor (não vai para a saída virtual)")
        preview_btn.clicked.connect(lambda: self.ctl.play_snippet(s.id, preview=True))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Nome", self.name)
        form.addRow("Categoria", self.category)
        form.addRow("Ícone", self.icon_picker)
        form.addRow("Cor", self.colors)
        form.addRow("", self.volume)
        form.addRow("", self.speed)
        opts = QHBoxLayout()
        opts.addWidget(self.loop)
        opts.addWidget(self.favorite)
        opts.addStretch(1)
        form.addRow("", opts)
        form.addRow("Atalho global", self.hotkey)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(preview_btn)
        file_row.addWidget(replace_btn)
        form.addRow("Arquivo", file_row)

        save = button("Salvar", "check", accent=True)
        save.clicked.connect(self._save)
        cancel = button("Cancelar")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(16)
        title = QLabel("Editar som")
        title.setObjectName("H2")
        root.addWidget(title)
        root.addLayout(form)
        root.addLayout(buttons)

    def _replace(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Substituir arquivo de áudio", "", AUDIO_FILTER)
        if path and self.ctl.replace_snippet_file(self.snippet.id, path):
            self.snippet = self.ctl.snippet(self.snippet.id)
            self.file_label.setText(self.snippet.original_filename)

    def _save(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Nome obrigatório", "Informe um nome para o som.")
            return
        new_hotkey = self.hotkey.hotkey()
        if new_hotkey != self.snippet.hotkey:
            ok, err = self.ctl.assign_hotkey(f"snippet:{self.snippet.id}", new_hotkey)
            if not ok:
                QMessageBox.warning(self, "Conflito de atalho", err)
                return
        category = self.category.currentData()
        if category != self.snippet.category_id:
            self.ctl.move_snippet(self.snippet.id, category)
        self.ctl.update_snippet(
            self.snippet.id,
            name=name,
            icon=self.icon_picker.current() or self.snippet.icon,
            color=self.colors.current(),
            volume=self.volume.value(),
            speed=self.speed.value(),
            loop=self.loop.isChecked(),
            favorite=self.favorite.isChecked(),
        )
        self.accept()
