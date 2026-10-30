"""Testes de persistência: banco, biblioteca, presets, configurações, atalhos."""
from pathlib import Path

import pytest

from audio.audio_loader import AudioLoadError
from database.db import Database
from hotkeys.keymap import normalize_hotkey, parse_hotkey
from presets.preset_manager import PresetManager
from settings.settings_manager import SettingsManager
from soundboard.library import SnippetLibrary


@pytest.fixture()
def db(data_dir):
    d = Database(data_dir / "test.db")
    yield d
    d.close()


def test_library_import_copy_rename_move_replace_delete(db, data_dir, tone_file):
    lib = SnippetLibrary(db)
    lib.seed_defaults()
    cats = lib.categories()
    assert [c.name for c in cats][:2] == ["Memes", "Reactions"]

    src = tone_file("Airhorn.wav")
    s = lib.import_file(src, cats[0].id)
    stored = Path(s.file_path)
    assert stored.parent == data_dir / "sounds" and stored.exists() and s.name == "Airhorn"
    assert s.duration == pytest.approx(0.5, abs=0.01)

    lib.update_snippet(s.id, name="Buzina", favorite=True, volume=0.5, hotkey="Ctrl+F1", loop=True)
    s = lib.snippet(s.id)
    assert (s.name, s.favorite, s.volume, s.hotkey, s.loop) == ("Buzina", True, 0.5, "Ctrl+F1", True)
    assert lib.snippets(search="buz")[0].id == s.id
    assert lib.snippets(search="%") == []  # curinga escapado
    assert lib.snippets(favorites_only=True)[0].id == s.id

    lib.move_to_category(s.id, cats[1].id)
    assert lib.snippet(s.id).category_id == cats[1].id

    old, new = lib.replace_file(s.id, tone_file("New.flac", fmt="FLAC"))
    assert not Path(old).exists() and Path(new).exists()

    lib.delete_snippet(s.id)
    assert lib.snippet(s.id) is None and not Path(new).exists()


def test_import_rejects_unsupported(db, tmp_path):
    lib = SnippetLibrary(db)
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(AudioLoadError):
        lib.import_file(txt)


def test_reorder_and_category_delete_keeps_snippets(db, tone_file):
    lib = SnippetLibrary(db)
    cid = lib.create_category("Test", "🎮", "#22C55E")
    ids = [lib.import_file(tone_file(f"s{i}.wav"), cid).id for i in range(3)]
    lib.reorder(list(reversed(ids)))
    assert [s.id for s in lib.snippets(category_id=cid)] == list(reversed(ids))
    lib.delete_category(cid, delete_snippets=False)
    assert len(lib.snippets(uncategorized=True)) == 3


def test_presets_crud_and_persistence(db):
    pm = PresetManager(db)
    pm.seed_builtins()
    names = [p.name for p in pm.all()]
    assert names == ["Normal Voice", "Deep Voice", "High Voice", "Radio", "Robot", "Demon", "Alien", "Telephone"]
    assert pm.default().name == "Normal Voice"
    deep = pm.all()[1]
    assert deep.state["pitch_shift"]["enabled"] and deep.state["pitch_shift"]["params"]["semitones"] == -4

    pid = pm.create("Meu preset", deep.state)
    st = pm.get(pid).state
    st["reverb"]["enabled"] = True
    st["reverb"]["params"]["mix"] = 0.42
    pm.update_state(pid, st)
    reloaded = PresetManager(db).get(pid)
    assert reloaded.state["reverb"]["params"]["mix"] == 0.42  # valores restaurados corretamente

    dup = pm.duplicate(pid)
    assert pm.get(dup).name == "Meu preset (cópia)"
    pm.rename(dup, "Outro")
    pm.set_default(dup)
    assert pm.default().id == dup
    pm.delete(dup)
    assert pm.default() is not None and pm.default().id != dup

    pm.update_state(deep.id, pm.get(pid).state)
    pm.restore_builtins()
    assert pm.get(deep.id).state["reverb"]["enabled"] is False


def test_settings_flush_and_reload(db, tmp_path):
    s = SettingsManager(db)
    seen = []
    s.add_listener(lambda k, v: seen.append(k))
    s.set("mixer.master_volume", 0.42)
    s.set("audio.input_device", "Mic X")
    s.flush()
    s2 = SettingsManager(db)
    assert s2.get("mixer.master_volume") == 0.42 and s2.get("audio.input_device") == "Mic X"
    assert s2.get("audio.samplerate") == 48000  # padrão
    assert seen == ["mixer.master_volume", "audio.input_device"]
    path = tmp_path / "cfg.json"
    s.export_json(path)
    s.set("mixer.master_volume", 1.0)
    assert s.import_json(path) > 5 and s.get("mixer.master_volume") == 0.42


@pytest.mark.parametrize("text,expected", [
    ("Ctrl+Shift+F1", "Ctrl+Shift+F1"), ("ctrl+alt+k", "Ctrl+Alt+K"), ("Alt+Num+", "Alt+Num+"),
    ("Num5", "Num5"), ("Win+F13", "Win+F13"), ("Shift+Alt+Ctrl+A", "Ctrl+Alt+Shift+A"),
    ("Banana+X", None), ("", None),
])
def test_hotkey_parsing(text, expected):
    assert normalize_hotkey(text) == expected
    if expected:
        assert parse_hotkey(expected) is not None
