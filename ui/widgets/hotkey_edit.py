"""Campo de captura de atalho: clique, pressione a combinação. Esc cancela, Backspace limpa."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from hotkeys.keymap import MODIFIER_VKS, MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, format_hotkey
from ui.widgets.common import tool_button


class HotkeyEdit(QWidget):
    #: emitido com o novo atalho (ou None ao limpar)
    hotkeyChanged = Signal(object)
    #: chamado com True/False ao iniciar/terminar a captura (o app suspende os atalhos globais,
    #: senão a combinação seria consumida pelo Windows antes de chegar aqui)
    capture_hook = None

    def __init__(self, hotkey: str | None = None, parent=None):
        super().__init__(parent)
        self._hotkey = hotkey
        self._capturing = False
        self.button = QPushButton()
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setMinimumWidth(150)
        self.button.setFocusPolicy(Qt.StrongFocus)
        self.button.clicked.connect(self._start_capture)
        self.button.installEventFilter(self)
        self.clear_btn = tool_button("x", "Remover atalho", 14)
        self.clear_btn.clicked.connect(self.clear)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.button, 1)
        lay.addWidget(self.clear_btn)
        self._refresh()

    def hotkey(self) -> str | None:
        return self._hotkey

    def setHotkey(self, hotkey: str | None) -> None:
        self._hotkey = hotkey
        self._capturing = False
        self._refresh()

    def clear(self) -> None:
        changed = self._hotkey is not None
        self.setHotkey(None)
        if changed:
            self.hotkeyChanged.emit(None)

    def _refresh(self) -> None:
        if self._capturing:
            self.button.setText("Pressione as teclas…")
        else:
            self.button.setText(self._hotkey or "Nenhum")
        self.clear_btn.setVisible(bool(self._hotkey) and not self._capturing)

    def _start_capture(self) -> None:
        self._capturing = True
        if HotkeyEdit.capture_hook:
            HotkeyEdit.capture_hook(True)
        self._refresh()
        self.button.setFocus()
        self.button.grabKeyboard()

    def _stop_capture(self) -> None:
        was = self._capturing
        self._capturing = False
        self.button.releaseKeyboard()
        if was and HotkeyEdit.capture_hook:
            HotkeyEdit.capture_hook(False)
        self._refresh()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.button and self._capturing:
            et = event.type()
            if et == event.Type.KeyPress:
                self._handle_key(event)
                return True
            if et == event.Type.FocusOut:
                self._stop_capture()
        return super().eventFilter(obj, event)

    def _handle_key(self, event) -> None:
        vk = event.nativeVirtualKey()
        key = event.key()
        mods_qt = event.modifiers()
        if key == Qt.Key_Escape and not mods_qt:
            self._stop_capture()
            return
        if key == Qt.Key_Backspace and not mods_qt:
            self._stop_capture()
            self.clear()
            return
        if vk in MODIFIER_VKS or vk == 0:
            return  # aguardando a tecla principal
        mods = 0
        if mods_qt & Qt.ControlModifier:
            mods |= MOD_CONTROL
        if mods_qt & Qt.AltModifier:
            mods |= MOD_ALT
        if mods_qt & Qt.ShiftModifier:
            mods |= MOD_SHIFT
        if mods_qt & Qt.MetaModifier:
            mods |= MOD_WIN
        text = format_hotkey(mods, vk)
        if text is None:
            return
        self._hotkey = text
        self._stop_capture()
        self.hotkeyChanged.emit(text)
