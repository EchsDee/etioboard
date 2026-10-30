"""Auto-Tune Studio: correção de afinação em tempo real e Song Mode (sincronizado com uma música)."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from autotune.library import DEFAULT_PARAMS
from autotune.music import CHORD_QUALITIES, NOTE_NAMES, SCALES, chord_name, key_name
from core.app_controller import AppController
from core.autotune_controller import CORRECTION_MODES
from ui import icons, theme
from ui.dialogs.music_dialogs import ChordDialog, KeyDialog
from ui.dialogs.snippet_dialog import AUDIO_FILTER
from ui.widgets.common import Card, button, label, tool_button
from ui.widgets.param_slider import ParamSlider
from ui.widgets.song_timeline import SongTimeline
from ui.widgets.toggle_switch import ToggleSwitch
from ui.widgets.tuner import PitchGraph, TunerDisplay

PARAM_UI = [
    # chave, rótulo, mín, máx, passo, unidade, casas, percentual, dica
    ("amount", "Correction Amount", 0, 1, 0.01, "", 0, True, "Intensidade da correção (0% = voz original)."),
    ("retune_ms", "Retune Speed", 0, 400, 1, "ms", 0, False,
     "Tempo para a nota chegar ao tom certo. 0 ms = efeito robótico (T-Pain); 50–150 ms = natural."),
    ("humanize", "Humanize", 0, 1, 0.01, "", 0, True, "Preserva vibrato e variações naturais da voz."),
    ("flex_cents", "Flex Tune", 0, 100, 1, "cents", 0, False,
     "Desvios menores que este valor quase não são corrigidos (mais expressivo)."),
    ("formant", "Formant Preservation", 0, 1, 0.01, "", 0, True,
     "100% mantém o timbre ao corrigir; menos que isso deixa as formantes acompanharem o tom."),
    ("ref_hz", "Reference Pitch (A4)", 415, 466, 0.1, "Hz", 1, False, "Afinação de referência (padrão 440 Hz)."),
]


def fmt_time(s: float) -> str:
    s = max(0.0, s)
    return f"{int(s) // 60}:{int(s) % 60:02d}"


class AutoTunePage(QWidget):
    def __init__(self, ctl: AppController, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctl = ctl
        self.at = ctl.autotune
        self._seeking = False

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 10, 0)
        root.setSpacing(14)

        # ================================================= cabeçalho
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Auto-Tune Studio", "H1"))
        titles.addWidget(label("Correção de afinação em tempo real, livre ou acompanhando a harmonia de uma música.",
                               "Dim", wrap=True))
        head.addLayout(titles, 1)
        head.addWidget(label("Auto-Tune ativo", "H3"))
        self.enable = ToggleSwitch(self.at.enabled)
        self.enable.setFixedSize(48, 26)
        self.enable.toggled.connect(self.at.set_enabled)
        head.addWidget(self.enable)
        root.addLayout(head)

        # ================================================= modo + presets
        bar = Card(padding=12)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.mode_group = QButtonGroup(self)
        for i, (key, text) in enumerate((("realtime", "Tempo real"), ("song", "Song Mode"))):
            b = QPushButton(text)
            b.setObjectName("BigToggle")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.mode_group.addButton(b, i)
            row.addWidget(b)
        self.mode_group.idClicked.connect(lambda i: self.at.set_source("realtime" if i == 0 else "song"))
        row.addSpacing(12)
        row.addWidget(label("Preset", "H3"))
        self.preset = QComboBox()
        self.preset.setMinimumWidth(200)
        self.preset.activated.connect(lambda i: self.at.load_preset(self.preset.itemData(i)))
        row.addWidget(self.preset)
        save = button("Salvar", "save")
        save.clicked.connect(self.at.save_preset)
        row.addWidget(save)
        save_as = button("Salvar como…", "copy")
        save_as.clicked.connect(self._save_as)
        row.addWidget(save_as)
        delete = tool_button("trash", "Excluir preset", 16, color="#F87171")
        delete.clicked.connect(self._delete_preset)
        row.addWidget(delete)
        row.addStretch(1)
        bar.body.addLayout(row)
        root.addWidget(bar)

        # ================================================= controles + afinador
        top = QHBoxLayout()
        top.setSpacing(14)
        controls = Card(padding=14)
        controls.setFixedWidth(360)
        controls.body.addWidget(label("Correção", "H3"))
        self.sliders: dict[str, ParamSlider] = {}
        for key, text, lo, hi, step, unit, dec, pct, tip in PARAM_UI:
            s = ParamSlider(text, lo, hi, DEFAULT_PARAMS[key], step, unit, dec, percent=pct)
            s.setToolTip(tip)
            s.valueChanged.connect(lambda v, k=key: self.at.set_params({k: v}))
            self.sliders[key] = s
            controls.body.addWidget(s)
        top.addWidget(controls)

        right = QVBoxLayout()
        right.setSpacing(14)
        keycard = Card(padding=14)
        krow = QHBoxLayout()
        krow.addWidget(label("Tonalidade", "H3"))
        self.key = QComboBox()
        for i, n in enumerate(NOTE_NAMES):
            self.key.addItem(n, i)
        self.key.activated.connect(lambda i: self.at.set_key(key=self.key.itemData(i)))
        krow.addWidget(self.key)
        self.scale = QComboBox()
        for k, (name, _) in SCALES.items():
            self.scale.addItem(name, k)
        self.scale.activated.connect(lambda i: self.at.set_key(scale=self.scale.itemData(i)))
        krow.addWidget(self.scale)
        self.detect_btn = button("Detectar pela voz", "mic",
                                 tooltip="Cante uma melodia por ~8 segundos para identificar a tonalidade.")
        self.detect_btn.clicked.connect(lambda: self.at.detect_key_from_voice(8.0))
        krow.addWidget(self.detect_btn)
        krow.addStretch(1)
        self.song_mode_label = label("Modo de correção", "H3")
        krow.addWidget(self.song_mode_label)
        self.song_mode = QComboBox()
        for k, text in CORRECTION_MODES.items():
            self.song_mode.addItem(text, k)
        self.song_mode.setToolTip("Scale: escala da música • Chord: prioriza notas do acorde atual • "
                                  "Melody: segue a melodia de referência (editável abaixo)")
        self.song_mode.activated.connect(lambda i: self.at.set_song_mode(self.song_mode.itemData(i)))
        krow.addWidget(self.song_mode)
        keycard.body.addLayout(krow)
        self.key_hint = label("", "Faint", wrap=True)
        keycard.body.addWidget(self.key_hint)
        right.addWidget(keycard)

        tune = Card(padding=12)
        self.tuner = TunerDisplay()
        tune.body.addWidget(self.tuner)
        self.graph = PitchGraph()
        self.graph.setMinimumHeight(190)
        tune.body.addWidget(self.graph, 1)
        right.addWidget(tune, 1)
        top.addLayout(right, 1)
        root.addLayout(top)

        # ================================================= Song Mode
        self.song_panel = Card(padding=14)
        sp = self.song_panel.body
        srow = QHBoxLayout()
        srow.addWidget(label("Música", "H2"))
        self.song_combo = QComboBox()
        self.song_combo.setMinimumWidth(260)
        self.song_combo.activated.connect(self._song_selected)
        srow.addWidget(self.song_combo, 1)
        imp = button("Importar música", "plus", accent=True)
        imp.clicked.connect(self._import_song)
        srow.addWidget(imp)
        for icon_name, tip, slot in (
            ("refresh", "Analisar novamente", lambda: self._with_song(self.at.analyze_song)),
            ("undo", "Restaurar análise automática (descarta edições)", lambda: self._with_song(self.at.restore_analysis)),
            ("music", "Importar melodia de referência (arquivo MIDI)", self._import_midi),
            ("edit", "Renomear", self._rename_song),
            ("trash", "Remover música", self._delete_song),
        ):
            b = tool_button(icon_name, tip, 16, color="#F87171" if icon_name == "trash" else None)
            b.clicked.connect(slot)
            srow.addWidget(b)
        sp.addLayout(srow)

        info = QHBoxLayout()
        info.setSpacing(18)
        self.info_bpm = label("BPM —", "H3")
        self.info_key = label("Tom —", "H3")
        self.info_scale = label("Escala —", "H3")
        self.info_chord = label("Acorde —", "H3")
        for w in (self.info_bpm, self.info_key, self.info_scale, self.info_chord):
            info.addWidget(w)
        edit_key = button("Corrigir tonalidade", "edit")
        edit_key.clicked.connect(self._edit_song_key)
        info.addWidget(edit_key)
        link = button("Vincular preset atual", "layers",
                      tooltip="Ao carregar esta música, o preset de Auto-Tune atual é aplicado automaticamente.")
        link.clicked.connect(self._link_preset)
        info.addWidget(link)
        info.addStretch(1)
        self.analysis_bar = QProgressBar()
        self.analysis_bar.setRange(0, 0)
        self.analysis_bar.setFixedWidth(140)
        self.analysis_bar.setFixedHeight(6)
        info.addWidget(self.analysis_bar)
        self.status = label("", "Faint")
        info.addWidget(self.status)
        sp.addLayout(info)
        self.warnings = label("", "Faint", wrap=True)
        sp.addWidget(self.warnings)

        trow = QHBoxLayout()
        trow.setSpacing(8)
        p = theme.current()
        self.play_btn = QPushButton()
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setProperty("accent", True)
        self.play_btn.setIcon(icons.icon("play", "#FFFFFF", 16))
        self.play_btn.clicked.connect(self._play_pause)
        trow.addWidget(self.play_btn)
        stop = button("", "stop", tooltip="Parar")
        stop.clicked.connect(self.at.stop)
        trow.addWidget(stop)
        self.time_label = label("0:00 / 0:00", "Value")
        trow.addWidget(self.time_label)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_released)
        trow.addWidget(self.seek, 1)
        vol_icon = QLabel()
        vol_icon.setPixmap(icons.pixmap("volume", p.text_dim, 16))
        trow.addWidget(vol_icon)
        self.music_vol = QSlider(Qt.Horizontal)
        self.music_vol.setRange(0, 150)
        self.music_vol.setFixedWidth(110)
        self.music_vol.setToolTip("Volume da música (monitor)")
        self.music_vol.setValue(int(float(ctl.settings.get("mixer.music_volume") or 0.8) * 100))
        self.music_vol.valueChanged.connect(lambda v: self.at.set_music_volume(v / 100))
        trow.addWidget(self.music_vol)
        self.to_virtual = QCheckBox("Enviar música ao microfone virtual")
        self.to_virtual.setToolTip("Desligado (recomendado): só você ouve a música; o Discord recebe apenas a voz.")
        self.to_virtual.setChecked(bool(ctl.settings.get("mixer.music_to_virtual")))
        self.to_virtual.toggled.connect(self.at.set_music_to_virtual)
        trow.addWidget(self.to_virtual)
        sp.addLayout(trow)

        zrow = QHBoxLayout()
        zrow.addWidget(label("Linha do tempo  •  clique na régua para posicionar  •  clique no piano roll para criar "
                             "notas de referência, arraste para mover/redimensionar, botão direito apaga  •  "
                             "duplo clique em acorde/tom para corrigir", "Faint", wrap=True), 1)
        self.snap = QCheckBox("Ajustar às batidas")
        self.snap.setChecked(True)
        zrow.addWidget(self.snap)
        self.follow = QCheckBox("Seguir reprodução")
        self.follow.setChecked(True)
        zrow.addWidget(self.follow)
        zrow.addWidget(label("Zoom", "Faint"))
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(10, 200)
        self.zoom.setValue(60)
        self.zoom.setFixedWidth(120)
        zrow.addWidget(self.zoom)
        sp.addLayout(zrow)

        self.timeline = SongTimeline()
        self.snap.toggled.connect(lambda on: setattr(self.timeline, "snap", on))
        self.zoom.valueChanged.connect(lambda v: self.timeline.set_zoom(float(v)))
        self.timeline.seekRequested.connect(self.at.seek)
        self.timeline.melodyEdited.connect(self._melody_edited)
        self.timeline.chordEditRequested.connect(self._edit_chord)
        self.timeline.keyEditRequested.connect(self._edit_key_segment)
        self.tl_scroll = QScrollArea()
        self.tl_scroll.setWidget(self.timeline)
        self.tl_scroll.setMinimumHeight(360)
        self.tl_scroll.setStyleSheet(f"QScrollArea {{ border: 1px solid {p.border}; border-radius: 8px; }}")
        sp.addWidget(self.tl_scroll)
        root.addWidget(self.song_panel)
        root.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 14, 18)
        outer.addWidget(scroll)

        # ================================================= sinais
        self.at.changed.connect(self.sync)
        self.at.presets_changed.connect(self._reload_presets)
        self.at.songs_changed.connect(self._reload_songs)
        self.at.song_loaded.connect(lambda _sid: (self._reload_songs(), self._load_timeline()))
        self.at.analysis_changed.connect(self._analysis_changed)
        self.at.key_learning.connect(self._key_learning)
        self._reload_presets()
        self._reload_songs()
        self.sync()
        last = ctl.settings.get("autotune.song_id")
        if last and self.at.songs.get(last):
            QTimer.singleShot(1500, lambda: self.at.load_song(last))

    # ================================================= sincronização da UI
    def sync(self) -> None:
        at = self.at
        self.enable.setCheckedSilently(at.enabled)
        song_mode = at.source == "song"
        self.mode_group.button(1 if song_mode else 0).setChecked(True)
        for k, s in self.sliders.items():
            v = at.params[k]
            if abs(s.value() - v) > 1e-6:
                s.blockSignals(True)
                s.setValue(v)
                s.blockSignals(False)
        self.key.setCurrentIndex(at.key)
        self.scale.setCurrentIndex(max(0, self.scale.findData(at.scale)))
        self.song_mode.setCurrentIndex(max(0, self.song_mode.findData(at.song_mode)))
        self.song_panel.setVisible(song_mode)
        self.song_mode.setVisible(song_mode)
        self.song_mode_label.setVisible(song_mode)
        for w in (self.key, self.scale, self.detect_btn):
            w.setEnabled(not song_mode)
        if song_mode:
            self.key_hint.setText("Song Mode: as notas permitidas vêm da tonalidade/acordes da música em cada instante "
                                  "(corrija a análise na linha do tempo, se necessário).")
        else:
            self.key_hint.setText("Tempo real: a voz é corrigida para a nota mais próxima da escala escolhida. "
                                  "Use Chromatic para corrigir para qualquer semitom.")
        idx = self.preset.findData(at.preset_id)
        self.preset.setCurrentIndex(idx if idx >= 0 else -1)

    def _reload_presets(self) -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        for pr in self.at.preset_list():
            self.preset.addItem(pr.name, pr.id)
        self.preset.setCurrentIndex(self.preset.findData(self.at.preset_id))
        self.preset.blockSignals(False)

    def _reload_songs(self) -> None:
        self.song_combo.blockSignals(True)
        self.song_combo.clear()
        status_txt = {"analyzing": " (analisando…)", "pending": " (na fila)", "error": " (erro na análise)"}
        for s in self.at.song_list():
            self.song_combo.addItem(f"{s.name}{status_txt.get(s.status, '')}", s.id)
        idx = self.song_combo.findData(self.at.current_song_id)
        self.song_combo.setCurrentIndex(idx)
        self.song_combo.blockSignals(False)
        self._update_info()

    def _update_info(self) -> None:
        song = self.at.current_song()
        a = song.analysis if song else None
        analyzing = bool(song and (song.status in ("analyzing", "pending")))
        self.analysis_bar.setVisible(analyzing)
        if not song:
            self.status.setText("Nenhuma música carregada")
        elif analyzing:
            self.status.setText("Analisando a música em segundo plano…")
        elif song.status == "error":
            self.status.setText(f"Erro na análise: {song.error}")
        else:
            self.status.setText("")
        if a:
            k = a.get("key", {})
            self.info_bpm.setText(f"{a.get('bpm', 0):.0f} BPM")
            manual = " (manual)" if k.get("manual") else f" ({k.get('confidence', 0) * 100:.0f}%)"
            self.info_key.setText(f"Tom: {NOTE_NAMES[k.get('tonic', 0)]}{manual}")
            self.info_scale.setText(f"Escala: {SCALES.get(k.get('scale', 'major'), ('?',))[0]}")
            mods = len(a.get("key_segments") or [])
            warn = list(a.get("warnings") or [])
            if mods > 1:
                warn.insert(0, f"{mods - 1} mudança(s) de tonalidade detectada(s).")
            if a.get("melody_source") == "estimated":
                warn.append("Melodia de referência estimada automaticamente — revise no piano roll antes de usar o "
                            "Melody Mode, ou importe um MIDI.")
            self.warnings.setText("  •  ".join(warn))
        else:
            for w, t in ((self.info_bpm, "BPM —"), (self.info_key, "Tom —"), (self.info_scale, "Escala —")):
                w.setText(t)
            self.warnings.setText("")

    def _load_timeline(self) -> None:
        song = self.at.current_song()
        self.timeline.set_analysis(copy.deepcopy(song.analysis) if song and song.analysis else None)
        self._update_info()

    def _analysis_changed(self, sid: int) -> None:
        if sid == self.at.current_song_id:
            self._load_timeline()
        self._reload_songs()

    def _key_learning(self, active: bool) -> None:
        self.detect_btn.setText("Ouvindo… cante" if active else "Detectar pela voz")
        self.detect_btn.setEnabled(not active and self.at.source != "song")

    # ================================================= ações
    def _save_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Novo preset de Auto-Tune", "Nome:")
        if ok and name.strip():
            self.at.create_preset(name.strip())
            self.sync()

    def _delete_preset(self) -> None:
        pid = self.at.preset_id
        p = self.at.presets.get(pid)
        if p and QMessageBox.question(self, "Excluir preset", f"Excluir “{p.name}”?") == QMessageBox.Yes:
            self.at.delete_preset(pid)

    def _with_song(self, fn) -> None:
        if self.at.current_song_id is not None:
            fn(self.at.current_song_id)

    def _song_selected(self, idx: int) -> None:
        sid = self.song_combo.itemData(idx)
        if sid is not None:
            self.at.load_song(sid)

    def _import_song(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar música ou instrumental", "", AUDIO_FILTER)
        if path:
            sid = self.at.import_song(path)
            if sid is not None:
                self.at.load_song(sid)
                self.ctl.notify.emit("info", "Música importada. Analisando BPM, tonalidade e acordes…")

    def _import_midi(self) -> None:
        if self.at.current_song_id is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Melodia de referência (MIDI)", "", "MIDI (*.mid *.midi)")
        if path:
            self.at.import_melody_midi(self.at.current_song_id, path)

    def _rename_song(self) -> None:
        song = self.at.current_song()
        if song:
            name, ok = QInputDialog.getText(self, "Renomear música", "Nome:", text=song.name)
            if ok and name.strip():
                self.at.rename_song(song.id, name.strip())

    def _delete_song(self) -> None:
        song = self.at.current_song()
        if song and QMessageBox.question(self, "Remover música", f"Remover “{song.name}”?") == QMessageBox.Yes:
            self.at.delete_song(song.id)
            self._load_timeline()

    def _link_preset(self) -> None:
        song = self.at.current_song()
        if song and self.at.preset_id:
            self.at.link_preset(song.id, self.at.preset_id)
            name = self.at.presets.get(self.at.preset_id).name
            self.ctl.notify.emit("success", f"Preset “{name}” vinculado a “{song.name}”")

    def _edit_song_key(self) -> None:
        song = self.at.current_song()
        if not song or not song.analysis:
            return
        k = song.analysis.get("key", {})
        dlg = KeyDialog(k.get("tonic", 0), k.get("scale", "major"), "Tonalidade da música",
                        "Substitui a tonalidade detectada (e as mudanças de tonalidade) pela informada.", self)
        if dlg.exec():
            self.at.set_song_key(song.id, *dlg.values())

    def _commit_timeline(self) -> None:
        sid = self.at.current_song_id
        if sid is not None and self.timeline.analysis is not None:
            self.at.update_analysis(sid, copy.deepcopy(self.timeline.analysis))

    def _melody_edited(self) -> None:
        a = self.timeline.analysis
        if a is not None:
            a["melody_source"] = "user"
        self._commit_timeline()

    def _edit_chord(self, i: int) -> None:
        a = self.timeline.analysis
        c = a["chords"][i]
        dlg = ChordDialog(c.get("root"), c.get("quality"), f"{fmt_time(c['start'])} – {fmt_time(c['end'])}", self)
        if dlg.exec():
            root, quality = dlg.values()
            c["root"], c["quality"], c["label"] = root, quality, chord_name(root, quality)
            c["notes"] = ([NOTE_NAMES[(root + iv) % 12] for iv in CHORD_QUALITIES[quality][1]]
                          if root is not None else [])
            c["manual"] = True
            self._commit_timeline()

    def _edit_key_segment(self, i: int) -> None:
        a = self.timeline.analysis
        k = a["key_segments"][i]
        dlg = KeyDialog(k["tonic"], k.get("scale", "major"), "Tonalidade do trecho",
                        f"{fmt_time(k['start'])} – {fmt_time(k['end'])}", self)
        if dlg.exec():
            tonic, scale = dlg.values()
            k.update({"tonic": tonic, "scale": scale, "name": key_name(tonic, scale), "manual": True})
            self._commit_timeline()

    def _play_pause(self) -> None:
        if self.at.transport()[2]:
            self.at.pause()
        else:
            self.at.play()

    def _seek_released(self) -> None:
        self._seeking = False
        _, dur, _ = self.at.transport()
        if dur > 0:
            self.at.seek(self.seek.value() / 1000 * dur)

    # ================================================= atualização periódica (30 fps)
    def tick(self, _levels: dict) -> None:
        tel = self.at.telemetry()
        if tel:
            active = tel.get("active")
            det = tel.get("detected") if active else None
            self.tuner.set_values(det, tel.get("target") if active else None,
                                  tel.get("output") if active else None,
                                  tel.get("chord") if self.at.source == "song" else "")
            self.graph.add(det, tel.get("output") if active else None, tel.get("allowed"))
        if self.at.source != "song":
            return
        pos, dur, playing = self.at.transport()
        self.play_btn.setIcon(icons.icon("pause" if playing else "play", "#FFFFFF", 16))
        self.play_btn.setToolTip("Pausar" if playing else "Tocar")
        self.time_label.setText(f"{fmt_time(pos)} / {fmt_time(dur)}")
        if not self._seeking and dur > 0:
            self.seek.blockSignals(True)
            self.seek.setValue(int(pos / dur * 1000))
            self.seek.blockSignals(False)
        self.timeline.set_position(pos)
        if playing and tel:
            self.timeline.add_trace(tel.get("song_time"), tel.get("detected"), tel.get("target"))
        if tel and tel.get("chord"):
            self.info_chord.setText(f"Acorde: {tel['chord']}")
        if playing and self.follow.isChecked():
            x = self.timeline.x_of(pos)
            bar = self.tl_scroll.horizontalScrollBar()
            view_w = self.tl_scroll.viewport().width()
            if not (bar.value() + 60 < x < bar.value() + view_w - 60):
                bar.setValue(int(x - view_w * 0.25))
