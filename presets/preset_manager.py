"""CRUD de presets de voz (SQLite)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from database.db import Database
from effects.chain import normalize_state
from presets.builtin import BUILTIN_PRESETS


@dataclass
class Preset:
    id: int
    name: str
    state: dict
    is_default: bool = False
    builtin_key: str | None = None
    hotkey: str | None = None
    position: int = 0
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict) -> "Preset":
        try:
            data = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            data = {}
        return cls(
            id=row["id"],
            name=row["name"],
            state=normalize_state(data.get("effects", data)),
            is_default=bool(row["is_default"]),
            builtin_key=row["builtin_key"],
            hotkey=row["hotkey"] or None,
            position=row["position"],
        )


class PresetManager:
    def __init__(self, db: Database):
        self.db = db

    # --------------------------------------------------------------- consulta
    def all(self) -> list[Preset]:
        rows = self.db.query("SELECT * FROM presets ORDER BY position, id")
        return [Preset.from_row(r) for r in rows]

    def get(self, preset_id: int | None) -> Preset | None:
        if preset_id is None:
            return None
        row = self.db.query_one("SELECT * FROM presets WHERE id = ?", (preset_id,))
        return Preset.from_row(row) if row else None

    def default(self) -> Preset | None:
        row = self.db.query_one("SELECT * FROM presets WHERE is_default = 1 ORDER BY id LIMIT 1")
        if row:
            return Preset.from_row(row)
        presets = self.all()
        return presets[0] if presets else None

    def unique_name(self, base: str) -> str:
        names = {p.name.lower() for p in self.all()}
        if base.lower() not in names:
            return base
        i = 2
        while f"{base} ({i})".lower() in names:
            i += 1
        return f"{base} ({i})"

    # --------------------------------------------------------------- escrita
    @staticmethod
    def _encode(state: dict) -> str:
        return json.dumps({"version": 1, "effects": normalize_state(state)})

    def create(self, name: str, state: dict, builtin_key: str | None = None) -> int:
        pos = (self.db.query_one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM presets") or {"p": 0})["p"]
        return self.db.execute(
            "INSERT INTO presets(name, data, builtin_key, position) VALUES(?, ?, ?, ?)",
            (name.strip() or "Preset", self._encode(state), builtin_key, pos),
        )

    def update_state(self, preset_id: int, state: dict) -> None:
        self.db.execute("UPDATE presets SET data = ? WHERE id = ?", (self._encode(state), preset_id))

    def rename(self, preset_id: int, name: str) -> None:
        self.db.execute("UPDATE presets SET name = ? WHERE id = ?", (name.strip(), preset_id))

    def duplicate(self, preset_id: int) -> int | None:
        p = self.get(preset_id)
        if not p:
            return None
        return self.create(self.unique_name(f"{p.name} (cópia)"), p.state)

    def delete(self, preset_id: int) -> None:
        was_default = self.db.query_one("SELECT is_default FROM presets WHERE id = ?", (preset_id,))
        self.db.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        if was_default and was_default["is_default"]:
            first = self.db.query_one("SELECT id FROM presets ORDER BY position, id LIMIT 1")
            if first:
                self.set_default(first["id"])

    def set_default(self, preset_id: int) -> None:
        with self.db.transaction() as db:
            db.conn.execute("UPDATE presets SET is_default = 0")
            db.conn.execute("UPDATE presets SET is_default = 1 WHERE id = ?", (preset_id,))

    def set_hotkey(self, preset_id: int, hotkey: str | None) -> None:
        self.db.execute("UPDATE presets SET hotkey = ? WHERE id = ?", (hotkey or None, preset_id))

    def reorder(self, ordered_ids: list[int]) -> None:
        self.db.executemany(
            "UPDATE presets SET position = ? WHERE id = ?", [(i, pid) for i, pid in enumerate(ordered_ids)]
        )

    # --------------------------------------------------------------- built-ins
    def seed_builtins(self) -> None:
        if self.db.query_one("SELECT id FROM presets LIMIT 1"):
            return
        for key, name, state in BUILTIN_PRESETS:
            self.create(name, state, builtin_key=key)
        normal = self.db.query_one("SELECT id FROM presets WHERE builtin_key = 'normal'")
        if normal:
            self.set_default(normal["id"])

    def restore_builtins(self) -> int:
        """Recria/restaura os presets originais (mantém os presets do usuário)."""
        restored = 0
        for key, name, state in BUILTIN_PRESETS:
            row = self.db.query_one("SELECT id FROM presets WHERE builtin_key = ?", (key,))
            if row:
                self.update_state(row["id"], state)
                self.rename(row["id"], name)
            else:
                self.create(name, state, builtin_key=key)
            restored += 1
        return restored
