"""Testes de integração do controlador (sem abrir dispositivos de áudio)."""
import pytest

from core.app_controller import AppController


@pytest.fixture()
def ctl(qapp, data_dir):
    c = AppController(data_dir / "c.db")
    c.hotkeys.start()
    yield c
    c.hotkeys.stop()
    c.engine.shutdown()
    c.settings.flush()
    c.db.close()


def test_first_run_seeds_data(ctl):
    assert len(ctl.preset_list()) == 8
    assert len(ctl.library.categories()) == 6
    assert ctl.presets.get(ctl.active_preset_id).name == "Normal Voice"


def test_preset_edit_modified_save_and_revert(ctl):
    events = []
    ctl.voice_modified_changed.connect(events.append)
    ctl.set_effect_params("reverb", {"mix": 0.5})
    ctl.set_effect_enabled("reverb", True)
    assert ctl.voice_modified and events[-1] is True
    ctl.revert_changes()
    assert not ctl.voice_modified and ctl.voice_state()["reverb"]["enabled"] is False

    ctl.set_effect_enabled("reverb", True)
    ctl.save_active_preset()
    assert not ctl.voice_modified
    assert ctl.presets.get(ctl.active_preset_id).state["reverb"]["enabled"] is True


def test_cycle_presets_and_delete_active(ctl):
    first = ctl.active_preset_id
    ctl.cycle_preset(1)
    assert ctl.active_preset_id != first
    ctl.cycle_preset(-1)
    assert ctl.active_preset_id == first
    new = ctl.create_preset("Teste", from_current=False)
    assert ctl.active_preset_id == new
    assert ctl.delete_preset(new)
    assert ctl.active_preset_id is not None and ctl.active_preset_id != new


def test_volume_mute_and_voice_toggle_reach_engine(ctl):
    ctl.set_volume("mixer.master_volume", 0.5)
    assert ctl.engine.mixer.master.target == 0.5
    ctl.set_muted(True)
    assert ctl.engine.voice.mic.target == 0.0
    ctl.set_muted(False)
    ctl.set_volume("mixer.mic_volume", 1.5)
    assert ctl.engine.voice.mic.target == 1.5
    ctl.set_voice_enabled(False)
    assert ctl.engine.voice.chain is None or not ctl.engine.voice.chain.master
    assert ctl.settings.get("voice.enabled") is False


def test_hotkey_conflicts_between_owners(ctl, tone_file):
    ok, _ = ctl.assign_hotkey("action:toggle_mute", "Ctrl+Alt+Shift+F20")
    assert ok
    cat = ctl.library.categories()[0].id
    ctl.import_files([str(tone_file())], cat)
    sid = ctl.library.snippets()[0].id
    ok, err = ctl.assign_hotkey(f"snippet:{sid}", "ctrl+alt+shift+f20")
    assert not ok and "Mutar" in err
    ok, _ = ctl.assign_hotkey(f"snippet:{sid}", "Ctrl+Alt+Shift+F21")
    assert ok and ctl.library.snippet(sid).hotkey == "Ctrl+Alt+Shift+F21"
    assert set(ctl.hotkeys.registered()) >= {"action:toggle_mute", f"snippet:{sid}"}
    ctl.assign_hotkey("action:toggle_mute", None)
    assert "toggle_mute" not in ctl.action_hotkeys()


def test_hotkey_dispatch(ctl):
    muted = ctl.muted
    ctl._on_hotkey("action:toggle_mute")
    assert ctl.muted is (not muted)
    before = ctl.active_preset_id
    ctl._on_hotkey("action:next_preset")
    assert ctl.active_preset_id != before


def test_delete_snippet_unregisters_hotkey(ctl, tone_file):
    ctl.import_files([str(tone_file())], None)
    sid = ctl.library.snippets()[0].id
    ctl.assign_hotkey(f"snippet:{sid}", "Ctrl+Alt+Shift+F22")
    ctl.delete_snippet(sid)
    assert f"snippet:{sid}" not in ctl.hotkeys.registered()


def test_playback_toggle_updates_mixer_and_setting(ctl):
    seen = []
    ctl.playback_changed.connect(seen.append)
    ctl.set_playback(True)
    assert ctl.playback and ctl.engine.mixer.monitor_voice and seen == [True]
    ctl._on_hotkey("action:toggle_playback")
    assert not ctl.playback and ctl.settings.get("mixer.monitor_voice") is False


def test_record_test_requires_running_audio(ctl):
    ctl.record_test(1.0)
    assert ctl.test_state == "idle"  # motor parado: só avisa


def test_preset_hotkey_modes(ctl):
    presets = {p.builtin_key: p.id for p in ctl.preset_list()}
    normal, demon, robot = presets["normal"], presets["demon"], presets["robot"]
    ctl.load_preset(normal)
    ctl.set_effect_enabled("reverb", True)  # ajuste não salvo deve sobreviver ao atalho temporário
    assert ctl.voice_modified

    # Trocar (padrão): continua no preset depois de soltar.
    ctl.set_preset_hotkey_mode("switch")
    ctl._on_hotkey(f"preset:{demon}")
    ctl._on_hotkey_released(f"preset:{demon}")
    assert ctl.active_preset_id == demon
    ctl.load_preset(normal)
    ctl.set_effect_enabled("reverb", True)

    # Segurar: ativo só enquanto segura; soltar volta à voz anterior (com o ajuste não salvo).
    ctl.set_preset_hotkey_mode("hold")
    ctl._on_hotkey(f"preset:{demon}")
    assert ctl.active_preset_id == demon
    ctl._on_hotkey(f"preset:{robot}")          # outro atalho durante o primeiro
    ctl._on_hotkey_released(f"preset:{demon}")  # soltar o antigo não desfaz o atual
    assert ctl.active_preset_id == robot
    ctl._on_hotkey_released(f"preset:{robot}")
    assert ctl.active_preset_id == normal
    assert ctl.voice_state()["reverb"]["enabled"] and ctl.voice_modified

    # Alternar: aperta liga, aperta de novo volta.
    ctl.set_preset_hotkey_mode("toggle")
    ctl._on_hotkey(f"preset:{demon}")
    ctl._on_hotkey_released(f"preset:{demon}")
    assert ctl.active_preset_id == demon
    ctl._on_hotkey(f"preset:{demon}")
    assert ctl.active_preset_id == normal and ctl.voice_state()["reverb"]["enabled"]

    # Troca manual durante um preset temporário vence: nada é restaurado depois.
    ctl._on_hotkey(f"preset:{demon}")
    ctl.load_preset(robot)
    ctl._on_hotkey(f"preset:{demon}")
    ctl._on_hotkey(f"preset:{demon}")
    assert ctl.active_preset_id == robot
