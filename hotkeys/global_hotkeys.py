"""Atalhos globais do Windows via RegisterHotKey (funcionam com o app minimizado/em segundo plano).

Uma thread dedicada registra os atalhos e roda o laço de mensagens Win32; os pedidos
de registro chegam por fila e são processados nessa mesma thread (exigência da API).
"""
from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
from ctypes import wintypes
from typing import Callable

from hotkeys.keymap import MOD_NOREPEAT, parse_hotkey

log = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_WAKE = 0x8000 + 1

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                     wintypes.UINT, wintypes.UINT]


class GlobalHotkeyManager:
    def __init__(self, on_trigger: Callable[[str], None]):
        self.on_trigger = on_trigger
        self._requests: queue.Queue = queue.Queue()
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._ids: dict[str, int] = {}        # ação -> id
        self._actions: dict[int, str] = {}    # id -> ação
        self._hotkeys: dict[str, str] = {}    # ação -> texto
        self._next_id = 1
        self._thread: threading.Thread | None = None
        self.available = sys.platform == "win32"

    def start(self) -> None:
        if not self.available or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="global-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)

    def stop(self) -> None:
        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None

    # ----------------------------------------------------------- API (qualquer thread)
    def register(self, action: str, hotkey: str | None) -> tuple[bool, str]:
        """Registra (ou substitui) o atalho de uma ação. Retorna (ok, mensagem de erro)."""
        if not self.available:
            return False, "Atalhos globais só são suportados no Windows."
        if not hotkey:
            self.unregister(action)
            return True, ""
        return self._call("register", action, hotkey)

    def unregister(self, action: str) -> None:
        if self.available and self._thread_id is not None:
            self._call("unregister", action, None)

    def unregister_all(self) -> None:
        for action in list(self._ids):
            self.unregister(action)

    def registered(self) -> dict[str, str]:
        return dict(self._hotkeys)

    def _call(self, op: str, action: str, hotkey: str | None) -> tuple[bool, str]:
        if self._thread_id is None:
            return False, "Serviço de atalhos não iniciado."
        reply: queue.Queue = queue.Queue(maxsize=1)
        self._requests.put((op, action, hotkey, reply))
        _user32.PostThreadMessageW(self._thread_id, WM_APP_WAKE, 0, 0)
        try:
            return reply.get(timeout=2.0)
        except queue.Empty:
            return False, "Tempo esgotado ao registrar o atalho."

    # ----------------------------------------------------------- thread Win32
    def _run(self) -> None:
        user32 = _user32
        kernel32 = _kernel32
        msg = wintypes.MSG()
        # Força a criação da fila de mensagens desta thread.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == WM_HOTKEY:
                action = self._actions.get(int(msg.wParam))
                if action:
                    try:
                        self.on_trigger(action)
                    except Exception:  # noqa: BLE001
                        log.exception("Erro ao executar atalho %s", action)
            elif msg.message == WM_APP_WAKE:
                self._process_requests()
        for hid in list(self._actions):
            user32.UnregisterHotKey(None, hid)
        self._actions.clear()
        self._ids.clear()

    def _process_requests(self) -> None:
        user32 = _user32
        while True:
            try:
                op, action, hotkey, reply = self._requests.get_nowait()
            except queue.Empty:
                return
            old = self._ids.pop(action, None)
            if old is not None:
                user32.UnregisterHotKey(None, old)
                self._actions.pop(old, None)
                self._hotkeys.pop(action, None)
            if op == "unregister":
                reply.put((True, ""))
                continue
            parsed = parse_hotkey(hotkey)
            if parsed is None:
                reply.put((False, f"Atalho inválido: {hotkey}"))
                continue
            mods, vk = parsed
            hid = self._next_id
            self._next_id += 1
            if user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                self._ids[action] = hid
                self._actions[hid] = action
                self._hotkeys[action] = hotkey
                reply.put((True, ""))
            else:
                err = ctypes.get_last_error()
                if err == 1409:  # ERROR_HOTKEY_ALREADY_REGISTERED
                    reply.put((False, f"'{hotkey}' já está em uso por outro programa."))
                else:
                    reply.put((False, f"Não foi possível registrar '{hotkey}' (erro {err})."))
