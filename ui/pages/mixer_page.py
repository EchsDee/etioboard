"""Mixer: canais com fader vertical e medidor, roteamento do monitor e sons ativos."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.app_controller import AppController
from ui import icons, theme
from ui.widgets.common import Card, button, label, tool_button
from ui.widgets.level_meter import LevelMeter

CHANNELS = [
    # chave de volume, título, ícone, chave de nível
    ("mixer.mic_volume", "Microfone", "mic", "input"),
    ("mixer.voice_volume", "Voz processada", "wave", "voice"),
    ("mixer.soundboard_volume", "Soundboard", "music", "soundboard"),
    ("mixer.monitor_volume", "Monitor (fones)", "headphones", "monitor"),
    ("mixer.master_volume", "Saída geral", "cable", "output"),
]


def _db_text(v: float) -> str:
    if v <= 0.0005:
        return "-∞ dB"
    return f"{20 * math.log10(v):+.1f} dB"


class ChannelStrip(Card):
    def __init__(self, ctl: AppController, key: str, title: str, icon_name: str, level_key: str):
        super().__init__(padding=14, spacing=8)
        self.ctl, self.key, self.level_key = ctl, key, level_key
        p = theme.current()
        self.setMinimumWidth(128)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, p.text_dim, 18))
        head.addWidget(ic)
        head.addWidget(label(title, "H3"), 1)
        self.body.addLayout(head)

        self.value = label("", "Value")
        self.value.setAlignment(Qt.AlignCenter)
        self.db = label("", "Faint")
        self.db.setAlignment(Qt.AlignCenter)

        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, 200)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setMinimumHeight(200)
        self.slider.setToolTip("0 a 200% (duplo clique: 100%)")
        self.meter = LevelMeter(Qt.Vertical, thickness=10)
        mid = QHBoxLayout()
        mid.addStretch(1)
        mid.addWidget(self.slider)
        mid.addSpacing(10)
        mid.addWidget(self.meter)
        mid.addStretch(1)
        self.body.addLayout(mid, 1)
        self.body.addWidget(self.value)
        self.body.addWidget(self.db)
        # rodapé de altura fixa (botões extras) para alinhar os faders de todos os canais
        self.footer = QWidget()
        self.footer.setFixedHeight(38)
        self.footer_lay = QHBoxLayout(self.footer)
        self.footer_lay.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.footer)

        self.slider.valueChanged.connect(self._changed)
        self.slider.installEventFilter(self)
        self.sync()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.slider and event.type() == event.Type.MouseButtonDblClick:
            self.slider.setValue(100)
            return True
        return super().eventFilter(obj, event)

    def sync(self) -> None:
        v = self.ctl.volume(self.key)
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v * 100)))
        self.slider.blockSignals(False)
        self._labels(v)

    def _labels(self, v: float) -> None:
        self.value.setText(f"{v * 100:.0f}%")
        self.db.setText(_db_text(v))

    def _changed(self, pos: int) -> None:
        v = pos / 100.0
        self._labels(v)
        self.ctl.set_volume(self.key, v)

    def tick(self, levels: dict) -> None:
        self.meter.set_level(levels.get(self.level_key, 0.0))


class MixerPage(QWidget):
    def __init__(self, ctl: AppController, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctl = ctl

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Mixer", "H1"))
        titles.addWidget(label("Volumes independentes de cada fonte. A saída geral é o que chega à saída "
                               "virtual (Discord, jogos…).", "Dim", wrap=True))
        head.addLayout(titles, 1)
        stop = button("Parar todos os sons", "stop-all", danger=True)
        stop.clicked.connect(ctl.stop_all)
        head.addWidget(stop)

        strips = QHBoxLayout()
        strips.setSpacing(12)
        self.strips = [ChannelStrip(ctl, *c) for c in CHANNELS]
        for s in self.strips:
            strips.addWidget(s, 1)

        # Mic mute no canal do microfone
        self.mute = button("Mutar", "mic-off")
        self.mute.setObjectName("MuteButton")
        self.mute.setCheckable(True)
        self.mute.clicked.connect(ctl.set_muted)
        self.strips[0].footer_lay.addWidget(self.mute)
        voice_toggle = QCheckBox("Efeitos ativos")
        voice_toggle.setChecked(ctl.voice_enabled)
        voice_toggle.toggled.connect(ctl.set_voice_enabled)
        ctl.voice_enabled_changed.connect(lambda on: (voice_toggle.blockSignals(True),
                                                      voice_toggle.setChecked(on),
                                                      voice_toggle.blockSignals(False)))
        self.strips[1].footer_lay.addWidget(voice_toggle)

        # Roteamento do monitor
        routing = Card(padding=14)
        routing.body.addWidget(label("Monitor (o que você ouve)", "H3"))
        routing.body.addWidget(label("O monitor é a sua saída de fones/alto-falantes. Ele não afeta o que os "
                                     "outros ouvem.", "Faint", wrap=True))
        self.mon_voice = QCheckBox("Ouvir minha voz processada")
        self.mon_voice.setChecked(bool(ctl.settings.get("mixer.monitor_voice")))
        self.mon_voice.toggled.connect(lambda on: ctl.set_monitor_sources(voice=on))
        self.mon_sb = QCheckBox("Ouvir o soundboard")
        self.mon_sb.setChecked(bool(ctl.settings.get("mixer.monitor_soundboard")))
        self.mon_sb.toggled.connect(lambda on: ctl.set_monitor_sources(soundboard=on))
        routing.body.addWidget(self.mon_voice)
        routing.body.addWidget(self.mon_sb)
        routing.body.addStretch(1)

        # Sons ativos
        active = Card(padding=14)
        active.body.addWidget(label("Tocando agora", "H3"))
        self.active_host = QWidget()
        self.active_lay = QGridLayout(self.active_host)
        self.active_lay.setContentsMargins(0, 0, 0, 0)
        self.active_lay.setVerticalSpacing(6)
        active.body.addWidget(self.active_host)
        self.none_label = label("Nenhum som tocando.", "Faint")
        active.body.addWidget(self.none_label)
        active.body.addStretch(1)
        self._active_ids: tuple = ()

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        bottom.addWidget(routing, 1)
        bottom.addWidget(active, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        root.addLayout(head)
        root.addLayout(strips, 3)
        root.addLayout(bottom, 2)

        ctl.mixer_changed.connect(lambda: [s.sync() for s in self.strips])
        ctl.mute_changed.connect(self._sync_mute)
        self._sync_mute(ctl.muted)

    def _sync_mute(self, muted: bool) -> None:
        self.mute.setChecked(muted)
        self.mute.setText("Mutado" if muted else "Mutar")

    def _rebuild_active(self, playing: dict) -> None:
        while self.active_lay.count():
            w = self.active_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for row, sid in enumerate(playing):
            s = self.ctl.snippet(sid)
            name = f"{s.icon}  {s.name}" if s else f"#{sid}"
            if playing[sid][1]:
                name += "  (prévia)"
            self.active_lay.addWidget(label(name), row, 0)
            stop = tool_button("stop", "Parar", 14)
            stop.clicked.connect(lambda _=False, i=sid: self.ctl.stop_snippet(i))
            self.active_lay.addWidget(stop, row, 1)
        self.none_label.setVisible(not playing)

    def tick(self, levels: dict) -> None:
        for s in self.strips:
            s.tick(levels)
        playing = self.ctl.playing()
        ids = tuple(sorted(playing))
        if ids != self._active_ids:
            self._active_ids = ids
            self._rebuild_active(playing)
