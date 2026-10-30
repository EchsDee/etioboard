"""Persistência do Auto-Tune Studio: músicas importadas (com análise) e presets de Auto-Tune."""
from __future__ import annotations

import copy
import json
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from audio.audio_loader import SUPPORTED_EXTENSIONS, AudioLoadError, probe
from database.db import Database
from utils.paths import app_data_dir

log = logging.getLogger(__name__)

DEFAULT_PARAMS = {"amount": 1.0, "retune_ms": 40.0, "humanize": 0.3, "flex_cents": 0.0,
                  "formant": 1.0, "ref_hz": 440.0}

BUILTIN_AT_PRESETS: list[tuple[str, str, dict]] = [
    ("natural", "Natural Correction",
     {"params": {"amount": 0.8, "retune_ms": 120, "humanize": 0.6, "flex_cents": 30, "formant": 1.0},
      "scale": "chromatic", "song_mode": "chord"}),
    ("light", "Light Auto-Tune",
     {"params": {"amount": 0.9, "retune_ms": 60, "humanize": 0.4, "flex_cents": 15, "formant": 1.0},
      "scale": "chromatic", "song_mode": "chord"}),
    ("hard", "Hard Auto-Tune",
     {"params": {"amount": 1.0, "retune_ms": 0, "humanize": 0.0, "flex_cents": 0, "formant": 1.0},
      "scale": "chromatic", "song_mode": "scale"}),
    ("robotic", "Robotic",
     {"params": {"amount": 1.0, "retune_ms": 0, "humanize": 0.0, "flex_cents": 0, "formant": 0.6},
      "scale": "chromatic", "song_mode": "scale"}),
    ("pop", "Pop Vocal",
     {"params": {"amount": 0.95, "retune_ms": 30, "humanize": 0.3, "flex_cents": 10, "formant": 1.0},
      "scale": "major", "song_mode": "chord"}),
    ("trap", "Trap Vocal",
     {"params": {"amount": 1.0, "retune_ms": 5, "humanize": 0.1, "flex_cents": 0, "formant": 0.9},
      "scale": "minor", "song_mode": "scale"}),
    ("rnb", "R&B Vocal",
     {"params": {"amount": 0.85, "retune_ms": 80, "humanize": 0.7, "flex_cents": 25, "formant": 1.0},
      "scale": "minor", "song_mode": "chord"}),
]


def songs_dir() -> Path:
    path = app_data_dir() / "songs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_preset_data(data: dict | None) -> dict:
    data = data or {}
    params = dict(DEFAULT_PARAMS)
    params.update({k: float(v) for k, v in (data.get("params") or {}).items() if k in DEFAULT_PARAMS})
    return {
        "params": params,
        "key": int(data.get("key", 0)) % 12,
        "scale": data.get("scale", "chromatic"),
        "song_mode": data.get("song_mode", "chord"),
    }


@dataclass
class AutoTunePreset:
    id: int
    name: str
    data: dict
    builtin_key: str | None = None


@dataclass
class Song:
    id: int
    name: str
    file_path: str
    original_filename: str
    duration: float
    status: str
    error: str | None
    analysis: dict | None
    preset_id: int | None
    correction_mode: str
    analysis_auto: dict | None = field(default=None, repr=False)

    @classmethod
    def from_row(cls, r: dict) -> "Song":
        def load(v):
            try:
                return json.loads(v) if v else None
            except json.JSONDecodeError:
                return None
        return cls(id=r["id"], name=r["name"], file_path=r["file_path"], original_filename=r["original_filename"],
                   duration=float(r["duration"]), status=r["status"], error=r["error"],
                   analysis=load(r["analysis"]), analysis_auto=load(r["analysis_auto"]),
                   preset_id=r["preset_id"], correction_mode=r["correction_mode"] or "chord")


