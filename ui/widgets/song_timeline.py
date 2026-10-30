"""Linha do tempo musical do Song Mode: régua/batidas, seções, tonalidade, acordes e piano roll.

Piano roll editável (melodia de referência):
  * clique em área vazia: cria uma nota (arraste para definir a duração)
  * arraste uma nota: move no tempo e na altura; arraste a borda direita: redimensiona
  * botão direito numa nota: apaga
  * duplo clique num acorde ou tonalidade: edita
  * clique na régua: posiciona a reprodução
"""
from __future__ import annotations

import bisect
from collections import deque

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from autotune.music import CHORD_QUALITIES, scale_pitch_classes
from ui import theme

RULER_H, SECTION_H, KEY_H, CHORD_H = 22, 20, 20, 28
LANES_H = RULER_H + SECTION_H + KEY_H + CHORD_H
KEYS_W = 38
MIDI_LO, MIDI_HI = 40, 84
ROW_H = 9
EDGE_PX = 6


def _hue_color(pc: int, alpha: int = 255, light: int = 125) -> QColor:
    c = QColor.fromHsl(int(pc * 30) % 360, 150, light)
    c.setAlpha(alpha)
    return c


class SongTimeline(QWidget):
    seekRequested = Signal(float)
    melodyEdited = Signal()
    chordEditRequested = Signal(int)
    keyEditRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.analysis: dict | None = None
        self.pps = 60.0                    # pixels por segundo (zoom)
        self.position = 0.0
        self.snap = True
        self.trace: deque[tuple[float, float | None, float | None]] = deque(maxlen=6000)
        self._drag = None                  # (modo, índice, offset_t, offset_midi, start_original)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._resize()

    # ------------------------------------------------------------------ dados
    def set_analysis(self, analysis: dict | None) -> None:
        self.analysis = analysis
        self.trace.clear()
        self._resize()
        self.update()

    def set_zoom(self, pps: float) -> None:
        self.pps = pps
        self._resize()
        self.update()

    def set_position(self, t: float) -> None:
        if abs(t - self.position) > 1e-3:
            self.position = t
            self.update()

    def add_trace(self, t: float | None, detected: float | None, target: float | None) -> None:
        if t is None:
            return
        if self.trace and t < self.trace[-1][0] - 0.5:  # voltou no tempo (seek/stop)
            self.trace.clear()
        self.trace.append((t, detected, target))

    @property
    def duration(self) -> float:
        return float(self.analysis.get("duration", 0.0)) if self.analysis else 0.0

    def _resize(self) -> None:
        w = KEYS_W + int(max(self.duration, 10.0) * self.pps) + 20
        h = LANES_H + (MIDI_HI - MIDI_LO + 1) * ROW_H + 2
        self.setFixedSize(QSize(w, h))

    # ------------------------------------------------------------------ geometria
    def x_of(self, t: float) -> float:
        return KEYS_W + t * self.pps

    def t_of(self, x: float) -> float:
        return max(0.0, (x - KEYS_W) / self.pps)

    def y_of_midi(self, m: float) -> float:
        return LANES_H + (MIDI_HI - m) * ROW_H

    def midi_of(self, y: float) -> int:
        return int(max(MIDI_LO, min(MIDI_HI, MIDI_HI - (y - LANES_H) // ROW_H)))

    def _snap(self, t: float) -> float:
        beats = self.analysis.get("beats") if self.analysis else None
        if not self.snap or not beats:
            return round(t, 3)
        # grade de 1/2 batida
        i = bisect.bisect_left(beats, t)
        cands = []
        for j in (i - 1, i):
            if 0 <= j < len(beats):
                cands.append(beats[j])
                if j + 1 < len(beats):
                    cands.append((beats[j] + beats[j + 1]) / 2)
        return min(cands, key=lambda b: abs(b - t)) if cands else t

    def _beat_len(self, t: float) -> float:
        beats = self.analysis.get("beats") if self.analysis else None
        if not beats or len(beats) < 2:
            return 0.5
        i = min(max(bisect.bisect_left(beats, t), 1), len(beats) - 1)
        return beats[i] - beats[i - 1]

    def _melody(self) -> list[dict]:
        return self.analysis.setdefault("melody", []) if self.analysis else []

    def _note_at(self, pos: QPointF) -> tuple[int, str] | None:
        for i, n in enumerate(self._melody()):
            r = QRectF(self.x_of(n["start"]), self.y_of_midi(n["midi"]),
                       max(3.0, (n["end"] - n["start"]) * self.pps), ROW_H)
            if r.contains(pos):
                return i, ("resize" if pos.x() > r.right() - EDGE_PX else "move")
        return None

    def _segment_at(self, key: str, t: float) -> int | None:
        for i, s in enumerate(self.analysis.get(key) or []):
            if s["start"] <= t < s["end"]:
                return i
        return None

    # ------------------------------------------------------------------ pintura
    def paintEvent(self, e) -> None:
        p = theme.current()
        g = QPainter(self)
        g.setRenderHint(QPainter.Antialiasing)
        vis = e.rect()
        t0, t1 = self.t_of(vis.left() - 50), self.t_of(vis.right() + 50)
        g.fillRect(vis, QColor(p.surface2))
        small = QFont(self.font())
        small.setPixelSize(10)
        bold = QFont(self.font())
        bold.setPixelSize(11)
        bold.setWeight(QFont.DemiBold)
        g.setFont(small)
        if not self.analysis:
            g.setPen(QColor(p.text_faint))
            g.drawText(QRectF(vis), Qt.AlignCenter, "Importe e selecione uma música para ver a análise")
            return
        a = self.analysis
        roll_bottom = self.height()

        # --- fundo do piano roll: linhas de teclas pretas
        for m in range(MIDI_LO, MIDI_HI + 1):
            y = self.y_of_midi(m)
            if m % 12 in (1, 3, 6, 8, 10):
                g.fillRect(QRectF(KEYS_W, y, self.width() - KEYS_W, ROW_H), QColor(0, 0, 0, 40 if p.name == "dark" else 18))
        # --- notas permitidas por acorde (destaque das linhas de notas do acorde em cada trecho)
        for c in a.get("chords") or []:
            if c["end"] < t0 or c["start"] > t1 or c.get("root") is None:
                continue
            pcs = {(c["root"] + iv) % 12 for iv in CHORD_QUALITIES[c["quality"]][1]}
            x0, x1 = self.x_of(c["start"]), self.x_of(c["end"])
            for m in range(MIDI_LO, MIDI_HI + 1):
                if m % 12 in pcs:
                    g.fillRect(QRectF(x0, self.y_of_midi(m), x1 - x0, ROW_H), _hue_color(c["root"], 38))
        # --- grade de batidas
        beats = a.get("beats") or []
        lo_i, hi_i = bisect.bisect_left(beats, t0), bisect.bisect_right(beats, t1)
        for k, b in enumerate(beats[lo_i:hi_i], start=lo_i):
            x = self.x_of(b)
            strong = k % 4 == 0
            g.setPen(QPen(QColor(p.border if not strong else p.text_faint), 1))
            g.drawLine(QPointF(x, RULER_H if strong else LANES_H), QPointF(x, roll_bottom))

        # --- régua
        g.fillRect(QRectF(vis.left(), 0, vis.width(), RULER_H), QColor(p.surface))
        step = 1 if self.pps >= 60 else (5 if self.pps >= 15 else 10)
        g.setPen(QColor(p.text_dim))
        for s in range(int(t0) // step * step, int(t1) + step, step):
            x = self.x_of(s)
            g.drawLine(QPointF(x, RULER_H - 6), QPointF(x, RULER_H))
            g.drawText(QRectF(x + 3, 2, 60, 14), Qt.AlignLeft, f"{s // 60}:{s % 60:02d}")

        def lane(items, y, h, label_fn, color_fn, font):
            g.setFont(font)
            for it in items:
                if it["end"] < t0 or it["start"] > t1:
                    continue
                r = QRectF(self.x_of(it["start"]) + 1, y + 2, (it["end"] - it["start"]) * self.pps - 2, h - 4)
                g.setPen(Qt.NoPen)
                g.setBrush(color_fn(it))
                g.drawRoundedRect(r, 4, 4)
                g.setPen(QColor("#FFFFFF"))
                g.drawText(r.adjusted(5, 0, -3, 0), Qt.AlignVCenter | Qt.AlignLeft, label_fn(it))

        lane(a.get("sections") or [], RULER_H, SECTION_H,
             lambda s: f"Seção {s['label']}  ·  {' '.join(s.get('notes', [])[:3])}",
             lambda s: QColor.fromHsl((ord(s["label"][0]) * 47) % 360, 60, 70), small)
        lane(a.get("key_segments") or [], RULER_H + SECTION_H, KEY_H, lambda k: k["name"],
             lambda k: _hue_color(k["tonic"], 255, 80), small)
        lane(a.get("chords") or [], RULER_H + SECTION_H + KEY_H, CHORD_H, lambda c: c["label"],
             lambda c: _hue_color(c["root"], 255, 95) if c.get("root") is not None else QColor(p.surface3), bold)

        # --- notas da melodia de referência
        g.setFont(small)
        for n in self._melody():
            if n["end"] < t0 or n["start"] > t1:
                continue
            r = QRectF(self.x_of(n["start"]), self.y_of_midi(n["midi"]) + 1,
                       max(3.0, (n["end"] - n["start"]) * self.pps), ROW_H - 2)
            g.setPen(QPen(QColor(p.accent).lighter(130), 1))
            g.setBrush(QColor(p.accent))
            g.drawRoundedRect(r, 2, 2)

        # --- trilha da voz (detectada) e alvo
        if self.trace:
            for idx, color, width in ((1, "#9CA3AF", 1.5), (2, "#22C55E", 2.0)):
                path = QPainterPath()
                started = False
                prev_t = None
                for pt in self.trace:
                    v = pt[idx]
                    if v is None or prev_t is None or pt[0] - prev_t > 0.15:
                        started = False
                    prev_t = pt[0]
                    if v is None or not (MIDI_LO <= v <= MIDI_HI + 1):
                        continue
                    q = QPointF(self.x_of(pt[0]), self.y_of_midi(v) + ROW_H / 2)
                    if started:
                        path.lineTo(q)
                    else:
                        path.moveTo(q)
                        started = True
                g.setPen(QPen(QColor(color), width))
                g.setBrush(Qt.NoBrush)
                g.drawPath(path)

        # --- teclado (fixo à esquerda da área visível)
        kx = max(0, vis.left())
        g.fillRect(QRectF(kx, LANES_H, KEYS_W, roll_bottom - LANES_H), QColor(p.surface))
        key = a.get("key") or {}
        scale_pcs = scale_pitch_classes(int(key.get("tonic", 0)), key.get("scale", "major"))
        for m in range(MIDI_LO, MIDI_HI + 1):
            y = self.y_of_midi(m)
            black = m % 12 in (1, 3, 6, 8, 10)
            g.fillRect(QRectF(kx, y, KEYS_W - 2, ROW_H - 1), QColor("#2A2F40" if black else "#D9DCE5"))
            if m % 12 in scale_pcs:
                g.fillRect(QRectF(kx + KEYS_W - 5, y, 3, ROW_H - 1), QColor(p.accent))
            if m % 12 == 0:
                g.setPen(QColor("#111318"))
                g.drawText(QRectF(kx + 2, y - 1, KEYS_W, ROW_H + 2), Qt.AlignLeft | Qt.AlignVCenter, f"C{m // 12 - 1}")
        g.setPen(QColor(p.text_faint))
        g.drawText(QRectF(kx, RULER_H, KEYS_W, SECTION_H), Qt.AlignCenter, "Seção")
        g.drawText(QRectF(kx, RULER_H + SECTION_H, KEYS_W, KEY_H), Qt.AlignCenter, "Tom")
        g.drawText(QRectF(kx, RULER_H + SECTION_H + KEY_H, KEYS_W, CHORD_H), Qt.AlignCenter, "Acorde")

        # --- cursor de reprodução
        x = self.x_of(self.position)
        g.setPen(QPen(QColor("#F43F5E"), 2))
        g.drawLine(QPointF(x, 0), QPointF(x, roll_bottom))

    # ------------------------------------------------------------------ interação
    def mousePressEvent(self, e) -> None:
        if not self.analysis:
            return
        pos = e.position()
        t = self.t_of(pos.x())
        if pos.y() < RULER_H:
            self.seekRequested.emit(t)
            return
        if pos.y() < LANES_H:
            return
        hit = self._note_at(pos)
        if e.button() == Qt.RightButton:
            if hit:
                self._melody().pop(hit[0])
                self.update()
                self.melodyEdited.emit()
            return
        if e.button() != Qt.LeftButton:
            return
        mel = self._melody()
        if hit:
            i, mode = hit
            n = mel[i]
            self._drag = (mode, i, t - n["start"], self.midi_of(pos.y()) - n["midi"])
        else:
            start = self._snap(t)
            note = {"start": round(start, 3), "end": round(start + self._beat_len(start), 3),
                    "midi": self.midi_of(pos.y())}
            mel.append(note)
            mel.sort(key=lambda n: n["start"])
            self._drag = ("resize", mel.index(note), 0.0, 0)
        self.update()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if self._drag is None:
            hit = self._note_at(pos) if pos.y() >= LANES_H else None
            self.setCursor(Qt.SizeHorCursor if hit and hit[1] == "resize" else
                           (Qt.OpenHandCursor if hit else (Qt.PointingHandCursor if pos.y() < RULER_H else Qt.ArrowCursor)))
            return
        mode, i, dt, dm = self._drag
        mel = self._melody()
        if not (0 <= i < len(mel)):
            return
        n = mel[i]
        t = self.t_of(pos.x())
        if mode == "move":
            length = n["end"] - n["start"]
            start = self._snap(t - dt)
            n["start"], n["end"] = round(start, 3), round(start + length, 3)
            n["midi"] = int(max(MIDI_LO, min(MIDI_HI, self.midi_of(pos.y()) - dm)))
        else:
            n["end"] = round(max(n["start"] + 0.05, self._snap(t) if self.snap else t), 3)
        self.update()

    def mouseReleaseEvent(self, _e) -> None:
        if self._drag is not None:
            self._drag = None
            self._melody().sort(key=lambda n: n["start"])
            self.melodyEdited.emit()

    def mouseDoubleClickEvent(self, e) -> None:
        if not self.analysis:
            return
        pos = e.position()
        t = self.t_of(pos.x())
        if RULER_H + SECTION_H <= pos.y() < RULER_H + SECTION_H + KEY_H:
            i = self._segment_at("key_segments", t)
            if i is not None:
                self.keyEditRequested.emit(i)
        elif RULER_H + SECTION_H + KEY_H <= pos.y() < LANES_H:
            i = self._segment_at("chords", t)
            if i is not None:
                self.chordEditRequested.emit(i)

    def sizeHint(self) -> QSize:
        return self.size()

