"""Visualizações do Auto-Tune: afinador (nota cantada x nota-alvo) e gráfico de afinação."""
from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from autotune.music import NOTE_NAMES, note_name
from ui import theme


class TunerDisplay(QWidget):
    """Mostra a nota detectada, a nota-alvo e o desvio em cents."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(116)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detected: float | None = None
        self.target: float | None = None
        self.output: float | None = None
        self.chord = ""

    def set_values(self, detected, target, output, chord: str = "") -> None:
        self.detected, self.target, self.output, self.chord = detected, target, output, chord
        self.update()

    def paintEvent(self, _e) -> None:
        p = theme.current()
        g = QPainter(self)
        g.setRenderHint(QPainter.Antialiasing)
        w = self.width()

        def block(x, title, value, color):
            g.setPen(QColor(p.text_faint))
            f = QFont(self.font())
            f.setPixelSize(11)
            g.setFont(f)
            g.drawText(QRectF(x, 4, w / 3, 16), Qt.AlignHCenter, title)
            f.setPixelSize(34)
            f.setWeight(QFont.Bold)
            g.setFont(f)
            g.setPen(QColor(color))
            g.drawText(QRectF(x, 20, w / 3, 44), Qt.AlignHCenter | Qt.AlignVCenter, value)

        block(0, "VOCÊ CANTA", note_name(self.detected), p.text if self.detected is not None else p.text_faint)
        block(w / 3, "CORRIGINDO PARA", note_name(self.target), p.accent if self.target is not None else p.text_faint)
        block(2 * w / 3, "ACORDE" if self.chord else "SAÍDA",
              self.chord or note_name(self.output), "#22C55E" if (self.chord or self.output is not None) else p.text_faint)

        # barra de cents: desvio da voz em relação à nota-alvo
        bar = QRectF(24, 76, w - 48, 10)
        g.setPen(Qt.NoPen)
        g.setBrush(QColor(p.surface3))
        g.drawRoundedRect(bar, 5, 5)
        g.setBrush(QColor(p.text_faint))
        g.drawRect(QRectF(bar.center().x() - 1, bar.top() - 4, 2, bar.height() + 8))
        small = QFont(self.font())
        small.setPixelSize(11)
        g.setFont(small)
        if self.detected is not None and self.target is not None:
            cents = max(-100.0, min(100.0, (self.detected - self.target) * 100))
            x = bar.center().x() + cents / 100 * bar.width() / 2
            col = "#22C55E" if abs(cents) < 10 else ("#F59E0B" if abs(cents) < 30 else "#EF4444")
            g.setBrush(QColor(col))
            g.drawEllipse(QPointF(x, bar.center().y()), 8, 8)
            g.setPen(QColor(p.text_dim))
            g.drawText(QRectF(0, 92, w, 18), Qt.AlignHCenter, f"{cents:+.0f} cents antes da correção")
        else:
            g.setPen(QColor(p.text_faint))
            g.drawText(QRectF(0, 92, w, 18), Qt.AlignHCenter, "Cante para ver a afinação")


class PitchGraph(QWidget):
    """Histórico de afinação: voz original (cinza) x saída corrigida (destaque), com linhas das notas permitidas."""

    WINDOW_S = 6.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.points: deque[tuple[float, float | None, float | None]] = deque()
        self.allowed: frozenset[int] = frozenset(range(12))

    def add(self, detected: float | None, output: float | None, allowed) -> None:
        now = time.monotonic()
        self.points.append((now, detected, output))
        while self.points and now - self.points[0][0] > self.WINDOW_S:
            self.points.popleft()
        if allowed:
            self.allowed = allowed
        self.update()

    def paintEvent(self, _e) -> None:
        p = theme.current()
        g = QPainter(self)
        g.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(34, 6, -6, -6)
        g.fillRect(QRectF(self.rect()), QColor(p.surface2))
        vals = [v for _, d, o in self.points for v in (d, o) if v is not None]
        center = (sorted(vals)[len(vals) // 2] if vals else 60.0)
        lo, hi = center - 7, center + 7

        def y_of(m):
            return r.bottom() - (m - lo) / (hi - lo) * r.height()

        f = QFont(self.font())
        f.setPixelSize(10)
        g.setFont(f)
        row_h = r.height() / (hi - lo)
        label_every = max(1, int(-(-13 // max(row_h, 1))))
        for m in range(int(lo), int(hi) + 1):
            pc = m % 12
            allowed = pc in self.allowed
            g.setPen(QPen(QColor(p.accent if allowed else p.border), 1, Qt.SolidLine if allowed else Qt.DotLine))
            if allowed:
                c = QColor(p.accent)
                c.setAlpha(70)
                g.setPen(QPen(c, 1))
            y = y_of(m)
            g.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            if m % label_every == 0:
                g.setPen(QColor(p.text_dim if allowed else p.text_faint))
                g.drawText(QRectF(0, y - 7, 30, 14), Qt.AlignRight | Qt.AlignVCenter, NOTE_NAMES[pc] + str(m // 12 - 1))

        now = time.monotonic()

        def x_of(t):
            return r.right() - (now - t) / self.WINDOW_S * r.width()

        for idx, color, width in ((1, p.text_faint, 1.6), (2, p.accent, 2.4)):
            path = QPainterPath()
            started = False
            for pt in self.points:
                v = pt[idx]
                if v is None or not (lo - 2 < v < hi + 2):
                    started = False
                    continue
                q = QPointF(x_of(pt[0]), y_of(v))
                if started:
                    path.lineTo(q)
                else:
                    path.moveTo(q)
                    started = True
            g.setPen(QPen(QColor(color), width))
            g.setBrush(Qt.NoBrush)
            g.drawPath(path)
        g.setPen(QColor(p.text_faint))
        g.drawText(QRectF(r.left() + 6, r.top(), 300, 14), Qt.AlignLeft,
                   "— voz original    — saída corrigida    ▬ notas permitidas")
