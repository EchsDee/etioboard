"""Botão do soundboard: cor, ícone, nome, atalho, favorito e indicador de reprodução.

Suporta arrastar e soltar (reordenar ou mover para outra categoria).
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QDrag, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from soundboard.library import Snippet
from ui import icons, theme

MIME_SNIPPET = "application/x-etioboard-snippet"


class SnippetButton(QWidget):
    clicked = Signal(int)
    context_requested = Signal(int, QPoint)
    dropped_on = Signal(int, int)  # (snippet arrastado, snippet alvo)

    def __init__(self, snippet: Snippet, size: int = 120, parent=None):
        super().__init__(parent)
        self.snippet = snippet
        self._size = size
        self._hover = False
        self._pressed = False
        self._drop_hint = False
        self._progress: float | None = None
        self._preview = False
        self._press_pos: QPoint | None = None
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setMinimumSize(self.sizeHint())
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        s = self.snippet
        lines = [f"<b>{s.name}</b>", f"Duração: {s.duration:.1f}s"]
        if s.hotkey:
            lines.append(f"Atalho: {s.hotkey}")
        if not s.exists:
            lines.append("<span style='color:#F87171'>Arquivo não encontrado</span>")
        lines.append("<i>Clique para tocar • botão direito para opções</i>")
        self.setToolTip("<br>".join(lines))

    def set_snippet(self, snippet: Snippet) -> None:
        self.snippet = snippet
        self._update_tooltip()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(int(self._size * 1.15), self._size)

    def set_progress(self, progress: float | None, preview: bool = False) -> None:
        if progress != self._progress or preview != self._preview:
            self._progress = progress
            self._preview = preview
            self.update()

    # ------------------------------------------------------------- pintura
    def paintEvent(self, _event) -> None:
        p = theme.current()
        s = self.snippet
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self._pressed:
            r = r.adjusted(2, 2, -2, -2)
        radius = 14.0

        base = QColor(s.color)
        bg = QColor(base)
        if p.name == "dark":
            bg = bg.darker(135) if not self._hover else bg.darker(115)
        else:
            bg = bg.lighter(150) if not self._hover else bg.lighter(135)
        playing = self._progress is not None

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        painter.fillPath(path, bg)

        # brilho superior sutil
        glow = QLinearGradient(r.topLeft(), r.bottomLeft())
        glow.setColorAt(0.0, QColor(255, 255, 255, 34 if p.name == "dark" else 60))
        glow.setColorAt(0.6, QColor(255, 255, 255, 0))
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(r, glow)

        # barra de progresso
        if playing:
            prog_color = QColor(p.accent if not self._preview else "#06B6D4")
            prog_color.setAlpha(70)
            painter.fillRect(QRectF(r.left(), r.top(), r.width() * self._progress, r.height()), prog_color)
            bar = QColor(p.accent if not self._preview else "#06B6D4")
            painter.fillRect(QRectF(r.left(), r.bottom() - 4, r.width() * self._progress, 4), bar)
        painter.restore()

        # borda
        if playing:
            pen = QPen(QColor(p.accent if not self._preview else "#06B6D4"), 2.0)
        elif self._drop_hint:
            pen = QPen(QColor(p.accent), 2.0, Qt.DashLine)
        elif self._hover:
            pen = QPen(base.lighter(140), 1.4)
        else:
            pen = QPen(QColor(255, 255, 255, 22) if p.name == "dark" else base.darker(110), 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        text_color = QColor("#FFFFFF") if p.name == "dark" else QColor("#111318")

        # ícone (emoji)
        emoji_font = QFont("Segoe UI Emoji")
        emoji_font.setPixelSize(int(self._size * 0.27))
        painter.setFont(emoji_font)
        painter.setPen(text_color)
        icon_rect = QRectF(r.left(), r.top() + r.height() * 0.12, r.width(), r.height() * 0.40)
        painter.drawText(icon_rect, Qt.AlignCenter, s.icon or "🔊")

        # nome
        name_font = QFont(self.font())
        name_font.setPixelSize(max(11, int(self._size * 0.105)))
        name_font.setWeight(QFont.DemiBold)
        painter.setFont(name_font)
        fm = QFontMetrics(name_font)
        text_rect = QRectF(r.left() + 8, r.top() + r.height() * 0.56, r.width() - 16, r.height() * 0.24)
        name = fm.elidedText(s.name, Qt.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, name)

        # rodapé: atalho / loop
        small = QFont(self.font())
        small.setPixelSize(max(9, int(self._size * 0.083)))
        painter.setFont(small)
        dim = QColor(text_color)
        dim.setAlpha(160)
        painter.setPen(dim)
        footer = QRectF(r.left() + 8, r.bottom() - r.height() * 0.21, r.width() - 16, r.height() * 0.15)
        if s.hotkey:
            hk = QFontMetrics(small).elidedText(s.hotkey, Qt.ElideRight, int(footer.width() - 18))
            painter.drawText(footer, Qt.AlignLeft | Qt.AlignVCenter, "⌨ " + hk)
        if s.loop:
            painter.drawPixmap(int(footer.right() - 14), int(footer.center().y() - 7),
                               icons.pixmap("repeat", dim.name(), 14))

        # favorito
        if s.favorite:
            painter.drawPixmap(int(r.right() - 22), int(r.top() + 8), icons.pixmap("star", "#FBBF24", 14, filled=True))
        # arquivo ausente
        if not s.exists:
            painter.drawPixmap(int(r.left() + 8), int(r.top() + 8), icons.pixmap("alert", "#F87171", 14))

    # ------------------------------------------------------------- mouse / drag
    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._pressed = True
            self._press_pos = e.position().toPoint()
            self.update()
        elif e.button() == Qt.RightButton:
            self.context_requested.emit(self.snippet.id, e.globalPosition().toPoint())

    def mouseMoveEvent(self, e) -> None:
        if not (e.buttons() & Qt.LeftButton) or self._press_pos is None:
            return
        if (e.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._pressed = False
        self.update()
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_SNIPPET, str(self.snippet.id).encode())
        drag.setMimeData(mime)
        pm = QPixmap(self.size() * self.devicePixelRatioF())
        pm.setDevicePixelRatio(self.devicePixelRatioF())
        pm.fill(Qt.transparent)
        self.render(pm)
        faded = QPixmap(pm.size())
        faded.setDevicePixelRatio(pm.devicePixelRatio())
        faded.fill(Qt.transparent)
        pp = QPainter(faded)
        pp.setOpacity(0.75)
        pp.drawPixmap(0, 0, pm)
        pp.end()
        drag.setPixmap(faded)
        drag.setHotSpot(self._press_pos)
        self._press_pos = None
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            self.update()
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit(self.snippet.id)
        self._press_pos = None

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasFormat(MIME_SNIPPET):
            sid = int(bytes(e.mimeData().data(MIME_SNIPPET)).decode())
            if sid != self.snippet.id:
                self._drop_hint = True
                self.update()
                e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        self._drop_hint = False
        self.update()

    def dropEvent(self, e) -> None:
        self._drop_hint = False
        self.update()
        if e.mimeData().hasFormat(MIME_SNIPPET):
            sid = int(bytes(e.mimeData().data(MIME_SNIPPET)).decode())
            if sid != self.snippet.id:
                self.dropped_on.emit(sid, self.snippet.id)
                e.acceptProposedAction()
