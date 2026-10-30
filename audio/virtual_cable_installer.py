"""Instalação assistida do VB-CABLE.

O Windows só mostra como microfone dispositivos criados por um driver de áudio
(kernel). O etioboard não pode criar um sozinho, então baixa o instalador oficial
do VB-CABLE (donationware, não redistribuído junto com o app), confere a assinatura
digital e o executa com elevação (UAC). O usuário só confirma a instalação.
"""
from __future__ import annotations

import ctypes
import logging
import os
import platform
import subprocess
import tempfile
import urllib.request
import zipfile
from ctypes import wintypes
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

DOWNLOAD_URL = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip"
EXPECTED_SIGNER = "BUREL VINCENT"  # autor do VB-Audio (certificado do instalador)
MAX_DOWNLOAD = 50 * 1024 * 1024


class InstallError(Exception):
    pass


def _download(dest: Path, progress: Callable[[float], None]) -> None:
    req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "etioboard"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            done += len(chunk)
            if done > MAX_DOWNLOAD:
                raise InstallError("Download inesperadamente grande; cancelado.")
            f.write(chunk)
            if total:
                progress(done / total)


def _extract_setup(zip_path: Path, folder: Path) -> Path:
    machine = platform.machine().lower()
    name = "VBCABLE_Setup_x64.exe" if machine in ("amd64", "x86_64", "arm64") else "VBCABLE_Setup.exe"
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            # extrai só arquivos simples (sem caminhos), protegendo contra "zip slip"
            if Path(info.filename).name != info.filename or info.is_dir():
                continue
            z.extract(info, folder)
    setup = folder / name
    if not setup.is_file():
        raise InstallError(f"Instalador '{name}' não encontrado no pacote baixado.")
    return setup


def _check_signature(exe: Path) -> None:
    script = (
        f"$s = Get-AuthenticodeSignature -LiteralPath '{exe}'; "
        "Write-Output $s.Status; Write-Output $s.SignerCertificate.Subject"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout.strip().splitlines()
    status = out[0].strip() if out else ""
    subject = out[1] if len(out) > 1 else ""
    if status != "Valid" or EXPECTED_SIGNER not in subject.upper():
        raise InstallError(f"Assinatura digital do instalador inválida ({status or 'desconhecida'}). "
                           "Instalação cancelada por segurança.")


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def _run_elevated_and_wait(exe: Path) -> None:
    SEE_MASK_NOCLOSEPROCESS = 0x40
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(exe)
    info.lpDirectory = str(exe.parent)
    info.nShow = 1
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        if err == 1223:  # ERROR_CANCELLED: usuário recusou o UAC
            raise InstallError("Instalação cancelada (permissão de administrador negada).")
        raise InstallError(f"Não foi possível abrir o instalador (erro {err}).")
    if info.hProcess:
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        kernel32.CloseHandle(info.hProcess)


def install_vb_cable(progress: Callable[[str, float], None]) -> None:
    """Baixa, verifica e executa o instalador. Bloqueia até o instalador fechar.

    Deve ser chamado fora da thread da interface. Lança InstallError em falhas.
    """
    if os.name != "nt":
        raise InstallError("Disponível apenas no Windows.")
    folder = Path(tempfile.mkdtemp(prefix="etioboard_vbcable_"))
    zip_path = folder / "vbcable.zip"
    try:
        progress("Baixando VB-CABLE…", 0.0)
        _download(zip_path, lambda f: progress("Baixando VB-CABLE…", f))
    except InstallError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise InstallError(f"Falha no download: {exc}") from exc
    progress("Verificando instalador…", 1.0)
    setup = _extract_setup(zip_path, folder / "pack")
    _check_signature(setup)
    progress("Aguardando a instalação (confirme a janela do Windows)…", 1.0)
    log.info("Executando instalador do VB-CABLE: %s", setup)
    _run_elevated_and_wait(setup)
