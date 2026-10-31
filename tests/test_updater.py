"""Atualizador: versão, consulta à release, download com SHA-256 e extração segura."""
import hashlib
import io
import json
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from utils import updater


def test_version_compare():
    assert updater.is_newer("1.1.0", "1.0.0")
    assert updater.is_newer("v1.10.0", "1.9.3")
    assert not updater.is_newer("1.0.0", "1.0.0")
    assert not updater.is_newer("0.9", "1.0.0")


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture()
def server(tmp_path, monkeypatch):
    root = tmp_path / "www"
    root.mkdir()

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    monkeypatch.setenv("ETIOBOARD_UPDATE_URL", base + "/latest.json")

    def publish(version: str, payload: bytes, digest: str | None = "auto", sha_file: bool = False):
        name = f"etioboard-{version}-win64.zip"
        (root / name).write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
        asset = {"name": name, "browser_download_url": f"{base}/{name}", "size": len(payload)}
        if digest == "auto":
            asset["digest"] = "sha256:" + sha
        elif digest:
            asset["digest"] = digest
        assets = [asset]
        if sha_file:
            (root / (name + ".sha256")).write_text(f"{sha}  {name}\n")
            assets.append({"name": name + ".sha256", "browser_download_url": f"{base}/{name}.sha256"})
        (root / "latest.json").write_text(json.dumps(
            {"tag_name": f"v{version}", "body": "Novidades", "html_url": base, "assets": assets}))

    yield publish
    httpd.shutdown()


def test_check_download_and_extract(server, tmp_path):
    payload = _zip_bytes({"etioboard/etioboard.exe": b"exe", "etioboard/_internal/lib.dll": b"dll"})
    server("0.0.1", payload)
    assert updater.check() is None  # mais antiga que a instalada

    server("99.0.0", payload)
    info = updater.check()
    assert info.version == "99.0.0" and info.notes == "Novidades" and info.sha256
    seen = []
    zip_path = updater.download(info, tmp_path / "dl", lambda d, t: seen.append((d, t)))
    assert seen[-1] == (len(payload), len(payload))
    build = updater.extract(zip_path, tmp_path / "x")
    assert (build / "etioboard.exe").read_bytes() == b"exe"
    assert (build / "_internal" / "lib.dll").exists()


def test_sha_from_sidecar_file_when_no_digest(server, tmp_path):
    server("99.0.0", _zip_bytes({"etioboard.exe": b"exe"}), digest=None, sha_file=True)
    info = updater.check()
    assert info.sha256 is None and info.sha256_url
    build = updater.extract(updater.download(info, tmp_path / "dl"), tmp_path / "x")
    assert (build / "etioboard.exe").exists()


def test_rejects_tampered_or_unverifiable_download(server, tmp_path):
    server("99.0.0", _zip_bytes({"etioboard.exe": b"exe"}), digest="sha256:" + "0" * 64)
    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.download(updater.check(), tmp_path / "dl")
    assert not list((tmp_path / "dl").glob("*.zip"))

    server("99.0.0", _zip_bytes({"etioboard.exe": b"exe"}), digest=None)
    with pytest.raises(updater.UpdateError, match="soma de verificação"):
        updater.download(updater.check(), tmp_path / "dl")


def test_extract_rejects_path_traversal_and_missing_exe(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(_zip_bytes({"../evil.txt": b"x", "etioboard.exe": b"exe"}))
    with pytest.raises(updater.UpdateError, match="fora da pasta"):
        updater.extract(bad, tmp_path / "x")
    assert not (tmp_path / "evil.txt").exists()

    noexe = tmp_path / "noexe.zip"
    noexe.write_bytes(_zip_bytes({"readme.txt": b"x"}))
    with pytest.raises(updater.UpdateError, match="sem etioboard.exe"):
        updater.extract(noexe, tmp_path / "y")


def test_offline_check_reports_error(monkeypatch):
    monkeypatch.setenv("ETIOBOARD_UPDATE_URL", "http://127.0.0.1:9/latest.json")
    with pytest.raises(updater.UpdateError, match="Sem conexão"):
        updater.check(timeout=2)


def test_cannot_self_update_from_source():
    ok, reason = updater.can_self_update()
    assert not ok and "código-fonte" in reason
