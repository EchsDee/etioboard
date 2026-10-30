"""Testes da migração de dados do nome antigo e do extrator do instalador do VB-CABLE."""
import sqlite3
import zipfile

import pytest

from audio.virtual_cable_installer import InstallError, _extract_setup
from database.db import Database
from utils import paths


def test_legacy_data_is_copied_and_paths_rewritten(tmp_path, monkeypatch):
    monkeypatch.delenv("ETIOBOARD_DATA", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    old = tmp_path / "VoiceStudio"
    (old / "sounds").mkdir(parents=True)
    (old / "sounds" / "a.wav").write_bytes(b"RIFF")
    db = Database(old / "voicestudio.db")
    db.execute("INSERT INTO snippets(name, file_path) VALUES(?, ?)", ("A", str(old / "sounds" / "a.wav")))
    db.close()

    assert paths.migrate_legacy_data() is True
    new = tmp_path / "etioboard"
    assert (new / "sounds" / "a.wav").exists() and (old / "sounds" / "a.wav").exists()  # antigo preservado
    con = sqlite3.connect(new / "etioboard.db")
    assert con.execute("SELECT file_path FROM snippets").fetchone()[0] == str(new / "sounds" / "a.wav")
    con.close()
    assert paths.migrate_legacy_data() is False  # só uma vez


def test_no_migration_without_legacy_data(tmp_path, monkeypatch):
    monkeypatch.delenv("ETIOBOARD_DATA", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.migrate_legacy_data() is False


def test_extract_setup_ignores_paths_in_zip(tmp_path):
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("VBCABLE_Setup_x64.exe", b"MZ")
        f.writestr("VBCABLE_Setup.exe", b"MZ")
        f.writestr("../evil.exe", b"MZ")
        f.writestr("sub/inner.txt", b"x")
    setup = _extract_setup(z, tmp_path / "out")
    assert setup.name.startswith("VBCABLE_Setup") and setup.exists()
    assert not (tmp_path / "evil.exe").exists() and not (tmp_path / "out" / "sub").exists()


def test_extract_setup_missing_installer(tmp_path):
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("readme.txt", b"x")
    with pytest.raises(InstallError):
        _extract_setup(z, tmp_path / "out")
