"""Botões da janela (bandeja, minimizar, maximizar/restaurar, fechar) no estilo do app."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QWidget

from ui import icons, theme


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


class TitleButton(QAbstractButton):
    """Botão quadrado com fundo arredondado que aparece suavemente no hover."""

    def __init__(self, icon_name: str, tooltip: str, danger: bool = False, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.danger = danger
        self._hover = 0.0
        self.setToolTip(tooltip)
        self.setFixedSize(38, 34)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.ArrowCursor)
        self._anim = QPropertyAnimation(self, b"hover", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def sizeHint(self) -> QSize:
        return QSize(38, 34)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, v: float) -> None:
        self._hover = v
        self.update()

    hover = Property(float, _get_hover, _set_hover)

    def set_icon_name(self, name: str) -> None:
        self.icon_name = name
        self.update()

    def _fade(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, e) -> None:
        self._fade(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._fade(0.0)
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        t = self._hover
        if self.danger:
            bg = QColor("#E5484D")
            bg.setAlphaF((0.85 if self.isDown() else 1.0) * t)
            fg = _mix(QColor(p.text_dim), QColor("#FFFFFF"), t)
        else:
            bg = QColor(p.surface3 if self.isDown() else p.surface2)
            bg.setAlphaF(t)
            fg = _mix(QColor(p.text_dim), QColor(p.text), t)
        if t > 0.0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        size = 16
        pm = icons.pixmap(self.icon_name, fg.name(), size)
        painter.drawPixmap((self.width() - size) // 2, (self.height() - size) // 2, pm)


class WindowControls(QWidget):
    """Linha de botões; a janela conecta os sinais ao que cada um deve fazer."""

    to_tray = Signal()
    minimize = Signal()
    toggle_maximize = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        self.btn_tray = TitleButton("win-tray", "Enviar para a bandeja do sistema")
        self.btn_min = TitleButton("win-min", "Minimizar")
        self.btn_max = TitleButton("win-max", "Maximizar")
        self.btn_close = TitleButton("x", "Fechar", danger=True)
        self.btn_tray.clicked.connect(self.to_tray)
        self.btn_min.clicked.connect(self.minimize)
        self.btn_max.clicked.connect(self.toggle_maximize)
        self.btn_close.clicked.connect(self.close_clicked)
        for b in (self.btn_tray, self.btn_min, self.btn_max, self.btn_close):
            h.addWidget(b)

    def set_maximized(self, maximized: bool) -> None:
        self.btn_max.set_icon_name("win-restore" if maximized else "win-max")
        self.btn_max.setToolTip("Restaurar" if maximized else "Maximizar")
