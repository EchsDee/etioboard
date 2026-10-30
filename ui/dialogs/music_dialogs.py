"""Diálogos de edição musical: acorde, tonalidade e ordem de processamento dos efeitos."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from autotune.music import CHORD_QUALITIES, NOTE_NAMES, SCALES
from ui.widgets.common import button, label

QUALITY_NAMES = {"maj": "Maior", "min": "Menor", "7": "Sétima (7)", "m7": "Menor com sétima (m7)"}


def _buttons(dlg: QDialog, extra=None) -> QHBoxLayout:
    row = QHBoxLayout()
    if extra:
        row.addWidget(extra)
    row.addStretch(1)
    cancel = button("Cancelar")
    cancel.clicked.connect(dlg.reject)
    ok = button("Aplicar", "check", accent=True)
    ok.clicked.connect(dlg.accept)
    row.addWidget(cancel)
    row.addWidget(ok)
    return row


class ChordDialog(QDialog):
    """Corrige um acorde identificado (ou marca como 'sem acorde')."""

    def __init__(self, root: int | None, quality: str | None, time_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar acorde")
        self.root = QComboBox()
        self.root.addItem("Sem acorde (N)", None)
        for i, n in enumerate(NOTE_NAMES):
            self.root.addItem(n, i)
        self.root.setCurrentIndex(self.root.findData(root) if root is not None else 0)
        self.quality = QComboBox()
        for q in CHORD_QUALITIES:
            self.quality.addItem(QUALITY_NAMES[q], q)
        self.quality.setCurrentIndex(max(0, self.quality.findData(quality)))
        self.root.currentIndexChanged.connect(lambda: self.quality.setEnabled(self.root.currentData() is not None))
        self.quality.setEnabled(root is not None)
        form = QFormLayout()
        form.addRow("Fundamental", self.root)
        form.addRow("Tipo", self.quality)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.addWidget(label("Editar acorde", "H2"))
        lay.addWidget(label(time_text, "Faint"))
        lay.addLayout(form)
        lay.addLayout(_buttons(self))

    def values(self) -> tuple[int | None, str | None]:
        root = self.root.currentData()
        return root, (self.quality.currentData() if root is not None else None)


class KeyDialog(QDialog):
    """Define tonalidade e escala (de um trecho ou da música inteira)."""

    def __init__(self, tonic: int, scale: str, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.tonic = QComboBox()
        for i, n in enumerate(NOTE_NAMES):
            self.tonic.addItem(n, i)
        self.tonic.setCurrentIndex(int(tonic) % 12)
        self.scale = QComboBox()
        for k, (name, _) in SCALES.items():
            self.scale.addItem(name, k)
        self.scale.setCurrentIndex(max(0, self.scale.findData(scale)))
        form = QFormLayout()
        form.addRow("Tônica", self.tonic)
        form.addRow("Escala", self.scale)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.addWidget(label(title, "H2"))
        if subtitle:
            lay.addWidget(label(subtitle, "Faint", wrap=True))
        lay.addLayout(form)
        lay.addLayout(_buttons(self))

    def values(self) -> tuple[int, str]:
        return self.tonic.currentData(), self.scale.currentData()


class EffectOrderDialog(QDialog):
    """Reordena a cadeia de processamento da voz (arrastar e soltar)."""

    def __init__(self, order: list[str], names: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ordem de processamento")
        self.setMinimumWidth(380)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self._names = names
        self._fill(order)
        self.reset_requested = False
        reset = button("Restaurar padrão", "undo")
        reset.clicked.connect(self._reset)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.addWidget(label("Ordem de processamento da voz", "H2"))
        lay.addWidget(label("Arraste para reordenar. O sinal passa de cima para baixo: "
                            "Microfone → … → Mixer → Saída virtual. Recomendado: Noise Gate e Auto-Tune primeiro.",
                            "Faint", wrap=True))
        lay.addWidget(QLabel("Microfone ↓"))
        lay.addWidget(self.list, 1)
        lay.addWidget(QLabel("↓ Mixer / saída virtual"))
        lay.addLayout(_buttons(self, reset))

    def _fill(self, order: list[str]) -> None:
        self.list.clear()
        for eid in order:
            it = QListWidgetItem(f"  ≡   {self._names.get(eid, eid)}")
            it.setData(Qt.UserRole, eid)
            self.list.addItem(it)

    def _reset(self) -> None:
        from effects.chain import DEFAULT_ORDER
        self._fill(list(DEFAULT_ORDER))
        self.reset_requested = True

    def order(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]
