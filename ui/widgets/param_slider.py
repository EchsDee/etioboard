"""Slider de parâmetro com rótulo e caixa numérica editável (escala linear ou logarítmica)."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit, QSlider, QWidget

RESOLUTION = 1000


class ValueEdit(QLineEdit):
    """Campo numérico compacto: digite um valor (vírgula ou ponto), setas/roda do mouse ajustam."""

    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, step: float, decimals: int, suffix: str = ""):
        super().__init__()
        self.setObjectName("ValueBox")
        self.minimum, self.maximum, self.step = minimum, maximum, step
        self.decimals, self.suffix = decimals, suffix
        self._value = minimum
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.editingFinished.connect(self._commit)
        self._show()

    def value(self) -> float:
        return self._value

    def setValue(self, v: float) -> None:
        v = min(self.maximum, max(self.minimum, float(v)))
        changed = abs(v - self._value) > 1e-12
        self._value = v
        if not self.hasFocus():
            self._show()
        if changed:
            self.valueChanged.emit(v)

    def _show(self) -> None:
        text = f"{self._value:.{self.decimals}f}".replace(".", ",")
        self.setText(f"{text}{self.suffix}")

    def _commit(self) -> None:
        raw = self.text()
        if self.suffix.strip():
            raw = raw.replace(self.suffix.strip(), "")
        raw = raw.replace(",", ".").strip()
        try:
            self.setValue(float(raw))
        except ValueError:
            pass
        self._show()

    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        self.setText(f"{self._value:.{self.decimals}f}".replace(".", ","))
        self.selectAll()

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        self._show()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Up, Qt.Key_Down):
            self.setValue(self._value + (self.step if e.key() == Qt.Key_Up else -self.step))
            self.setText(f"{self._value:.{self.decimals}f}".replace(".", ","))
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e) -> None:
        if self.hasFocus():
            self.setValue(self._value + (self.step if e.angleDelta().y() > 0 else -self.step))
            self.setText(f"{self._value:.{self.decimals}f}".replace(".", ","))
            e.accept()
        else:
            e.ignore()


class ParamSlider(QWidget):
    valueChanged = Signal(float)

    def __init__(self, label: str, minimum: float, maximum: float, value: float, step: float = 0.01,
                 unit: str = "", decimals: int = 2, log: bool = False, percent: bool = False, parent=None):
        super().__init__(parent)
        self.minimum, self.maximum = float(minimum), float(maximum)
        self.log = log and minimum > 0
        self.percent = percent
        self._updating = False

        self.label = QLabel(label)
        self.label.setObjectName("Dim")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, RESOLUTION)
        self.slider.setCursor(Qt.PointingHandCursor)
        if percent:
            self.box = ValueEdit(minimum * 100, maximum * 100, 1, 0, " %")
        else:
            self.box = ValueEdit(minimum, maximum, step, decimals, f" {unit}" if unit else "")
        self.box.setFixedWidth(84)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.addWidget(self.label, 0, 0)
        grid.addWidget(self.box, 0, 1, Qt.AlignRight)
        grid.addWidget(self.slider, 1, 0, 1, 2)

        self.slider.valueChanged.connect(self._from_slider)
        self.box.valueChanged.connect(self._from_box)
        self.setValue(value)

    # mapeamento posição <-> valor
    def _to_pos(self, v: float) -> int:
        v = min(self.maximum, max(self.minimum, v))
        if self.log:
            frac = math.log(v / self.minimum) / math.log(self.maximum / self.minimum)
        else:
            frac = (v - self.minimum) / (self.maximum - self.minimum)
        return int(round(frac * RESOLUTION))

    def _from_pos(self, pos: int) -> float:
        frac = pos / RESOLUTION
        if self.log:
            return self.minimum * (self.maximum / self.minimum) ** frac
        return self.minimum + frac * (self.maximum - self.minimum)

    def value(self) -> float:
        v = self.box.value()
        return v / 100.0 if self.percent else v

    def setValue(self, v: float) -> None:
        self._updating = True
        self.box.setValue(v * 100.0 if self.percent else v)
        self.slider.setValue(self._to_pos(v))
        self._updating = False

    def _from_slider(self, pos: int) -> None:
        if self._updating:
            return
        v = self._from_pos(pos)
        self._updating = True
        self.box.setValue(v * 100.0 if self.percent else v)
        self._updating = False
        self.valueChanged.emit(self.value())

    def _from_box(self, _v: float) -> None:
        if self._updating:
            return
        self._updating = True
        self.slider.setValue(self._to_pos(self.value()))
        self._updating = False
        self.valueChanged.emit(self.value())

    def mouseDoubleClickEvent(self, event) -> None:  # duplo clique no rótulo: foca o valor
        self.box.setFocus()
        self.box.selectAll()
        super().mouseDoubleClickEvent(event)
