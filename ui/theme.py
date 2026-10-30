"""Temas (escuro/claro) e folha de estilos Qt."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor

from ui import icons
from utils.paths import app_data_dir

ACCENTS = {
    "Violeta": "#8B5CF6",
    "Azul": "#3B82F6",
    "Ciano": "#06B6D4",
    "Verde": "#10B981",
    "Rosa": "#EC4899",
    "Laranja": "#F97316",
}


@dataclass
class Palette:
    name: str
    bg: str
    sidebar: str
    surface: str
    surface2: str
    surface3: str
    border: str
    text: str
    text_dim: str
    text_faint: str
    accent: str = "#8B5CF6"
    danger: str = "#EF4444"
    success: str = "#22C55E"
    warning: str = "#F59E0B"

    @property
    def accent_hover(self) -> str:
        return QColor(self.accent).lighter(115).name()

    @property
    def accent_soft(self) -> str:
        c = QColor(self.accent)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, 0.16)"


DARK = Palette(
    name="dark", bg="#0E1016", sidebar="#0A0C11", surface="#151821", surface2="#1C2030",
    surface3="#252A3D", border="#262B3B", text="#E7E9F1", text_dim="#9096AB", text_faint="#5E6479",
)
LIGHT = Palette(
    name="light", bg="#F3F4F8", sidebar="#E9EBF2", surface="#FFFFFF", surface2="#F0F2F7",
    surface3="#E3E6EE", border="#DADEE8", text="#141720", text_dim="#596075", text_faint="#9298AA",
)

_current: Palette = DARK


def current() -> Palette:
    return _current


def set_theme(name: str, accent: str) -> Palette:
    global _current
    base = LIGHT if name == "light" else DARK
    _current = Palette(**{**base.__dict__, "accent": accent})
    return _current


def _asset_paths(p: Palette) -> dict[str, str]:
    folder = app_data_dir() / "cache" / "qss"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {
        "down": icons.write_svg(folder / f"down_{p.name}.svg", "chevron-down", p.text_dim),
        "up": icons.write_svg(folder / f"up_{p.name}.svg", "chevron-up", p.text_dim),
        "check": icons.write_svg(folder / f"check_{p.accent[1:]}.svg", "check", "#FFFFFF"),
    }
    return {k: str(v).replace("\\", "/") for k, v in paths.items()}


def stylesheet(p: Palette) -> str:
    a = _asset_paths(p)
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; color: {p.text}; outline: none; }}
QMainWindow, QDialog, #Root {{ background: {p.bg}; }}
QWidget#Page {{ background: {p.bg}; }}
QToolTip {{ background: {p.surface3}; color: {p.text}; border: 1px solid {p.border}; padding: 6px 8px; border-radius: 6px; }}

/* ---------- Sidebar ---------- */
#Sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}
#Brand {{ font-size: 13pt; font-weight: 700; }}
#BrandSub {{ color: {p.text_faint}; font-size: 8.5pt; }}
QPushButton#NavButton {{
    text-align: left; padding: 10px 14px; border-radius: 10px; border: none;
    background: transparent; color: {p.text_dim}; font-weight: 600;
}}
QPushButton#NavButton:hover {{ background: {p.surface}; color: {p.text}; }}
QPushButton#NavButton:checked {{ background: {p.accent_soft}; color: {p.text}; }}

/* ---------- Superfícies ---------- */
#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
#CardInner {{ background: {p.surface2}; border-radius: 10px; }}
#TopBar {{ background: {p.bg}; border-bottom: 1px solid {p.border}; }}
#Chip {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 13px; padding: 4px 10px; color: {p.text_dim}; }}
#Banner {{ background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.45); border-radius: 12px; }}
#BannerError {{ background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.45); border-radius: 12px; }}
QLabel#H1 {{ font-size: 17pt; font-weight: 700; }}
QLabel#H2 {{ font-size: 12pt; font-weight: 700; }}
QLabel#H3 {{ font-size: 10.5pt; font-weight: 700; }}
QLabel#Dim {{ color: {p.text_dim}; }}
QLabel#Faint {{ color: {p.text_faint}; font-size: 9pt; }}
QLabel#Badge {{ background: {p.accent_soft}; color: {p.accent_hover}; border-radius: 8px; padding: 2px 8px; font-size: 8.5pt; font-weight: 700; }}
QLabel#Value {{ color: {p.text_dim}; font-family: "Cascadia Mono", Consolas, monospace; font-size: 9pt; }}

/* ---------- Botões ---------- */
QPushButton {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px;
    padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {p.surface3}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:disabled {{ color: {p.text_faint}; background: {p.surface}; }}
QPushButton[accent="true"] {{ background: {p.accent}; border-color: {p.accent}; color: white; }}
QPushButton[accent="true"]:hover {{ background: {p.accent_hover}; }}
QPushButton[accent="true"]:disabled {{ background: {p.surface2}; border-color: {p.border}; color: {p.text_faint}; }}
QPushButton[danger="true"] {{ background: rgba(239,68,68,0.14); border-color: rgba(239,68,68,0.5); color: #F87171; }}
QPushButton[danger="true"]:hover {{ background: rgba(239,68,68,0.24); }}
QPushButton[flat="true"] {{ background: transparent; border: none; padding: 6px; }}
QPushButton[flat="true"]:hover {{ background: {p.surface2}; }}
QPushButton#BigToggle {{ border-radius: 12px; padding: 10px 16px; text-align: left; }}
QPushButton#BigToggle:checked {{ background: {p.accent_soft}; border-color: {p.accent}; }}
QPushButton#MuteButton:checked {{ background: rgba(239,68,68,0.18); border-color: {p.danger}; color: #F87171; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 5px; }}
QToolButton:hover {{ background: {p.surface2}; }}
QToolButton:checked {{ background: {p.accent_soft}; }}

/* ---------- Entradas ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QKeySequenceEdit {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px; padding: 6px 10px;
    selection-background-color: {p.accent};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {p.accent}; }}
QLineEdit#Search {{ padding-left: 32px; border-radius: 10px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({a['down']}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px;
    selection-background-color: {p.accent_soft}; selection-color: {p.text};
}}
QLineEdit#ValueBox {{
    background: transparent; border: 1px solid transparent; padding: 1px 4px; border-radius: 6px;
    font-family: "Cascadia Mono", Consolas, monospace; font-size: 9pt; color: {p.text_dim};
}}
QLineEdit#ValueBox:hover, QLineEdit#ValueBox:focus {{ border-color: {p.border}; background: {p.surface2}; color: {p.text}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; }}
QAbstractSpinBox QLineEdit {{ padding: 0; margin: 0; border: none; background: transparent; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {p.border}; background: {p.surface2}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: url({a['check']}); }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 8px; border: 1px solid {p.border}; background: {p.surface2}; }}
QRadioButton::indicator:checked {{ background: {p.accent}; border: 4px solid {p.surface2}; }}

/* ---------- Sliders ---------- */
QSlider:horizontal {{ min-height: 20px; background: transparent; }}
QSlider:vertical {{ min-width: 30px; background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: {p.surface3}; border: none; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border: none; border-radius: 2px; }}
QSlider::add-page:horizontal {{ background: {p.surface3}; border: none; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: #FFFFFF; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; border: 2px solid {p.accent};
}}
QSlider::handle:horizontal:hover {{ background: {p.accent_hover}; }}
QSlider::groove:vertical {{ width: 6px; background: {p.surface3}; border: none; border-radius: 3px; }}
QSlider::add-page:vertical {{ background: {p.accent}; border: none; border-radius: 3px; }}
QSlider::sub-page:vertical {{ background: {p.surface3}; border: none; border-radius: 3px; }}
QSlider::handle:vertical {{
    background: #FFFFFF; height: 18px; width: 30px; margin: 0 -12px; border-radius: 6px; border: 2px solid {p.accent};
}}

/* ---------- Listas / menus / scroll ---------- */
QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 9px; color: {p.text_dim}; margin: 1px 0; }}
QListWidget::item:hover {{ background: {p.surface}; color: {p.text}; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QMenu {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.accent_soft}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.surface3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.surface3}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {p.text_dim}; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom-color: {p.accent}; }}
QMessageBox QLabel {{ color: {p.text}; }}
QProgressBar {{ background: {p.surface3}; border: none; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}
"""
