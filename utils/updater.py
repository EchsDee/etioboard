"""Atualização pelo próprio aplicativo, a partir das releases do GitHub.

Fluxo:
1. ``check()`` consulta a última release e compara a versão com ``APP_VERSION``.
2. ``download()`` baixa o zip da release e confere o SHA-256 publicado pelo GitHub
   (campo ``digest`` do asset) ou, na falta dele, o arquivo ``.sha256`` da release.
3. ``extract()`` descompacta numa pasta temporária, recusando caminhos fora dela.
4. ``launch_installer()`` inicia um script PowerShell que espera o app fechar, troca os
   arquivos da pasta de instalação (guardando os antigos para desfazer em caso de falha)
   e reabre o etioboard. Os dados do usuário ficam em %APPDATA% e não são tocados.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from utils.paths import APP_NAME, APP_VERSION, app_data_dir, is_frozen

log = logging.getLogger(__name__)

REPO = "EchsDee/etioboard"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_RE = re.compile(rf"^{APP_NAME}-[\w.\-]+-win64\.zip$", re.IGNORECASE)
MAX_DOWNLOAD = 1024 * 1024 * 1024
EXE_NAME = f"{APP_NAME}.exe"


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    size: int
    sha256: str | None
    sha256_url: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def _api_url() -> str:
    return os.environ.get("ETIOBOARD_UPDATE_URL") or API_URL


def _open(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def check(timeout: float = 15.0) -> UpdateInfo | None:
    """Retorna a release mais nova que a versão atual, ou None se já está atualizado."""
    try:
        with _open(_api_url(), timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("Nenhuma versão publicada encontrada.") from exc
        raise UpdateError(f"O GitHub respondeu com erro {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Sem conexão com o servidor de atualizações.") from exc

    version = str(data.get("tag_name") or data.get("name") or "").lstrip("vV")
    if not version or not is_newer(version):
        return None
    assets = data.get("assets") or []
    asset = next((a for a in assets if ASSET_RE.match(a.get("name", ""))), None)
    if asset is None:
        raise UpdateError(f"A versão {version} não tem o pacote para Windows.")
    digest = str(asset.get("digest") or "")
    sha = digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else None
    sha_asset = next((a for a in assets if a.get("name") == asset["name"] + ".sha256"), None)
    return UpdateInfo(
        version=version,
        notes=str(data.get("body") or "").strip(),
        page_url=str(data.get("html_url") or f"https://github.com/{REPO}/releases"),
        asset_name=asset["name"],
        asset_url=asset["browser_download_url"],
        size=int(asset.get("size") or 0),
        sha256=sha,
        sha256_url=sha_asset["browser_download_url"] if sha_asset else None,
    )


def _expected_sha(info: UpdateInfo) -> str:
    if info.sha256:
        return info.sha256
    if info.sha256_url:
        with _open(info.sha256_url, 15.0) as resp:
            text = resp.read(4096).decode("utf-8", "replace")
        m = re.search(r"\b[0-9a-fA-F]{64}\b", text)
        if m:
            return m.group(0).lower()
    raise UpdateError("A versão publicada não tem soma de verificação (SHA-256); atualização recusada.")


def download(info: UpdateInfo, dest_dir: Path, progress: Callable[[int, int], None] | None = None,
             cancel: threading.Event | None = None) -> Path:
    """Baixa o pacote e confere a integridade. Retorna o caminho do zip."""
    expected = _expected_sha(info)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / info.asset_name
    h = hashlib.sha256()
    try:
        with _open(info.asset_url, 30.0) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length") or info.size or 0)
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("Download cancelado.")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_DOWNLOAD:
                    raise UpdateError("Download inesperadamente grande; cancelado.")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"Falha no download: {exc}") from exc
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise
    if h.hexdigest() != expected:
        dest.unlink(missing_ok=True)
        raise UpdateError("O arquivo baixado está corrompido ou foi alterado (SHA-256 não confere).")
    return dest


def extract(zip_path: Path, dest_dir: Path) -> Path:
    """Descompacta e retorna a pasta que contém o etioboard.exe."""
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True)
    root = dest_dir.resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                target = (dest_dir / member.filename).resolve()
                if not target.is_relative_to(root):
                    raise UpdateError("Pacote de atualização inválido (caminho fora da pasta).")
            zf.extractall(dest_dir)
    except zipfile.BadZipFile as exc:
        raise UpdateError("Pacote de atualização inválido (zip corrompido).") from exc
    found = sorted(dest_dir.rglob(EXE_NAME), key=lambda p: len(p.parts))
    if not found:
        raise UpdateError(f"Pacote de atualização sem {EXE_NAME}.")
    return found[0].parent


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def can_self_update() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "A atualização automática só funciona no Windows."
    if not is_frozen():
        return False, "Executando pelo código-fonte: atualize com git pull."
    folder = install_dir()
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".write-test-", delete=True):
            pass
    except OSError:
        return False, f"Sem permissão para gravar em {folder}. Mova o etioboard para uma pasta do usuário."
    return True, ""


def staging_dir() -> Path:
    return Path(tempfile.gettempdir()) / f"{APP_NAME}-update"


# O script roda depois que o app fecha. Move só os itens que o pacote novo traz (arquivos que o
# usuário tenha colocado na pasta ficam intactos); se algo falhar, devolve os antigos e reabre.
_INSTALL_PS1 = r"""
param([int]$AppPid, [string]$Src, [string]$Dst, [string]$Log)
$ErrorActionPreference = 'Stop'
function Say($m) { Add-Content -LiteralPath $Log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m) }
function Move-Atomic($from, $to) {
    if (Test-Path -LiteralPath $from -PathType Container) { [System.IO.Directory]::Move($from, $to) }
    else { [System.IO.File]::Move($from, $to) }
}
$exe = Join-Path $Dst 'etioboard.exe'
$old = Join-Path $Dst '.update-old'
try {
    Say "Aguardando o etioboard (PID $AppPid) fechar..."
    try { Wait-Process -Id $AppPid -Timeout 60 -ErrorAction Stop } catch { }
    Start-Sleep -Milliseconds 500
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
    New-Item -ItemType Directory -Path $old | Out-Null
    $items = Get-ChildItem -LiteralPath $Src -Force
    $moved = New-Object System.Collections.ArrayList
    $copied = New-Object System.Collections.ArrayList
    try {
        # Renomeações atômicas: ou o item inteiro sai, ou nada muda (Move-Item pode mover pela metade).
        foreach ($it in $items) {
            $cur = Join-Path $Dst $it.Name
            if (Test-Path -LiteralPath $cur) {
                for ($i = 0; $i -lt 20; $i++) {
                    try { Move-Atomic $cur (Join-Path $old $it.Name); break }
                    catch { if ($i -eq 19) { throw }; Start-Sleep -Milliseconds 500 }
                }
                [void]$moved.Add($it.Name)
            }
        }
        foreach ($it in $items) {
            [void]$copied.Add($it.Name)
            Copy-Item -LiteralPath $it.FullName -Destination $Dst -Recurse -Force
        }
    } catch {
        Say "Falha ao trocar os arquivos: $_ . Restaurando a versao anterior."
        foreach ($n in $copied) { Remove-Item -LiteralPath (Join-Path $Dst $n) -Recurse -Force -ErrorAction SilentlyContinue }
        foreach ($n in $moved) { Move-Atomic (Join-Path $old $n) (Join-Path $Dst $n) }
        Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
        Say "Versao anterior restaurada."
        Start-Process -FilePath $exe -ArgumentList '--restart'
        exit 1
    }
    Say "Arquivos atualizados. Reabrindo."
    Start-Process -FilePath $exe -ArgumentList '--restart', '--updated'
    Start-Sleep -Seconds 3
    Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Split-Path $Src -Parent) -Recurse -Force -ErrorAction SilentlyContinue
    Say "Atualizacao concluida."
} catch {
    Say "Erro inesperado: $_"
    if (Test-Path -LiteralPath $exe) { Start-Process -FilePath $exe -ArgumentList '--restart' }
    exit 1
}
"""


def launch_installer(new_build: Path, target: Path | None = None, pid: int | None = None) -> None:
    """Inicia o script que aplica a atualização assim que este processo terminar."""
    target = target or install_dir()
    script = staging_dir() / "install.ps1"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_INSTALL_PS1, encoding="utf-8-sig")
    log_file = app_data_dir() / "logs" / "update.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    # NEW_PROCESS_GROUP | NO_WINDOW. Sem DETACHED_PROCESS: com ele o PowerShell sai sem executar nada.
    flags = 0x00000200 | 0x08000000
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
         "-File", str(script), "-AppPid", str(pid or os.getpid()), "-Src", str(new_build),
         "-Dst", str(target), "-Log", str(log_file)],
        creationflags=flags, close_fds=True,
    )
    log.info("Instalador da atualização iniciado (%s -> %s)", new_build, target)
