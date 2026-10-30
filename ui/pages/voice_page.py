"""Voice Changer: cartões de efeitos com controles individuais + barra de presets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.app_controller import AppController
from effects.base import Effect
from effects.chain import DISPLAY_ORDER
from ui import theme
from ui.widgets.common import Card, button, label, tool_button
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.level_meter import LevelMeter
from ui.widgets.param_slider import ParamSlider
from ui.widgets.toggle_switch import ToggleSwitch

PERCENT_KEYS = {"mix", "feedback", "resonance", "room_size", "damping"}


class EffectCard(Card):
    def __init__(self, ctl: AppController, cls: type[Effect], parent=None):
        super().__init__(parent, padding=14, spacing=8)
        self.ctl = ctl
        self.cls = cls
        self.setFixedWidth(300)
        head = QHBoxLayout()
        title = label(cls.display_name, "H3")
        title.setToolTip(cls.description)
        head.addWidget(title)
        head.addStretch(1)
        reset = tool_button("undo", "Restaurar valores padrão", 15)
        reset.clicked.connect(self._reset)
        head.addWidget(reset)
        self.toggle = ToggleSwitch()
        self.toggle.toggled.connect(self._toggled)
        head.addWidget(self.toggle)
        self.body.addLayout(head)
        desc = label(cls.description, "Faint", wrap=True)
        self.body.addWidget(desc)

        self.sliders: dict[str, ParamSlider] = {}
        for spec in cls.params_spec:
            s = ParamSlider(spec.label, spec.minimum, spec.maximum, spec.default, spec.step, spec.unit,
                            spec.decimals, spec.log, percent=spec.key in PERCENT_KEYS)
            s.valueChanged.connect(lambda v, k=spec.key: self.ctl.set_effect_params(self.cls.effect_id, {k: v}))
            self.sliders[spec.key] = s
            self.body.addWidget(s)
        self.body.addStretch(1)

    def _toggled(self, on: bool) -> None:
        self.ctl.set_effect_enabled(self.cls.effect_id, on)
        self._apply_enabled_look(on)

    def _apply_enabled_look(self, on: bool) -> None:
        p = theme.current()
        border = p.accent if on else p.border
        self.setStyleSheet(f"#Card {{ border: 1px solid {border}; }}")

    def _reset(self) -> None:
        defaults = self.cls.default_params()
        for k, v in defaults.items():
            self.sliders[k].setValue(v)
        self.ctl.set_effect_params(self.cls.effect_id, defaults)

    def load(self, entry: dict) -> None:
        self.toggle.setCheckedSilently(entry["enabled"])
        self._apply_enabled_look(entry["enabled"])
        for k, v in entry["params"].items():
            if k in self.sliders:
                self.sliders[k].setValue(v)


class VoicePage(QWidget):
    def __init__(self, ctl: AppController, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctl = ctl

        # --- cabeçalho
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Voice Changer", "H1"))
        titles.addWidget(label("Combine efeitos em tempo real. As alterações são aplicadas imediatamente, "
                               "sem interromper o áudio.", "Dim", wrap=True))
        head.addLayout(titles, 1)
        master = QHBoxLayout()
        master.setSpacing(10)
        master.addWidget(label("Modificador ativo", "H3"))
        self.master = ToggleSwitch(ctl.voice_enabled)
        self.master.setFixedSize(48, 26)
        self.master.toggled.connect(ctl.set_voice_enabled)
        master.addWidget(self.master)
        head.addLayout(master)

        # --- barra de preset
        bar = Card(padding=12)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label("Preset", "H3"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(220)
        self.preset_combo.activated.connect(self._preset_selected)
        row.addWidget(self.preset_combo)
        self.modified = label("Alterado", "Badge")
        row.addWidget(self.modified)
        row.addStretch(1)
        row.addWidget(label("Entrada", "Faint"))
        self.in_meter = LevelMeter(thickness=6)
        self.in_meter.setFixedWidth(110)
        row.addWidget(self.in_meter)
        row.addWidget(label("Voz", "Faint"))
        self.out_meter = LevelMeter(thickness=6)
        self.out_meter.setFixedWidth(110)
        row.addWidget(self.out_meter)
        self.revert_btn = button("Descartar", "undo", tooltip="Voltar aos valores salvos do preset")
        self.revert_btn.clicked.connect(ctl.revert_changes)
        row.addWidget(self.revert_btn)
        self.save_btn = button("Salvar", "save", accent=True)
        self.save_btn.clicked.connect(ctl.save_active_preset)
        row.addWidget(self.save_btn)
        save_as = button("Salvar como…", "copy")
        save_as.clicked.connect(self._save_as)
        row.addWidget(save_as)
        bar.body.addLayout(row)

        # --- playback / teste de voz
        test = Card(padding=12)
        trow = QHBoxLayout()
        trow.setSpacing(10)
        trow.addWidget(label("Ouvir como está", "H3"))
        self.playback = ToggleSwitch(ctl.playback)
        self.playback.toggled.connect(ctl.set_playback)
        self.playback.setToolTip("Playback ao vivo: sua voz processada nos fones (com um pequeno atraso).")
        trow.addWidget(self.playback)
        trow.addWidget(label("Playback ao vivo", "Dim"))
        trow.addSpacing(16)
        self.test_btn = button("Gravar teste (5 s)", "mic")
        self.test_btn.setToolTip("Grava 5 segundos do que os outros ouvem (voz + efeitos + sons) e toca de "
                                 "volta só nos seus fones. Bom para ouvir sem o atraso do playback ao vivo.")
        self.test_btn.clicked.connect(lambda: ctl.record_test(5.0))
        trow.addWidget(self.test_btn)
        self.test_bar = QProgressBar()
        self.test_bar.setRange(0, 1000)
        self.test_bar.setTextVisible(False)
        self.test_bar.setFixedHeight(6)
        self.test_bar.setMaximumWidth(220)
        trow.addWidget(self.test_bar, 1)
        self.test_label = label("", "Faint")
        trow.addWidget(self.test_label)
        trow.addStretch(1)
        test.body.addLayout(trow)

        # --- cartões
        self.cards: dict[str, EffectCard] = {}
        grid_host = QWidget()
        self.flow = FlowLayout(grid_host, spacing=14, stretch_items=True)
        for cls in DISPLAY_ORDER:
            card = EffectCard(ctl, cls)
            card.setMinimumWidth(300)
            card.setMaximumWidth(16777215)
            self.cards[cls.effect_id] = card
            self.flow.addWidget(card)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 8, 0)
        il.addWidget(grid_host)
        il.addStretch(1)
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        root.addLayout(head)
        root.addWidget(bar)
        root.addWidget(test)
        root.addWidget(scroll, 1)

        ctl.voice_state_changed.connect(self.load_state)
        ctl.voice_modified_changed.connect(self._set_modified)
        ctl.voice_enabled_changed.connect(self.master.setCheckedSilently)
        ctl.playback_changed.connect(self.playback.setCheckedSilently)
        ctl.test_state_changed.connect(self._test_state)
        self._test_state("idle")
        ctl.presets_changed.connect(self.reload_presets)
        ctl.active_preset_changed.connect(lambda _id: self.reload_presets())
        self.reload_presets()
        self.load_state()
        self._set_modified(ctl.voice_modified)

    def load_state(self) -> None:
        state = self.ctl.voice_state()
        for eid, card in self.cards.items():
            card.load(state[eid])

    def reload_presets(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for p in self.ctl.preset_list():
            self.preset_combo.addItem(("★ " if p.is_default else "") + p.name, p.id)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(self.ctl.active_preset_id)))
        self.preset_combo.blockSignals(False)

    def _preset_selected(self, idx: int) -> None:
        pid = self.preset_combo.itemData(idx)
        if pid is not None and pid != self.ctl.active_preset_id:
            self.ctl.load_preset(pid)

    def _set_modified(self, modified: bool) -> None:
        self.modified.setVisible(modified)
        self.revert_btn.setEnabled(modified)
        self.save_btn.setEnabled(modified)

    def _save_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Salvar preset como", "Nome do novo preset:")
        if ok and name.strip():
            self.ctl.create_preset(name.strip(), from_current=True)
            self.ctl.notify.emit("success", f"Preset “{name.strip()}” criado")

    def _test_state(self, state: str) -> None:
        texts = {"idle": "Gravar teste (5 s)", "recording": "Parar gravação", "playing": "Parar"}
        self.test_btn.setText(texts[state])
        self.test_bar.setVisible(state != "idle")
        self.test_label.setText({"recording": "● Gravando… fale agora", "playing": "▶ Ouvindo a gravação",
                                 "idle": ""}[state])
        self.test_label.setStyleSheet("color: #EF4444;" if state == "recording" else "")

    def tick(self, levels: dict) -> None:
        if self.ctl.test_state != "idle":
            self.test_bar.setValue(int(self.ctl.test_progress() * 1000))
        self.in_meter.set_level(levels.get("input", 0.0))
        self.out_meter.set_level(levels.get("processed", 0.0))
