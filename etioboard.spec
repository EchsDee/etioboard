# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller etioboard.spec --noconfirm
# Saída:  dist/etioboard/etioboard.exe  (modo "onedir": inicia rápido, ideal para áudio)

block_cipher = None

EXCLUDES = [
    "tkinter", "matplotlib", "IPython", "pytest", "PIL", "pandas",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtBluetooth",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtQuickWidgets", "PySide6.QtLocation",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=["PySide6.QtSvg", "PySide6.QtNetwork"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="etioboard",
    icon="assets/icons/app.ico",
    console=False,
    debug=False,
    strip=False,
    upx=False,
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="etioboard",
)
