"""Layout em fluxo: distribui itens em linhas, quebrando conforme a largura disponível."""
from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 12, stretch_items: bool = True):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.stretch_items = stretch_items  # distribui sobra de largura entre os itens da linha
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m: QMargins = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        sp = self._spacing
        items = [i for i in self._items if not (i.widget() and i.widget().isHidden())]
        if not items:
            return m.top() + m.bottom()

        # agrupa em linhas
        rows, row, row_w = [], [], 0
        for item in items:
            w = item.sizeHint().width()
            if row and row_w + sp + w > area.width():
                rows.append(row)
                row, row_w = [], 0
            row_w += (sp if row else 0) + w
            row.append(item)
        if row:
            rows.append(row)

        # largura uniforme: usa o nº de colunas da primeira linha para todas
        cols = len(rows[0])
        base_w = items[0].sizeHint().width()
        if self.stretch_items and cols > 0:
            item_w = max(base_w, (area.width() - sp * (cols - 1)) // cols)
            item_w = min(item_w, int(base_w * 1.35))
        else:
            item_w = base_w

        y = area.y()
        for row in rows:
            x = area.x()
            row_h = max(i.sizeHint().height() for i in row)
            for item in row:
                if not test:
                    item.setGeometry(QRect(QPoint(x, y), QSize(item_w, row_h)))
                x += item_w + sp
            y += row_h + sp
        return y - sp - rect.y() + m.bottom()
