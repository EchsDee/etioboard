"""Gera assets/icons/app.ico a partir do ícone vetorial do app (usado pelo PyInstaller)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

app = QGuiApplication([])
from ui.icons import app_icon_svg  # noqa: E402

out = ROOT / "assets" / "icons" / "app.ico"
out.parent.mkdir(parents=True, exist_ok=True)
renderer = QSvgRenderer(QByteArray(app_icon_svg().encode()))
img = QImage(256, 256, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
renderer.render(p, QRectF(0, 0, 256, 256))
p.end()
if not img.save(str(out), "ICO"):
    raise SystemExit("Falha ao gerar o ícone")
print(f"Ícone gerado: {out}")
