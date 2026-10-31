"""Janela sem a barra de título do Windows, mantendo o comportamento nativo.

A barra padrão é removida tratando WM_NCCALCSIZE (a área cliente ocupa a janela toda), mas os
estilos WS_CAPTION/WS_THICKFRAME continuam ativos: o Windows segue cuidando de sombra, cantos
arredondados (Win 11), animações, Aero Snap, arrastar pela barra e redimensionar pelas bordas.
O WM_NCHITTEST diz ao Windows quais regiões são "barra de título" e quais são bordas.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QAbstractButton, QWidget

IS_WINDOWS = sys.platform == "win32"

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
SWP_FRAMECHANGED, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x20, 0x2, 0x1, 0x4, 0x10
SM_CXFRAME, SM_CYFRAME, SM_CXPADDEDBORDER = 32, 33, 92
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2

RESIZE_BORDER = 6  # px lógicos sensíveis ao redimensionamento


class _MARGINS(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int)]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _dwm = ctypes.WinDLL("dwmapi")
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.IsZoomed.argtypes = [wintypes.HWND]
    _user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    _user32.GetDpiForWindow.restype = wintypes.UINT
    _user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
    _dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(_MARGINS)]
    _dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


class FramelessHelper:
    """Liga o comportamento nativo a uma janela Qt criada com Qt.FramelessWindowHint.

    ``drag_areas``: widgets cuja área livre funciona como barra de título (arrastar, duplo clique
    maximiza, Aero Snap). Botões e widgets em ``no_drag`` dentro deles continuam clicáveis.
    """

    def __init__(self, window: QWidget):
        self.window = window
        self.drag_areas: list[QWidget] = []
        self.no_drag: list[QWidget] = []

    # ------------------------------------------------------------ instalação
    def apply(self) -> None:
        """Reaplica estilos/DWM; chamar após a janela ganhar HWND (showEvent)."""
        if not IS_WINDOWS:
            return
        hwnd = int(self.window.winId())
        style = _user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        wanted = style | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
        if wanted != style:
            _user32.SetWindowLongPtrW(hwnd, GWL_STYLE, wanted)
        # 1 px de "vidro" basta para o DWM desenhar a sombra da janela.
        margins = _MARGINS(1, 1, 1, 1)
        _dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        pref = ctypes.c_int(DWMWCP_ROUND)
        _dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref))
        _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                             SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    # ------------------------------------------------------------ mensagens nativas
    def native_event(self, event_type, message) -> tuple[bool, int] | None:
        if not IS_WINDOWS or event_type != b"windows_generic_MSG":
            return None
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_NCCALCSIZE and msg.wParam:
            if _user32.IsZoomed(msg.hWnd):
                # Maximizada, a janela passa das bordas do monitor pela espessura da moldura.
                dpi = _user32.GetDpiForWindow(msg.hWnd) or 96
                fx = _user32.GetSystemMetricsForDpi(SM_CXFRAME, dpi) + _user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi)
                fy = _user32.GetSystemMetricsForDpi(SM_CYFRAME, dpi) + _user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi)
                params = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
                r = params.rgrc[0]
                r.left += fx
                r.right -= fx
                r.top += fy
                r.bottom -= fy
            return True, 0
        if msg.message == WM_NCHITTEST:
            return True, self._hit_test(msg)
        return None

    def _hit_test(self, msg) -> int:
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        rect = wintypes.RECT()
        _user32.GetWindowRect(msg.hWnd, ctypes.byref(rect))
        dpr = self.window.devicePixelRatioF() or 1.0
        pos = QPoint(int((x - rect.left) / dpr), int((y - rect.top) / dpr))
        w, h = self.window.width(), self.window.height()

        if not _user32.IsZoomed(msg.hWnd):
            b = RESIZE_BORDER
            left, right = pos.x() < b, pos.x() >= w - b
            top, bottom = pos.y() < b, pos.y() >= h - b
            if top and left:
                return HTTOPLEFT
            if top and right:
                return HTTOPRIGHT
            if bottom and left:
                return HTBOTTOMLEFT
            if bottom and right:
                return HTBOTTOMRIGHT
            if left:
                return HTLEFT
            if right:
                return HTRIGHT
            if top:
                return HTTOP
            if bottom:
                return HTBOTTOM
        return HTCAPTION if self._is_drag_point(pos) else HTCLIENT

    def _is_drag_point(self, pos: QPoint) -> bool:
        child = self.window.childAt(pos)
        while child is not None and child is not self.window:
            if isinstance(child, QAbstractButton) or child in self.no_drag:
                return False
            if child in self.drag_areas:
                return True
            child = child.parentWidget()
        return False
