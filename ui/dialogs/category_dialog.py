"""Diálogo de criação/edição de categoria."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout

from ui.widgets.common import button
from ui.widgets.pickers import ColorSwatches, EmojiPicker

CATEGORY_COLORS = ["#6366F1", "#8B5CF6", "#EC4899", "#EF4444", "#F59E0B", "#22C55E", "#06B6D4",
                   "#3B82F6", "#64748B", "#A855F7"]


class CategoryDialog(QDialog):
    def __init__(self, name: str = "", icon: str = "📁", color: str = "#6366F1", title: str = "Nova categoria",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.name = QLineEdit(name)
        self.name.setMaxLength(40)
        self.name.setPlaceholderText("Ex.: Memes")
        self.icon = EmojiPicker()
        self.icon.select(icon)
        self.color = ColorSwatches(CATEGORY_COLORS, columns=11)
        self.color.select(color)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setVerticalSpacing(10)
        form.addRow("Nome", self.name)
        form.addRow("Ícone", self.icon)
        form.addRow("Cor", self.color)

        ok = button("Salvar", "check", accent=True)
        ok.clicked.connect(self._accept)
        cancel = button("Cancelar")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(16)
        t = QLabel(title)
        t.setObjectName("H2")
        root.addWidget(t)
        root.addLayout(form)
        root.addLayout(row)

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Nome obrigatório", "Informe um nome para a categoria.")
            return
        self.accept()

    def values(self) -> tuple[str, str, str]:
        return self.name.text().strip(), self.icon.current() or "📁", self.color.current()
