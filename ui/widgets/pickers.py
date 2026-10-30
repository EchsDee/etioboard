"""Seletores de ícone (emoji) e de cor."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QColorDialog, QGridLayout, QPushButton, QToolButton, QWidget

from ui import theme

EMOJIS = (
    "🔊 🎵 🎶 🎤 🎧 🎸 🥁 🎺 🎹 📯 🔔 📢 📣 🚨 💥 💣 🔥 ⚡ ✨ 🌟 "
    "😂 🤣 😮 😱 😡 🤬 😭 😎 🤔 🙄 😏 🥳 🤡 👻 💀 👽 🤖 👾 😈 🐸 "
    "🐶 🐱 🦆 🐔 🐮 🐷 🐐 🦁 🐺 🐍 👏 👍 👎 🙌 🤝 💪 🫡 👀 💯 ❗ "
    "❓ ✅ ❌ ⛔ 🏆 🎮 🕹️ 🎯 🎲 🃏 ⚔️ 🛡️ 🔫 💰 💎 🍕 🍺 🚀 🏎️ 💨 "
    "📦 📁 🗣️ 💬 🎬 📺 📻 ☎️ ⏰ 🌈"
).split()


class EmojiPicker(QWidget):
    picked = Signal(str)

    def __init__(self, columns: int = 10, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setSpacing(2)
        grid.setContentsMargins(0, 0, 0, 0)
        font = QFont("Segoe UI Emoji")
        font.setPixelSize(18)
        self._buttons: dict[str, QToolButton] = {}
        for i, e in enumerate(EMOJIS):
            b = QToolButton()
            b.setText(e)
            b.setFont(font)
            b.setFixedSize(QSize(32, 32))
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, em=e: self.select(em, emit=True))
            grid.addWidget(b, i // columns, i % columns)
            self._buttons[e] = b
        self._current = ""

    def select(self, emoji: str, emit: bool = False) -> None:
        self._current = emoji
        for e, b in self._buttons.items():
            b.setChecked(e == emoji)
        if emit:
            self.picked.emit(emoji)

    def current(self) -> str:
        return self._current


class ColorSwatches(QWidget):
    picked = Signal(str)

    def __init__(self, colors: list[str], columns: int = 8, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)
        self._buttons: dict[str, QPushButton] = {}
        self._current = colors[0] if colors else "#6366F1"
        items = list(colors) + ["custom"]
        for i, c in enumerate(items):
            b = QPushButton("+" if c == "custom" else "")
            b.setFixedSize(QSize(28, 28))
            b.setCursor(Qt.PointingHandCursor)
            if c == "custom":
                b.setToolTip("Cor personalizada…")
                b.clicked.connect(self._custom)
            else:
                b.clicked.connect(lambda _=False, col=c: self.select(col, emit=True))
                self._buttons[c] = b
            grid.addWidget(b, i // columns, i % columns)
        self._restyle()

    def _restyle(self) -> None:
        p = theme.current()
        for c, b in self._buttons.items():
            border = f"3px solid {p.text}" if c.lower() == self._current.lower() else "1px solid rgba(255,255,255,0.15)"
            b.setStyleSheet(f"QPushButton {{ background: {c}; border: {border}; border-radius: 14px; padding: 0; }}")

    def _custom(self) -> None:
        color = QColorDialog.getColor(QColor(self._current), self, "Escolher cor")
        if color.isValid():
            self.select(color.name(), emit=True)

    def select(self, color: str, emit: bool = False) -> None:
        self._current = color
        self._restyle()
        if emit:
            self.picked.emit(color)

    def current(self) -> str:
        return self._current
