"""Notificações discretas (toast) no canto inferior da janela."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from ui import icons, theme

_LEVELS = {
    "info": ("activity", None),
    "success": ("check", "#22C55E"),
    "warning": ("alert", "#F59E0B"),
    "error": ("alert", "#EF4444"),
}


class Toast(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.icon = QLabel()
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setMaximumWidth(460)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 16, 10)
        lay.setSpacing(10)
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._anim = QPropertyAnimation(self._opacity, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, level: str, message: str, msec: int = 2600) -> None:
        p = theme.current()
        name, color = _LEVELS.get(level, _LEVELS["info"])
        color = color or p.accent
        self.setStyleSheet(f"background: {p.surface3}; border: 1px solid {p.border}; border-radius: 12px;")
        self.text.setStyleSheet(f"background: transparent; border: none; color: {p.text};")
        self.icon.setStyleSheet("background: transparent; border: none;")
        self.icon.setPixmap(icons.pixmap(name, color, 18))
        self.text.setText(message)
        self.adjustSize()
        self._reposition()
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.setStartValue(self._opacity.opacity() if self.isVisible() else 0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(msec if level != "error" else msec * 2)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent:
            self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 24)

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_once)
        self._anim.start()

    def _hide_once(self) -> None:
        self._anim.finished.disconnect(self._hide_once)
        if self._opacity.opacity() <= 0.01:
            self.hide()
