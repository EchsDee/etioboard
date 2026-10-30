"""Interruptor animado (estilo iOS/Fluent)."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton

from ui import theme


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setCheckedSilently(self, checked: bool) -> None:
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._anim.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def paintEvent(self, _event) -> None:
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off, on = QColor(p.surface3), QColor(p.accent)
        if not self.isEnabled():
            on = QColor(p.text_faint)
        t = self._pos
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * t
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, r.top() + 3, d, d))
