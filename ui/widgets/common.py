"""Helpers de construção de UI."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui import icons, theme


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setObjectName(role)
    lbl.setWordWrap(wrap)
    return lbl


def button(text: str = "", icon_name: str | None = None, accent: bool = False, danger: bool = False,
           flat: bool = False, tooltip: str = "", icon_color: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    if accent:
        btn.setProperty("accent", True)
    if danger:
        btn.setProperty("danger", True)
    if flat:
        btn.setProperty("flat", True)
    if icon_name:
        p = theme.current()
        color = icon_color or ("#FFFFFF" if accent else ("#F87171" if danger else p.text))
        btn.setIcon(icons.icon(icon_name, color, 18))
        btn.setIconSize(QSize(16, 16))
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def tool_button(icon_name: str, tooltip: str = "", size: int = 18, color: str | None = None,
                checkable: bool = False, active_color: str | None = None) -> QToolButton:
    p = theme.current()
    btn = QToolButton()
    btn.setCursor(Qt.PointingHandCursor)
    btn.setIcon(icons.icon(icon_name, color or p.text_dim, size, active_color=active_color))
    btn.setIconSize(QSize(size, size))
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    return btn


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, padding: int = 16, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0), stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for i, w in enumerate(widgets):
        if stretch_at is not None and i == stretch_at:
            lay.addStretch(1)
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


def vbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


def separator() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.current().border};")
    line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return line


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