class AutoTunePresetManager:
    def __init__(self, db: Database):
        self.db = db

    def all(self) -> list[AutoTunePreset]:
        rows = self.db.query("SELECT * FROM autotune_presets ORDER BY position, id")
        return [AutoTunePreset(r["id"], r["name"], normalize_preset_data(json.loads(r["data"])), r["builtin_key"])
                for r in rows]

    def get(self, pid: int | None) -> AutoTunePreset | None:
        if pid is None:
            return None
        r = self.db.query_one("SELECT * FROM autotune_presets WHERE id = ?", (pid,))
        return AutoTunePreset(r["id"], r["name"], normalize_preset_data(json.loads(r["data"])),
                              r["builtin_key"]) if r else None

    def create(self, name: str, data: dict, builtin_key: str | None = None) -> int:
        pos = self.db.query_one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM autotune_presets")["p"]
        return self.db.execute(
            "INSERT INTO autotune_presets(name, data, builtin_key, position) VALUES(?, ?, ?, ?)",
            (name.strip() or "Preset", json.dumps(normalize_preset_data(data)), builtin_key, pos))

    def update(self, pid: int, data: dict) -> None:
        self.db.execute("UPDATE autotune_presets SET data = ? WHERE id = ?",
                        (json.dumps(normalize_preset_data(data)), pid))

    def rename(self, pid: int, name: str) -> None:
        self.db.execute("UPDATE autotune_presets SET name = ? WHERE id = ?", (name.strip(), pid))

    def delete(self, pid: int) -> None:
        self.db.execute("DELETE FROM autotune_presets WHERE id = ?", (pid,))

    def seed_builtins(self) -> None:
        if self.db.query_one("SELECT id FROM autotune_presets LIMIT 1"):
            return
        for key, name, data in BUILTIN_AT_PRESETS:
            self.create(name, data, key)


class SongLibrary:
    def __init__(self, db: Database):
        self.db = db

    def all(self) -> list[Song]:
        return [Song.from_row(r) for r in self.db.query("SELECT * FROM songs ORDER BY created_at DESC, id DESC")]

    def get(self, sid: int | None) -> Song | None:
        if sid is None:
            return None
        r = self.db.query_one("SELECT * FROM songs WHERE id = ?", (sid,))
        return Song.from_row(r) if r else None

    def import_file(self, path: str | Path) -> Song:
        src = Path(path)
        if src.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise AudioLoadError(f"Formato não suportado: {src.suffix} (use WAV, MP3, OGG ou FLAC)")
        duration = probe(src)
        dest = songs_dir() / f"{uuid.uuid4().hex}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        sid = self.db.execute(
            "INSERT INTO songs(name, file_path, original_filename, duration) VALUES(?, ?, ?, ?)",
            (src.stem, str(dest), src.name, duration))
        return self.get(sid)

    def set_status(self, sid: int, status: str, error: str | None = None) -> None:
        self.db.execute("UPDATE songs SET status = ?, error = ? WHERE id = ?", (status, error, sid))

    def save_auto_analysis(self, sid: int, analysis: dict) -> None:
        """Grava a análise automática; também vira a versão editável (descarta edições anteriores)."""
        text = json.dumps(analysis)
        self.db.execute("UPDATE songs SET analysis = ?, analysis_auto = ?, status = 'ready', error = NULL "
                        "WHERE id = ?", (text, text, sid))

    def save_analysis(self, sid: int, analysis: dict) -> None:
        self.db.execute("UPDATE songs SET analysis = ? WHERE id = ?", (json.dumps(analysis), sid))

    def restore_auto(self, sid: int) -> dict | None:
        s = self.get(sid)
        if s and s.analysis_auto:
            self.save_analysis(sid, s.analysis_auto)
            return copy.deepcopy(s.analysis_auto)
        return None

    def update(self, sid: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("name", "preset_id", "correction_mode")}
        if allowed:
            cols = ", ".join(f"{k} = ?" for k in allowed)
            self.db.execute(f"UPDATE songs SET {cols} WHERE id = ?", (*allowed.values(), sid))

    def delete(self, sid: int) -> None:
        s = self.get(sid)
        self.db.execute("DELETE FROM songs WHERE id = ?", (sid,))
        if s:
            try:
                p = Path(s.file_path)
                if p.parent.resolve() == songs_dir().resolve():
                    p.unlink(missing_ok=True)
            except OSError:
                log.warning("Não foi possível remover %s", s.file_path)
