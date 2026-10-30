"""Medidor de nível (VU/peak) com suavização e retenção de pico."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from ui import theme

MIN_DB = -60.0


def lin_to_frac(x: float) -> float:
    if x <= 1e-6:
        return 0.0
    db = 20 * math.log10(x)
    return max(0.0, min(1.0, (db - MIN_DB) / -MIN_DB))


class LevelMeter(QWidget):
    def __init__(self, orientation=Qt.Horizontal, thickness: int = 8, parent=None):
        super().__init__(parent)
        self.orientation = orientation
        self.thickness = thickness
        self._level = 0.0
        self._peak = 0.0
        self._peak_time = 0.0
        if orientation == Qt.Horizontal:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setFixedHeight(thickness)
        else:
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self.setFixedWidth(thickness)

    def sizeHint(self) -> QSize:
        return QSize(160, self.thickness) if self.orientation == Qt.Horizontal else QSize(self.thickness, 160)

    def set_level(self, linear: float) -> None:
        frac = lin_to_frac(linear)
        # ataque instantâneo, queda suave
        self._level = frac if frac > self._level else self._level * 0.82 + frac * 0.18
        now = time.monotonic()
        if frac >= self._peak or now - self._peak_time > 1.2:
            self._peak = max(frac, self._peak * 0.96 if now - self._peak_time > 1.2 else frac)
            if frac >= self._peak:
                self._peak_time = now
        self.update()

    def paintEvent(self, _event) -> None:
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        radius = min(r.width(), r.height()) / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(p.surface3))
        painter.drawRoundedRect(r, radius, radius)

        horizontal = self.orientation == Qt.Horizontal
        if horizontal:
            grad = QLinearGradient(r.left(), 0, r.right(), 0)
        else:
            grad = QLinearGradient(0, r.bottom(), 0, r.top())
        grad.setColorAt(0.0, QColor("#22C55E"))
        grad.setColorAt(0.70, QColor("#84CC16"))
        grad.setColorAt(0.85, QColor("#F59E0B"))
        grad.setColorAt(1.0, QColor("#EF4444"))

        if self._level > 0.005:
            if horizontal:
                fill = QRectF(r.left(), r.top(), r.width() * self._level, r.height())
            else:
                h = r.height() * self._level
                fill = QRectF(r.left(), r.bottom() - h, r.width(), h)
            painter.setBrush(grad)
            painter.drawRoundedRect(fill, radius, radius)

        if self._peak > 0.01:
            painter.setBrush(QColor(p.text))
            if horizontal:
                x = r.left() + (r.width() - 2) * self._peak
                painter.drawRect(QRectF(x, r.top(), 2, r.height()))
            else:
                y = r.bottom() - (r.height() - 2) * self._peak - 2
                painter.drawRect(QRectF(r.left(), y, r.width(), 2))


class ActivityDot(QWidget):
    """Indicador circular de atividade do microfone."""

    def __init__(self, size: int = 10, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._value = 0.0
        self._color = QColor("#22C55E")

    def set_value(self, frac: float, color: str | None = None) -> None:
        self._value = max(0.0, min(1.0, frac))
        if color:
            self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = QColor(self._color)
        c.setAlphaF(0.25 + 0.75 * self._value)
        painter.setPen(Qt.NoPen)
        painter.setBrush(c)
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
