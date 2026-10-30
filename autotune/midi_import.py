"""Leitor mínimo de arquivos MIDI (SMF formato 0/1) para importar uma melodia de referência."""
from __future__ import annotations

import struct
from pathlib import Path


class MidiError(Exception):
    pass


def _varlen(data: bytes, i: int) -> tuple[int, int]:
    value = 0
    while True:
        b = data[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i


def read_notes(path: str | Path) -> list[dict]:
    """Retorna notas [{start, end, midi, channel}] em segundos (respeita mudanças de tempo)."""
    data = Path(path).read_bytes()
    if data[:4] != b"MThd":
        raise MidiError("Não é um arquivo MIDI válido.")
    _fmt, ntracks, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise MidiError("MIDI com divisão SMPTE não é suportado.")
    pos = 8 + struct.unpack(">I", data[4:8])[0]
    events: list[tuple[int, int, int, int, int]] = []  # (tick, ordem, tipo, a, b)
    tempos: list[tuple[int, int]] = [(0, 500000)]
    for _ in range(ntracks):
        if data[pos:pos + 4] != b"MTrk":
            break
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        i, end = pos + 8, pos + 8 + length
        tick, status = 0, 0
        while i < end:
            delta, i = _varlen(data, i)
            tick += delta
            b = data[i]
            if b & 0x80:
                status = b
                i += 1
            if status == 0xFF:
                mtype = data[i]
                ln, i = _varlen(data, i + 1)
                if mtype == 0x51 and ln == 3:
                    tempos.append((tick, int.from_bytes(data[i:i + 3], "big")))
                i += ln
            elif status in (0xF0, 0xF7):
                ln, i = _varlen(data, i)
                i += ln
            else:
                kind, ch = status & 0xF0, status & 0x0F
                if kind in (0xC0, 0xD0):
                    i += 1
                else:
                    a, v = data[i], data[i + 1]
                    i += 2
                    if kind == 0x90 and v > 0:
                        events.append((tick, 1, ch, a, 1))
                    elif kind == 0x80 or (kind == 0x90 and v == 0):
                        events.append((tick, 0, ch, a, 0))
        pos = end
    tempos.sort()

    def tick_to_s(t: int) -> float:
        sec, last_tick, tempo = 0.0, 0, tempos[0][1]
        for tt, tp in tempos[1:]:
            if tt >= t:
                break
            sec += (tt - last_tick) * tempo / 1e6 / division
            last_tick, tempo = tt, tp
        return sec + (t - last_tick) * tempo / 1e6 / division

    open_notes: dict[tuple[int, int], int] = {}
    notes = []
    for tick, _order, ch, note, on in sorted(events):
        if ch == 9:  # bateria
            continue
        key = (ch, note)
        if on:
            open_notes[key] = tick
        elif key in open_notes:
            t0 = open_notes.pop(key)
            notes.append({"start": tick_to_s(t0), "end": tick_to_s(tick), "midi": note, "channel": ch})
    if not notes:
        raise MidiError("Nenhuma nota encontrada no arquivo.")
    return sorted(notes, key=lambda n: n["start"])


def melody_line(notes: list[dict]) -> list[dict]:
    """Reduz notas polifônicas a uma linha (nota mais aguda em cada instante, 'skyline')."""
    out: list[dict] = []
    for n in sorted(notes, key=lambda n: (n["start"], -n["midi"])):
        if out and n["start"] < out[-1]["end"]:
            if n["midi"] <= out[-1]["midi"]:
                continue
            out[-1]["end"] = n["start"]
            if out[-1]["end"] - out[-1]["start"] < 0.03:
                out.pop()
        out.append({"start": round(n["start"], 3), "end": round(n["end"], 3), "midi": int(n["midi"])})
    return out
