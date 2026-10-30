"""Biblioteca de snippets e categorias (SQLite + pasta própria de arquivos)."""
from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from audio.audio_loader import SUPPORTED_EXTENSIONS, AudioLoadError, probe
from database.db import Database
from utils.paths import sounds_dir

log = logging.getLogger(__name__)

DEFAULT_CATEGORIES = [
    ("Memes", "😂", "#F59E0B"),
    ("Reactions", "😮", "#EC4899"),
    ("Games", "🎮", "#22C55E"),
    ("Voice Lines", "🗣️", "#3B82F6"),
    ("Music", "🎵", "#A855F7"),
    ("Miscellaneous", "📦", "#64748B"),
]

SNIPPET_COLORS = [
    "#3B3F5C", "#6D28D9", "#7C3AED", "#2563EB", "#0891B2", "#0D9488", "#16A34A",
    "#65A30D", "#CA8A04", "#EA580C", "#DC2626", "#DB2777", "#9333EA", "#475569",
]


@dataclass
class Category:
    id: int
    name: str
    icon: str
    color: str
    position: int


@dataclass
class Snippet:
    id: int
    name: str
    file_path: str
    original_filename: str
    category_id: int | None
    icon: str
    color: str
    hotkey: str | None
    volume: float
    speed: float
    loop: bool
    favorite: bool
    position: int
    duration: float

    @classmethod
    def from_row(cls, r: dict) -> "Snippet":
        return cls(
            id=r["id"], name=r["name"], file_path=r["file_path"],
            original_filename=r["original_filename"], category_id=r["category_id"],
            icon=r["icon"], color=r["color"], hotkey=r["hotkey"] or None,
            volume=float(r["volume"]), speed=float(r["speed"]), loop=bool(r["loop"]),
            favorite=bool(r["favorite"]), position=int(r["position"]), duration=float(r["duration"]),
        )

    @property
    def exists(self) -> bool:
        return Path(self.file_path).is_file()


