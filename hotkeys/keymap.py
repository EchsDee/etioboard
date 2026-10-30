"""Conversão entre teclas (códigos virtuais do Windows) e texto legível, ex.: "Ctrl+Shift+F1"."""
from __future__ import annotations

import ctypes
import sys

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

MODIFIER_NAMES = [("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT), ("Win", MOD_WIN)]

# Teclas modificadoras (ignoradas como tecla principal)
MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}

_NAMED: dict[int, str] = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "CapsLock",
    0x1B: "Esc", 0x20: "Space", 0x21: "PageUp", 0x22: "PageDown", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2C: "PrintScreen", 0x2D: "Insert",
    0x2E: "Delete", 0x6A: "Num*", 0x6B: "Num+", 0x6D: "Num-", 0x6E: "Num.", 0x6F: "Num/",
    0x90: "NumLock", 0x91: "ScrollLock",
    0xAD: "VolumeMute", 0xAE: "VolumeDown", 0xAF: "VolumeUp",
    0xB0: "MediaNext", 0xB1: "MediaPrev", 0xB2: "MediaStop", 0xB3: "MediaPlay",
}
for _i in range(26):
    _NAMED[0x41 + _i] = chr(ord("A") + _i)
for _i in range(10):
    _NAMED[0x30 + _i] = str(_i)
    _NAMED[0x60 + _i] = f"Num{_i}"
for _i in range(24):
    _NAMED[0x70 + _i] = f"F{_i + 1}"

_BY_NAME = {v.lower(): k for k, v in _NAMED.items()}

# Teclas de pontuação (OEM) dependem do layout; usamos o caractere produzido.
_OEM_VKS = list(range(0xBA, 0xC1)) + list(range(0xDB, 0xE0)) + [0xE2, 0xC1, 0xC2]


def _oem_char(vk: int) -> str | None:
    if sys.platform != "win32":
        return None
    ch = ctypes.windll.user32.MapVirtualKeyW(vk, 2) & 0xFFFF  # MAPVK_VK_TO_CHAR
    if ch and 32 < ch < 0xFFFF:
        return chr(ch).upper()
    return None


def vk_name(vk: int) -> str | None:
    if vk in _NAMED:
        return _NAMED[vk]
    if vk in _OEM_VKS:
        return _oem_char(vk) or f"VK{vk:02X}"
    return None


def vk_from_name(name: str) -> int | None:
    low = name.strip().lower()
    if low in _BY_NAME:
        return _BY_NAME[low]
    if low.startswith("vk") and len(low) == 4:
        try:
            return int(low[2:], 16)
        except ValueError:
            return None
    for vk in _OEM_VKS:
        if (_oem_char(vk) or "").lower() == low:
            return vk
    return None


def format_hotkey(mods: int, vk: int) -> str | None:
    key = vk_name(vk)
    if key is None:
        return None
    parts = [name for name, flag in MODIFIER_NAMES if mods & flag]
    parts.append(key)
    return "+".join(parts)


def parse_hotkey(text: str | None) -> tuple[int, int] | None:
    """'Ctrl+Shift+F1' -> (mods, vk). Retorna None se inválido."""
    if not text:
        return None
    # "Num+" e "+" precisam de cuidado: separa pelo '+' mas preserva um '+' final.
    raw = text.strip()
    parts: list[str] = []
    token = ""
    for i, ch in enumerate(raw):
        if ch == "+" and token and i != len(raw) - 1 and token.lower() != "num":
            parts.append(token)
            token = ""
        else:
            token += ch
    if token:
        parts.append(token)
    if not parts:
        return None
    mods = 0
    flags = {name.lower(): flag for name, flag in MODIFIER_NAMES}
    for p in parts[:-1]:
        flag = flags.get(p.strip().lower())
        if flag is None:
            return None
        mods |= flag
    vk = vk_from_name(parts[-1])
    if vk is None:
        return None
    return mods, vk


def normalize_hotkey(text: str | None) -> str | None:
    parsed = parse_hotkey(text)
    return format_hotkey(*parsed) if parsed else None
