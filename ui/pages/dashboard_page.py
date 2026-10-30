"""Dashboard: categorias, grade do soundboard e painel de controle rápido."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from audio.audio_loader import SUPPORTED_EXTENSIONS
from core.app_controller import AppController
from ui import icons, theme
from ui.dialogs.category_dialog import CategoryDialog
from ui.dialogs.snippet_dialog import AUDIO_FILTER, SnippetDialog
from ui.widgets.common import Card, button, label, tool_button
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.level_meter import LevelMeter, lin_to_frac
from ui.widgets.param_slider import ParamSlider
from ui.widgets.snippet_button import MIME_SNIPPET, SnippetButton
from ui.widgets.toggle_switch import ToggleSwitch

FAV, ALL, NONE = "fav", "all", "none"


class CategoryList(QListWidget):
    """Lista de categorias que aceita snippets soltos sobre ela (mover de categoria)."""

    snippet_dropped = Signal(int, object)  # snippet_id, chave da categoria

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setIconSize(QSize(18, 18))
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasFormat(MIME_SNIPPET):
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        item = self.itemAt(e.position().toPoint())
        if e.mimeData().hasFormat(MIME_SNIPPET) and item and item.data(Qt.UserRole)[0] in ("cat", NONE):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e) -> None:
        item = self.itemAt(e.position().toPoint())
        if item and e.mimeData().hasFormat(MIME_SNIPPET):
            sid = int(bytes(e.mimeData().data(MIME_SNIPPET)).decode())
            self.snippet_dropped.emit(sid, item.data(Qt.UserRole))
            e.acceptProposedAction()


class SoundGrid(QWidget):
    """Área da grade: aceita arquivos arrastados do Explorer para importação."""

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.flow = FlowLayout(self, spacing=12)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if Path(u.toLocalFile()).suffix.lower() in SUPPORTED_EXTENSIONS]
        if paths:
            self.files_dropped.emit(paths)
            e.acceptProposedAction()


class ControlPanel(QWidget):
    """Coluna direita: microfone, voz, volumes e status."""

    def __init__(self, ctl: AppController, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        p = theme.current()
        self.setFixedWidth(284)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # --- Microfone
        mic = Card(padding=14)
        head = QHBoxLayout()
        self.mic_icon = QLabel()
        self.mic_icon.setPixmap(icons.pixmap("mic", p.text_dim, 18))
        head.addWidget(self.mic_icon)
        head.addWidget(label("Microfone", "H3"))
        head.addStretch(1)
        self.mic_activity = label("", "Faint")
        head.addWidget(self.mic_activity)
        mic.body.addLayout(head)
        self.mic_name = label("—", "Faint", wrap=True)
        mic.body.addWidget(self.mic_name)
        mic.body.addWidget(label("Entrada", "Faint"))
        self.in_meter = LevelMeter(thickness=8)
        mic.body.addWidget(self.in_meter)
        self.mute_btn = button("Microfone ativo", "mic")
        self.mute_btn.setObjectName("MuteButton")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setMinimumHeight(40)
        self.mute_btn.clicked.connect(lambda checked: ctl.set_muted(checked))
        mic.body.addWidget(self.mute_btn)
        root.addWidget(mic)

        # --- Voz
        voice = Card(padding=14)
        vh = QHBoxLayout()
        vi = QLabel()
        vi.setPixmap(icons.pixmap("wave", p.text_dim, 18))
        vh.addWidget(vi)
        vh.addWidget(label("Modificador de voz", "H3"))
        vh.addStretch(1)
        self.voice_toggle = ToggleSwitch(ctl.voice_enabled)
        self.voice_toggle.toggled.connect(ctl.set_voice_enabled)
        vh.addWidget(self.voice_toggle)
        voice.body.addLayout(vh)
        self.preset_combo = QComboBox()
        self.preset_combo.activated.connect(self._preset_selected)
        voice.body.addWidget(self.preset_combo)
        voice.body.addWidget(label("Saída (voz + sons)", "Faint"))
        self.out_meter = LevelMeter(thickness=8)
        voice.body.addWidget(self.out_meter)
        root.addWidget(voice)

        # --- Volumes
        vol = Card(padding=14)
        vol.body.addWidget(label("Volume", "H3"))
        self.sliders: dict[str, ParamSlider] = {}
        for key, text in (("mixer.master_volume", "Geral (saída)"),
                          ("mixer.soundboard_volume", "Soundboard"),
                          ("mixer.mic_volume", "Microfone")):
            s = ParamSlider(text, 0.0, 2.0, ctl.volume(key), percent=True)
            s.valueChanged.connect(lambda v, k=key: ctl.set_volume(k, v))
            self.sliders[key] = s
            vol.body.addWidget(s)
        root.addWidget(vol)

        # --- Status
        status = Card(padding=14)
        sh = QHBoxLayout()
        self.status_dot = QLabel("●")
        sh.addWidget(self.status_dot)
        self.status_text = label("Iniciando…", "H3")
        sh.addWidget(self.status_text, 1)
        status.body.addLayout(sh)
        self.status_detail = label("", "Faint", wrap=True)
        status.body.addWidget(self.status_detail)
        root.addWidget(status)
        root.addStretch(1)

        ctl.mute_changed.connect(self._sync_mute)
        ctl.voice_enabled_changed.connect(self.voice_toggle.setCheckedSilently)
        ctl.presets_changed.connect(self.reload_presets)
        ctl.active_preset_changed.connect(lambda _id: self.reload_presets())
        ctl.mixer_changed.connect(self._sync_volumes)
        ctl.engine_status.connect(self.set_status)
        self._sync_mute(ctl.muted)
        self.reload_presets()
        self.set_status(ctl.status)

    def _sync_mute(self, muted: bool) -> None:
        p = theme.current()
        self.mute_btn.setChecked(muted)
        self.mute_btn.setText("Microfone mutado" if muted else "Microfone ativo")
        self.mute_btn.setIcon(icons.icon("mic-off" if muted else "mic", "#F87171" if muted else p.text, 18))

    def _sync_volumes(self) -> None:
        for key, s in self.sliders.items():
            if abs(s.value() - self.ctl.volume(key)) > 1e-3:
                s.setValue(self.ctl.volume(key))

    def reload_presets(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for pr in self.ctl.preset_list():
            self.preset_combo.addItem(pr.name, pr.id)
        idx = self.preset_combo.findData(self.ctl.active_preset_id)
        self.preset_combo.setCurrentIndex(max(0, idx))
        self.preset_combo.blockSignals(False)

    def _preset_selected(self, idx: int) -> None:
        pid = self.preset_combo.itemData(idx)
        if pid is not None:
            self.ctl.load_preset(pid)

    def set_status(self, st) -> None:
        colors = {"running": "#22C55E", "degraded": "#F59E0B", "starting": "#3B82F6",
                  "error": "#EF4444", "stopped": "#64748B"}
        texts = {"running": "Áudio funcionando", "degraded": "Funcionando com avisos",
                 "starting": "Iniciando…", "error": "Erro no áudio", "stopped": "Áudio parado"}
        self.status_dot.setStyleSheet(f"color: {colors.get(st.state, '#64748B')}; font-size: 14pt;")
        self.status_text.setText(texts.get(st.state, st.state))
        lines = []
        if st.state in ("running", "degraded"):
            lines.append(f"Saída virtual: {st.virtual_name or 'não encontrada'}")
            lines.append(f"Monitor: {st.monitor_name or 'desativado'}")
            lines.append(f"{st.samplerate} Hz • bloco {st.blocksize} • ~{st.latency_ms:.0f} ms")
        if st.state == "error":
            lines.append(st.message)
        self.status_detail.setText("\n".join(lines))
        self.mic_name.setText(st.input_name or "Nenhum microfone ativo")

    def tick(self, levels: dict) -> None:
        self.in_meter.set_level(levels.get("input", 0.0))
        self.out_meter.set_level(levels.get("output", 0.0))
        frac = lin_to_frac(levels.get("input", 0.0))
        active = frac > 0.35 and not self.ctl.muted
        self.mic_activity.setText("● falando" if active else ("mutado" if self.ctl.muted else ""))
        self.mic_activity.setStyleSheet(f"color: {'#22C55E' if active else theme.current().text_faint};")


class DashboardPage(QWidget):
    def __init__(self, ctl: AppController, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctl = ctl
        self.buttons: dict[int, SnippetButton] = {}
        self.current_key: tuple = (ALL, None)
        p = theme.current()

        # ---------------- categorias
        self.cat_panel = QFrame()
        self.cat_panel.setFixedWidth(220)
        cat_lay = QVBoxLayout(self.cat_panel)
        cat_lay.setContentsMargins(0, 0, 0, 0)
        cat_lay.setSpacing(8)
        ch = QHBoxLayout()
        ch.addWidget(label("Categorias", "H3"))
        ch.addStretch(1)
        add_cat = tool_button("plus", "Nova categoria", 16)
        add_cat.clicked.connect(self._new_category)
        ch.addWidget(add_cat)
        cat_lay.addLayout(ch)
        self.cat_list = CategoryList()
        self.cat_list.currentItemChanged.connect(self._category_changed)
        self.cat_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cat_list.customContextMenuRequested.connect(self._category_menu)
        self.cat_list.snippet_dropped.connect(self._snippet_to_category)
        self.cat_list.itemDoubleClicked.connect(lambda it: self._edit_category(it))
        cat_lay.addWidget(self.cat_list, 1)
        cat_lay.addWidget(label("Arraste sons para uma categoria para movê-los.", "Faint", wrap=True))

        # ---------------- centro
        center = QVBoxLayout()
        center.setSpacing(12)
        head = QHBoxLayout()
        self.title = label("Todos os sons", "H1")
        head.addWidget(self.title)
        self.count = label("", "Badge")
        head.addWidget(self.count)
        head.addStretch(1)
        center.addLayout(head)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Pesquisar sons…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", p.text_faint, 16), QLineEdit.LeadingPosition)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self.reload_grid)
        self.search.textChanged.connect(lambda: self._search_timer.start())
        tools.addWidget(self.search, 1)
        add = button("Adicionar sons", "plus", accent=True)
        add.clicked.connect(self._add_files)
        tools.addWidget(add)
        stop = button("Parar tudo", "stop-all", danger=True, tooltip="Interromper todos os sons")
        stop.clicked.connect(ctl.stop_all)
        tools.addWidget(stop)
        center.addLayout(tools)

        self.grid = SoundGrid()
        self.grid.files_dropped.connect(self._import)
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setAlignment(Qt.AlignCenter)
        ei = QLabel()
        ei.setPixmap(icons.pixmap("inbox", p.text_faint, 48))
        ei.setAlignment(Qt.AlignCenter)
        el.addWidget(ei)
        self.empty_text = label("Nenhum som aqui ainda", "H2")
        self.empty_text.setAlignment(Qt.AlignCenter)
        el.addWidget(self.empty_text)
        hint = label("Clique em “Adicionar sons” ou arraste arquivos WAV, MP3, OGG ou FLAC para cá.", "Dim")
        hint.setAlignment(Qt.AlignCenter)
        el.addWidget(hint)

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 6, 0)
        cl.addWidget(self.grid)
        cl.addWidget(self.empty)
        cl.addStretch(1)
        container.setAcceptDrops(True)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(container)
        center.addWidget(self.scroll, 1)

        # ---------------- direita
        self.controls = ControlPanel(ctl)

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(20)
        root.addWidget(self.cat_panel)
        root.addLayout(center, 1)
        root.addWidget(self.controls)

        ctl.library_changed.connect(self._library_changed)
        self.reload_categories()
        self._select_saved_category()

        self._play_timer = QTimer(self)
        self._play_timer.setInterval(33)
        self._play_timer.timeout.connect(self._update_playing)
        self._play_timer.start()

    # ---------------------------------------------------------------- responsivo
    def resizeEvent(self, e) -> None:
        w = self.width()
        self.controls.setVisible(w >= 1080)
        self.cat_panel.setFixedWidth(220 if w >= 900 else 170)
        super().resizeEvent(e)

    # ---------------------------------------------------------------- categorias
    def reload_categories(self) -> None:
        p = theme.current()
        counts = self.ctl.library.count_by_category()
        total = sum(counts.values())
        favs = len(self.ctl.library.snippets(favorites_only=True))
        self.cat_list.blockSignals(True)
        self.cat_list.clear()

        def add(text: str, key: tuple, icon_text: str | None = None, icon_name: str | None = None, n: int = 0):
            it = QListWidgetItem(f"{icon_text + '  ' if icon_text else ''}{text}")
            it.setData(Qt.UserRole, key)
            if icon_name:
                it.setIcon(icons.icon(icon_name, p.text_dim, 18))
            it.setToolTip(f"{n} som(ns)")
            self.cat_list.addItem(it)
            return it

        add("Todos os sons", (ALL, None), icon_name="grid", n=total)
        add("Favoritos", (FAV, None), icon_name="star", n=favs)
        for c in self.ctl.library.categories():
            add(c.name, ("cat", c.id), icon_text=c.icon, n=counts.get(c.id, 0))
        if counts.get(None):
            add("Sem categoria", (NONE, None), icon_name="folder", n=counts.get(None, 0))
        # restaura seleção
        for i in range(self.cat_list.count()):
            if tuple(self.cat_list.item(i).data(Qt.UserRole)) == tuple(self.current_key):
                self.cat_list.setCurrentRow(i)
                break
        else:
            self.cat_list.setCurrentRow(0)
            self.current_key = (ALL, None)
        self.cat_list.blockSignals(False)

    def _select_saved_category(self) -> None:
        saved = self.ctl.settings.get("ui.last_category", "all")
        if isinstance(saved, list) and len(saved) == 2:
            self.current_key = tuple(saved)
            self.reload_categories()
        self.reload_grid()

    def _category_changed(self, item, _prev) -> None:
        if item is None:
            return
        self.current_key = tuple(item.data(Qt.UserRole))
        self.ctl.settings.set("ui.last_category", list(self.current_key))
        self.reload_grid()

    def _category_menu(self, pos) -> None:
        item = self.cat_list.itemAt(pos)
        if not item or item.data(Qt.UserRole)[0] != "cat":
            menu = QMenu(self)
            menu.addAction(icons.icon("plus", theme.current().text, 16), "Nova categoria", self._new_category)
            menu.exec(self.cat_list.mapToGlobal(pos))
            return
        cid = item.data(Qt.UserRole)[1]
        p = theme.current()
        menu = QMenu(self)
        menu.addAction(icons.icon("edit", p.text, 16), "Editar…", lambda: self._edit_category(item))
        menu.addAction(icons.icon("chevron-up", p.text, 16), "Mover para cima", lambda: self._move_category(cid, -1))
        menu.addAction(icons.icon("chevron-down", p.text, 16), "Mover para baixo", lambda: self._move_category(cid, 1))
        menu.addSeparator()
        menu.addAction(icons.icon("trash", "#F87171", 16), "Excluir categoria…", lambda: self._delete_category(cid))
        menu.exec(self.cat_list.mapToGlobal(pos))

    def _new_category(self) -> None:
        dlg = CategoryDialog(parent=self)
        if dlg.exec():
            cid = self.ctl.create_category(*dlg.values())
            self.current_key = ("cat", cid)
            self.reload_categories()
            self.reload_grid()

    def _edit_category(self, item) -> None:
        key = item.data(Qt.UserRole)
        if key[0] != "cat":
            return
        c = self.ctl.library.category(key[1])
        dlg = CategoryDialog(c.name, c.icon, c.color, "Editar categoria", self)
        if dlg.exec():
            self.ctl.update_category(c.id, *dlg.values())

    def _move_category(self, cid: int, step: int) -> None:
        ids = [c.id for c in self.ctl.library.categories()]
        i = ids.index(cid)
        j = i + step
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            self.ctl.reorder_categories(ids)

    def _delete_category(self, cid: int) -> None:
        c = self.ctl.library.category(cid)
        n = len(self.ctl.library.snippets(category_id=cid))
        box = QMessageBox(self)
        box.setWindowTitle("Excluir categoria")
        box.setText(f"Excluir a categoria “{c.name}”?")
        if n:
            box.setInformativeText(f"Ela contém {n} som(ns). O que deseja fazer com eles?")
            keep = box.addButton("Manter sons (sem categoria)", QMessageBox.AcceptRole)
            delete = box.addButton("Excluir sons também", QMessageBox.DestructiveRole)
        else:
            keep = box.addButton("Excluir", QMessageBox.AcceptRole)
            delete = None
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked in (keep, delete) and clicked is not None:
            self.current_key = (ALL, None)
            self.ctl.delete_category(cid, delete_snippets=clicked is delete)

    def _snippet_to_category(self, sid: int, key) -> None:
        key = tuple(key)
        target = key[1] if key[0] == "cat" else None
        self.ctl.move_snippet(sid, target)
        self.ctl.notify.emit("success", "Som movido")

    # ---------------------------------------------------------------- grade
    def _library_changed(self) -> None:
        self.reload_categories()
        self.reload_grid()

    def _visible_snippets(self):
        kind, cid = self.current_key
        search = self.search.text()
        lib = self.ctl.library
        if kind == FAV:
            return lib.snippets(favorites_only=True, search=search)
        if kind == "cat":
            return lib.snippets(category_id=cid, search=search)
        if kind == NONE:
            return lib.snippets(uncategorized=True, search=search)
        return lib.snippets(search=search)

    def reload_grid(self) -> None:
        kind, cid = self.current_key
        if kind == "cat":
            c = self.ctl.library.category(cid)
            self.title.setText(f"{c.icon}  {c.name}" if c else "Categoria")
        else:
            self.title.setText({ALL: "Todos os sons", FAV: "Favoritos", NONE: "Sem categoria"}[kind])

        snippets = self._visible_snippets()
        size = int(self.ctl.settings.get("soundboard.button_size", 120))
        flow = self.grid.flow
        existing = self.buttons
        self.buttons = {}
        while flow.count():
            flow.takeAt(0)
        for s in snippets:
            btn = existing.pop(s.id, None)
            if btn is None or btn._size != size:
                if btn:
                    btn.deleteLater()
                btn = SnippetButton(s, size)
                btn.clicked.connect(self.ctl.play_snippet)
                btn.context_requested.connect(self._snippet_menu)
                btn.dropped_on.connect(self._reorder_drop)
            else:
                btn.set_snippet(s)
            self.buttons[s.id] = btn
            flow.addWidget(btn)
            btn.show()
        for btn in existing.values():
            btn.deleteLater()
        self.grid.updateGeometry()
        self.count.setText(str(len(snippets)))
        self.grid.setVisible(bool(snippets))
        self.empty.setVisible(not snippets)
        if not snippets and self.search.text():
            self.empty_text.setText("Nenhum som encontrado")
        else:
            self.empty_text.setText("Nenhum som aqui ainda")

    def _update_playing(self) -> None:
        if not self.isVisible():
            return
        playing = self.ctl.playing()
        for sid, btn in self.buttons.items():
            info = playing.get(sid)
            btn.set_progress(info[0] if info else None, info[1] if info else False)

    def _reorder_drop(self, dragged: int, target: int) -> None:
        ids = list(self.buttons.keys())
        if dragged not in ids or target not in ids:
            return
        ids.remove(dragged)
        ids.insert(ids.index(target) if ids.index(target) >= 0 else len(ids), dragged)
        self.ctl.reorder_snippets(ids)

    def _current_category_id(self) -> int | None:
        kind, cid = self.current_key
        return cid if kind == "cat" else None

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Adicionar sons", "", AUDIO_FILTER)
        if paths:
            self._import(paths)

    def _import(self, paths: list[str]) -> None:
        ok, errors = self.ctl.import_files(paths, self._current_category_id())
        if ok and self.current_key[0] == FAV:
            self.ctl.notify.emit("info", "Sons adicionados em “Todos os sons” (não favoritados)")
        if ok:
            self.ctl.notify.emit("success", f"{ok} som(ns) adicionado(s)")
        if errors:
            QMessageBox.warning(self, "Alguns arquivos não foram importados", "\n".join(errors))

    def _snippet_menu(self, sid: int, pos) -> None:
        s = self.ctl.snippet(sid)
        if not s:
            return
        p = theme.current()
        menu = QMenu(self)
        menu.addAction(icons.icon("play", p.text, 16), "Tocar", lambda: self.ctl.play_snippet(sid))
        menu.addAction(icons.icon("headphones", p.text, 16), "Prévia (só no monitor)",
                       lambda: self.ctl.play_snippet(sid, preview=True))
        menu.addAction(icons.icon("stop", p.text, 16), "Parar", lambda: self.ctl.stop_snippet(sid))
        menu.addSeparator()
        menu.addAction(icons.icon("edit", p.text, 16), "Editar…", lambda: self._edit_snippet(sid))
        menu.addAction(icons.icon("edit", p.text, 16), "Renomear…", lambda: self._rename_snippet(sid))
        fav = menu.addAction(icons.icon("star", "#FBBF24", 16, filled=s.favorite),
                             "Remover dos favoritos" if s.favorite else "Favoritar")
        fav.triggered.connect(lambda: self.ctl.update_snippet(sid, favorite=not s.favorite))
        loop = menu.addAction(icons.icon("repeat", p.text, 16), "Repetir (loop)")
        loop.setCheckable(True)
        loop.setChecked(s.loop)
        loop.triggered.connect(lambda checked: self.ctl.update_snippet(sid, loop=checked))
        move = menu.addMenu(icons.icon("folder", p.text, 16), "Mover para")
        move.addAction("Sem categoria", lambda: self.ctl.move_snippet(sid, None))
        for c in self.ctl.library.categories():
            act = move.addAction(f"{c.icon}  {c.name}", lambda cid=c.id: self.ctl.move_snippet(sid, cid))
            act.setEnabled(c.id != s.category_id)
        menu.addAction(icons.icon("upload", p.text, 16), "Substituir arquivo…", lambda: self._replace_file(sid))
        menu.addSeparator()
        menu.addAction(icons.icon("trash", "#F87171", 16), "Remover", lambda: self._delete_snippet(sid))
        menu.exec(pos)

    def _edit_snippet(self, sid: int) -> None:
        SnippetDialog(self.ctl, sid, self).exec()

    def _rename_snippet(self, sid: int) -> None:
        s = self.ctl.snippet(sid)
        name, ok = QInputDialog.getText(self, "Renomear", "Novo nome:", text=s.name)
        if ok and name.strip():
            self.ctl.update_snippet(sid, name=name.strip())

    def _replace_file(self, sid: int) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Substituir arquivo de áudio", "", AUDIO_FILTER)
        if path:
            self.ctl.replace_snippet_file(sid, path)

    def _delete_snippet(self, sid: int) -> None:
        s = self.ctl.snippet(sid)
        if QMessageBox.question(self, "Remover som", f"Remover “{s.name}” da biblioteca?") == QMessageBox.Yes:
            self.ctl.delete_snippet(sid)

    def tick(self, levels: dict) -> None:
        if self.controls.isVisible():
            self.controls.tick(levels)