class SnippetLibrary:
    EDITABLE = {"name", "category_id", "icon", "color", "hotkey", "volume", "speed", "loop", "favorite"}

    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------------- categorias
    def categories(self) -> list[Category]:
        return [Category(**r) for r in self.db.query("SELECT * FROM categories ORDER BY position, id")]

    def category(self, category_id: int) -> Category | None:
        r = self.db.query_one("SELECT * FROM categories WHERE id = ?", (category_id,))
        return Category(**r) if r else None

    def create_category(self, name: str, icon: str = "📁", color: str = "#6366F1") -> int:
        pos = self.db.query_one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM categories")["p"]
        return self.db.execute(
            "INSERT INTO categories(name, icon, color, position) VALUES(?, ?, ?, ?)",
            (name.strip() or "Categoria", icon, color, pos),
        )

    def update_category(self, category_id: int, name: str, icon: str, color: str) -> None:
        self.db.execute(
            "UPDATE categories SET name = ?, icon = ?, color = ? WHERE id = ?",
            (name.strip(), icon, color, category_id),
        )

    def delete_category(self, category_id: int, delete_snippets: bool = False) -> list[Snippet]:
        """Exclui a categoria. Os snippets ficam sem categoria, ou são excluídos se pedido."""
        removed: list[Snippet] = []
        if delete_snippets:
            for s in self.snippets(category_id=category_id):
                self.delete_snippet(s.id)
                removed.append(s)
        self.db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        return removed

    def reorder_categories(self, ordered_ids: list[int]) -> None:
        self.db.executemany(
            "UPDATE categories SET position = ? WHERE id = ?", [(i, cid) for i, cid in enumerate(ordered_ids)]
        )

    def seed_defaults(self) -> None:
        if self.db.query_one("SELECT id FROM categories LIMIT 1"):
            return
        for name, icon, color in DEFAULT_CATEGORIES:
            self.create_category(name, icon, color)

    # ---------------------------------------------------------------- snippets
    def snippets(self, category_id: int | None = None, favorites_only: bool = False,
                 search: str = "", uncategorized: bool = False) -> list[Snippet]:
        sql = "SELECT * FROM snippets WHERE 1=1"
        params: list = []
        if category_id is not None:
            sql += " AND category_id = ?"
            params.append(category_id)
        if uncategorized:
            sql += " AND category_id IS NULL"
        if favorites_only:
            sql += " AND favorite = 1"
        if search.strip():
            sql += " AND name LIKE ? ESCAPE '\\'"
            term = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{term}%")
        sql += " ORDER BY position, id"
        return [Snippet.from_row(r) for r in self.db.query(sql, params)]

    def snippet(self, snippet_id: int) -> Snippet | None:
        r = self.db.query_one("SELECT * FROM snippets WHERE id = ?", (snippet_id,))
        return Snippet.from_row(r) if r else None

    def count_by_category(self) -> dict[int | None, int]:
        rows = self.db.query("SELECT category_id, COUNT(*) AS n FROM snippets GROUP BY category_id")
        return {r["category_id"]: r["n"] for r in rows}

    @staticmethod
    def is_supported(path: str | Path) -> bool:
        return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS

    def _store_file(self, source: Path, copy: bool) -> Path:
        if not copy:
            return source.resolve()
        dest = sounds_dir() / f"{uuid.uuid4().hex}{source.suffix.lower()}"
        shutil.copy2(source, dest)
        return dest

    def import_file(self, path: str | Path, category_id: int | None = None, copy: bool = True,
                    name: str | None = None) -> Snippet:
        """Valida, copia para a pasta do app e cadastra. Lança AudioLoadError se inválido."""
        source = Path(path)
        if not source.is_file():
            raise AudioLoadError(f"Arquivo não encontrado: {source}")
        if not self.is_supported(source):
            raise AudioLoadError(f"Formato não suportado: {source.suffix} (use WAV, MP3, OGG ou FLAC)")
        duration = probe(source)
        stored = self._store_file(source, copy)
        pos = self.db.query_one(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM snippets WHERE category_id IS ?", (category_id,)
        )["p"]
        color = SNIPPET_COLORS[pos % len(SNIPPET_COLORS)]
        sid = self.db.execute(
            """INSERT INTO snippets(name, file_path, original_filename, category_id, color, position, duration)
               VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (name or source.stem, str(stored), source.name, category_id, color, pos, duration),
        )
        log.info("Snippet importado: %s -> %s", source.name, stored)
        return self.snippet(sid)

    def update_snippet(self, snippet_id: int, **fields) -> None:
        fields = {k: v for k, v in fields.items() if k in self.EDITABLE}
        if not fields:
            return
        if "hotkey" in fields:
            fields["hotkey"] = fields["hotkey"] or None
        for key in ("loop", "favorite"):
            if key in fields:
                fields[key] = int(bool(fields[key]))
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE snippets SET {cols} WHERE id = ?", (*fields.values(), snippet_id))

    def move_to_category(self, snippet_id: int, category_id: int | None) -> None:
        pos = self.db.query_one(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM snippets WHERE category_id IS ?", (category_id,)
        )["p"]
        self.db.execute("UPDATE snippets SET category_id = ?, position = ? WHERE id = ?",
                        (category_id, pos, snippet_id))

    def reorder(self, ordered_ids: list[int]) -> None:
        self.db.executemany(
            "UPDATE snippets SET position = ? WHERE id = ?", [(i, sid) for i, sid in enumerate(ordered_ids)]
        )

    def replace_file(self, snippet_id: int, path: str | Path, copy: bool = True) -> tuple[str, str]:
        """Substitui o arquivo de áudio. Retorna (caminho antigo, caminho novo)."""
        snippet = self.snippet(snippet_id)
        if snippet is None:
            raise AudioLoadError("Snippet não encontrado.")
        source = Path(path)
        if not self.is_supported(source):
            raise AudioLoadError(f"Formato não suportado: {source.suffix}")
        duration = probe(source)
        stored = self._store_file(source, copy)
        self.db.execute(
            "UPDATE snippets SET file_path = ?, original_filename = ?, duration = ? WHERE id = ?",
            (str(stored), source.name, duration, snippet_id),
        )
        self._remove_owned_file(snippet.file_path)
        return snippet.file_path, str(stored)

    def delete_snippet(self, snippet_id: int) -> Snippet | None:
        snippet = self.snippet(snippet_id)
        if snippet is None:
            return None
        self.db.execute("DELETE FROM snippets WHERE id = ?", (snippet_id,))
        self._remove_owned_file(snippet.file_path)
        return snippet

    def _remove_owned_file(self, file_path: str) -> None:
        """Só apaga arquivos que pertencem à pasta do aplicativo e não são usados por outro snippet."""
        p = Path(file_path)
        try:
            if p.resolve().parent != sounds_dir().resolve():
                return
            if self.db.query_one("SELECT id FROM snippets WHERE file_path = ?", (str(p),)):
                return
            p.unlink(missing_ok=True)
        except OSError:
            log.warning("Não foi possível remover %s", p, exc_info=True)

    def hotkeys_in_use(self) -> dict[str, int]:
        rows = self.db.query("SELECT id, hotkey FROM snippets WHERE hotkey IS NOT NULL AND hotkey != ''")
        return {r["hotkey"]: r["id"] for r in rows}
