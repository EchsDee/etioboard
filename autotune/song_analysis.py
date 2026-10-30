"""Análise musical offline de uma música/instrumental.

Gera um "mapa musical": BPM e batidas, tonalidade global e mudanças de tonalidade,
escala, acordes por segmento (com notas do acorde e da tonalidade), estrutura
(seções) e uma melodia de referência estimada.

Executado em um processo separado (ProcessPoolExecutor) para não disputar o GIL com
a thread de áudio. Só usa NumPy/SciPy.
"""
from __future__ import annotations

import math

import numpy as np
import soundfile as sf
from numpy.lib.stride_tricks import sliding_window_view
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import find_peaks, resample_poly

from autotune.music import (
    CHORD_QUALITIES,
    NOTE_NAMES,
    chord_name,
    key_name,
    key_scores,
    scale_pitch_classes,
)

SR = 22050
ANALYSIS_VERSION = 1


# =============================================================================== básicos
def load_mono(path: str) -> np.ndarray:
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    y = data.mean(axis=1)
    if sr != SR:
        g = math.gcd(int(sr), SR)
        y = resample_poly(y, SR // g, sr // g).astype(np.float32)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    return y / peak if peak > 0 else y


def stft_mag(y: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    pad = np.pad(y, (n_fft // 2, n_fft // 2))
    frames = sliding_window_view(pad, n_fft)[::hop]
    win = np.hanning(n_fft).astype(np.float32)
    out = np.empty((len(frames), n_fft // 2 + 1), dtype=np.float32)
    for i in range(0, len(frames), 256):
        out[i:i + 256] = np.abs(np.fft.rfft(frames[i:i + 256] * win, axis=1))
    return out


def viterbi(log_emit: np.ndarray, log_trans: np.ndarray) -> np.ndarray:
    """Caminho mais provável. log_emit: (T, S); log_trans: (S, S)."""
    T, S = log_emit.shape
    delta = log_emit[0].copy()
    back = np.zeros((T, S), dtype=np.int32)
    for t in range(1, T):
        scores = delta[:, None] + log_trans
        back[t] = np.argmax(scores, axis=0)
        delta = scores[back[t], np.arange(S)] + log_emit[t]
    path = np.empty(T, dtype=np.int32)
    path[-1] = int(np.argmax(delta))
    for t in range(T - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


def sticky_transitions(n_states: int, p_stay: float) -> np.ndarray:
    m = np.full((n_states, n_states), (1 - p_stay) / (n_states - 1))
    np.fill_diagonal(m, p_stay)
    return np.log(m)


# =============================================================================== croma
NOTE_LO, NOTE_HI = 28, 96          # E1..C7: notas candidatas
_LOGF_RES = 3                      # bins por semitom no espectro log-frequência
_LOGF_LO, _LOGF_HI = 24, 112


def _logfreq_matrix(n_fft: int) -> np.ndarray:
    """Matriz (bins STFT -> bins log-frequência), interpolação triangular."""
    freqs = np.fft.rfftfreq(n_fft, 1 / SR)
    centers = np.arange(_LOGF_LO * _LOGF_RES, _LOGF_HI * _LOGF_RES) / _LOGF_RES
    midi = 69 + 12 * np.log2(np.maximum(freqs, 1e-9) / 440.0)
    width = 1.0 / _LOGF_RES
    w = np.maximum(0.0, 1.0 - np.abs(midi[:, None] - centers[None, :]) / width)
    w[freqs < 25] = 0
    return w.astype(np.float32)


def _note_dictionary() -> np.ndarray:
    """Perfis harmônicos (notas x bins log-frequência): fundamental + 8 harmônicos decrescentes."""
    centers = np.arange(_LOGF_LO * _LOGF_RES, _LOGF_HI * _LOGF_RES) / _LOGF_RES
    notes = np.arange(NOTE_LO, NOTE_HI + 1)
    D = np.zeros((len(notes), len(centers)), dtype=np.float32)
    for i, n in enumerate(notes):
        for h in range(1, 9):
            pos = n + 12 * math.log2(h)
            D[i] += (0.75 ** (h - 1)) * np.maximum(0.0, 1.0 - np.abs(centers - pos) * _LOGF_RES / 1.5)
    return D / (np.linalg.norm(D, axis=1, keepdims=True) + 1e-9)


def note_activations(mag: np.ndarray, n_fft: int, iters: int = 40) -> np.ndarray:
    """Transcrição aproximada: decompõe o espectro em notas com harmônicos (NMF com dicionário fixo).

    Diferente de um croma ingênuo, os harmônicos de uma nota não são contados como outras notas.
    Retorna ativações (frames x notas NOTE_LO..NOTE_HI).
    """
    X = mag @ _logfreq_matrix(n_fft)                       # (T, F)
    X = X / (X.max() + 1e-9)
    D = _note_dictionary()                                 # (N, F)
    H = np.full((X.shape[0], D.shape[0]), 0.1, dtype=np.float32)
    DDt = D @ D.T
    XDt = X @ D.T
    for _ in range(iters):                                 # atualizações multiplicativas (euclidiana)
        H *= XDt / (H @ DDt + 1e-9)
    return H


def chroma_from_notes(H: np.ndarray, lo: int = NOTE_LO, hi: int = NOTE_HI) -> np.ndarray:
    notes = np.arange(NOTE_LO, NOTE_HI + 1)
    sel = (notes >= lo) & (notes <= hi)
    chroma = np.zeros((H.shape[0], 12), dtype=np.float32)
    for pc in range(12):
        chroma[:, pc] = H[:, sel & (notes % 12 == pc)].sum(axis=1)
    return chroma


# =============================================================================== ritmo
def onset_envelope(y: np.ndarray, hop: int = 512) -> np.ndarray:
    mag = stft_mag(y, 2048, hop)
    logm = np.log1p(1000.0 * mag)
    flux = np.maximum(np.diff(logm, axis=0, prepend=logm[:1]), 0.0).sum(axis=1)
    flux = flux - uniform_filter1d(flux, 16)
    flux = np.maximum(flux, 0.0)
    return flux / (flux.std() + 1e-9)


def estimate_tempo(onset: np.ndarray, fps: float) -> float:
    o = onset - onset.mean()
    n = 1 << int(np.ceil(np.log2(2 * len(o))))
    ac = np.fft.irfft(np.abs(np.fft.rfft(o, n)) ** 2, n)[: len(o)]
    bpms = np.arange(60.0, 200.0, 0.5)
    lags = 60.0 * fps / bpms
    vals = np.interp(lags, np.arange(len(ac)), ac)
    prior = np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)
    return float(bpms[int(np.argmax(vals * prior))])


def track_beats(onset: np.ndarray, fps: float, bpm: float, tightness: float = 100.0) -> np.ndarray:
    """Rastreamento de batidas por programação dinâmica (Ellis, 2007): segue variações de andamento."""
    period = 60.0 * fps / bpm
    window = np.arange(-int(round(2 * period)), -int(round(period / 2)) + 1)
    txcost = -tightness * np.log(-window / period) ** 2
    local = onset / (onset.std() + 1e-9)
    score = local.copy()
    back = np.full(len(local), -1)
    for i in range(len(local)):
        idx = i + window
        ok = idx >= 0
        if not ok.any():
            continue
        cand = score[idx[ok]] + txcost[ok]
        j = int(np.argmax(cand))
        if cand[j] > 0:
            score[i] = local[i] + cand[j]
            back[i] = idx[ok][j]
    tail = max(1, int(period))
    i = len(score) - tail + int(np.argmax(score[-tail:]))
    beats = []
    while i >= 0:
        beats.append(i)
        i = back[i]
    return np.array(beats[::-1], dtype=float) / fps


# =============================================================================== harmonia
_TEMPLATES: list[tuple[int, str, np.ndarray]] = []
for _root in range(12):
    for _q, (_suffix, _ints) in CHORD_QUALITIES.items():
        _v = np.zeros(12)
        for _k, _i in enumerate(_ints):
            _v[(_root + _i) % 12] = 1.0 if _k < 3 else 0.6
        _TEMPLATES.append((_root, _q, _v / np.linalg.norm(_v)))


def recognize_chords(beat_chroma: np.ndarray, beat_energy: np.ndarray,
                     beat_bass: np.ndarray | None = None) -> list[tuple[int | None, str | None]]:
    S = len(_TEMPLATES) + 1
    norm = beat_chroma / (np.linalg.norm(beat_chroma, axis=1, keepdims=True) + 1e-9)
    tmpl = np.array([t[2] for t in _TEMPLATES])
    sims = norm @ tmpl.T                                  # (T, 48)
    # tétrades só ganham de tríades com evidência clara da sétima
    sims[:, [i for i, t in enumerate(_TEMPLATES) if t[1] in ("7", "m7")]] -= 0.06
    if beat_bass is not None:                             # o baixo costuma tocar a fundamental do acorde
        bass = beat_bass / (beat_bass.max(axis=1, keepdims=True) + 1e-9)
        roots = np.array([t[0] for t in _TEMPLATES])
        sims += 0.15 * bass[:, roots]
    no_chord = np.where(beat_energy < 0.08, 1.0, 0.55)[:, None]
    emit = np.concatenate([sims, no_chord], axis=1) * 12.0
    path = viterbi(emit, sticky_transitions(S, 0.85))
    return [(_TEMPLATES[s][0], _TEMPLATES[s][1]) if s < len(_TEMPLATES) else (None, None) for s in path]


def harmonic_minor_check(chroma_sum: np.ndarray, tonic: int) -> str:
    raised, natural = chroma_sum[(tonic + 11) % 12], chroma_sum[(tonic + 10) % 12]
    return "harmonic_minor" if raised > natural * 1.15 else "minor"


def key_path(beat_chroma: np.ndarray, beat_times: np.ndarray, duration: float):
    win, hop = 16, 4
    T = len(beat_chroma)
    if T < win:
        return []
    starts = list(range(0, T - win + 1, hop))
    scores = np.array([key_scores(beat_chroma[s:s + win].sum(axis=0)) for s in starts])
    path = viterbi(scores * 10.0, sticky_transitions(24, 0.97))
    segs = []
    for i, k in enumerate(path):
        t0 = beat_times[starts[i]] if i else 0.0
        if segs and segs[-1][2] == k:
            continue
        segs.append([t0, None, int(k)])
    for i in range(len(segs)):
        segs[i][1] = segs[i + 1][0] if i + 1 < len(segs) else duration
    # funde trechos curtos (< 12 s) ao vizinho: não são modulações reais
    merged = []
    for s in segs:
        if merged and (s[1] - s[0] < 12.0 or s[2] == merged[-1][2]):
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return merged


# =============================================================================== estrutura
def find_sections(features: np.ndarray, beat_times: np.ndarray, duration: float) -> list[dict]:
    T = len(features)
    if T < 32:
        return [{"start": 0.0, "end": duration, "label": "A"}]
    f = features / (np.linalg.norm(features, axis=1, keepdims=True) + 1e-9)
    ssm = f @ f.T
    k = 8
    kernel = np.ones((2 * k, 2 * k))
    kernel[:k, k:] = -1
    kernel[k:, :k] = -1
    kernel *= np.outer(np.hanning(2 * k), np.hanning(2 * k))
    nov = np.zeros(T)
    padded = np.pad(ssm, k, mode="edge")
    for i in range(T):
        nov[i] = np.sum(padded[i:i + 2 * k, i:i + 2 * k] * kernel)
    nov = np.maximum(nov, 0)
    peaks, _ = find_peaks(nov, distance=16, height=np.percentile(nov, 75))
    bounds = [0] + [int(p) for p in peaks if 8 <= p <= T - 8] + [T]
    sections, means = [], []
    for a, b in zip(bounds, bounds[1:]):
        means.append(f[a:b].mean(axis=0))
    labels: list[str] = []
    for i, m in enumerate(means):
        label = None
        for j in range(i):
            if np.dot(m, means[j]) / (np.linalg.norm(m) * np.linalg.norm(means[j]) + 1e-9) > 0.97:
                label = labels[j]
                break
        labels.append(label or chr(ord("A") + len(set(labels))))
    for (a, b), lab in zip(zip(bounds, bounds[1:]), labels):
        t0 = 0.0 if a == 0 else float(beat_times[a])
        t1 = duration if b >= T else float(beat_times[b])
        if sections and sections[-1]["label"] == lab:
            sections[-1]["end"] = t1
        else:
            sections.append({"start": t0, "end": t1, "label": lab})
    return sections


# =============================================================================== melodia
def extract_melody(y: np.ndarray) -> list[dict]:
    """Melodia predominante (estimativa) por saliência harmônica + Viterbi. Deve ser revisada."""
    hop, n_fft = 512, 4096
    mag = stft_mag(y, n_fft, hop)
    fps = SR / hop
    freqs_per_bin = SR / n_fft
    notes = np.arange(48, 85)  # C3..C6
    sal = np.zeros((len(mag), len(notes)), dtype=np.float32)
    mag_max = maximum_filter1d(mag, 3, axis=1)
    for h in range(1, 7):
        bins = np.round(440.0 * 2 ** ((notes - 69) / 12) * h / freqs_per_bin).astype(int)
        ok = bins < mag.shape[1]
        sal[:, ok] += (0.8 ** (h - 1)) * mag_max[:, bins[ok]]
    sal *= np.where((notes >= 55) & (notes <= 79), 1.15, 1.0)  # faixa típica de voz
    sal = np.log1p(sal)
    frame_max = sal.max(axis=1)
    voiced = frame_max > np.percentile(frame_max, 35)
    S = len(notes) + 1
    emit = np.full((len(sal), S), -1e9)
    norm = sal / (frame_max[:, None] + 1e-9)
    emit[:, :-1] = np.where(voiced[:, None], norm * 8.0, -4.0)
    emit[:, -1] = np.where(voiced, 2.0, 6.0)
    jump = np.abs(notes[:, None] - notes[None, :])
    trans = np.zeros((S, S))
    trans[:-1, :-1] = -0.6 * np.minimum(jump, 12)
    trans[:-1, -1] = trans[-1, :-1] = -3.0
    path = viterbi(emit, trans)
    out, start = [], 0
    for i in range(1, len(path) + 1):
        if i == len(path) or path[i] != path[start]:
            if path[start] < len(notes) and (i - start) >= int(0.12 * fps):
                out.append({"start": round(start / fps, 3), "end": round(i / fps, 3),
                            "midi": int(notes[path[start]])})
            start = i
    return out


# =============================================================================== principal
def analyze(path: str) -> dict:
    y = load_mono(path)
    duration = len(y) / SR
    warnings: list[str] = []

    # --- ritmo
    hop_on = 512
    fps = SR / hop_on
    onset = onset_envelope(y, hop_on)
    bpm = estimate_tempo(onset, fps)
    beats = track_beats(onset, fps, bpm)
    if len(beats) > 8:
        bpm = float(60.0 / np.median(np.diff(beats)))
    else:
        warnings.append("Batidas pouco claras; acordes analisados em janelas fixas.")
        beats = np.arange(0.0, duration, 0.5)
    beat_times = np.concatenate(([0.0], beats[beats > 0.05]))

    # --- transcrição aproximada -> croma (sem harmônicos) e croma do baixo, sincronizados às batidas
    hop_c, n_fft_c = 2048, 8192
    mag = stft_mag(y, n_fft_c, hop_c)
    H = note_activations(mag, n_fft_c)
    chroma_raw = chroma_from_notes(H)
    bass_raw = chroma_from_notes(H, NOTE_LO, 52)
    energy = mag.sum(axis=1)
    energy = energy / (energy.max() + 1e-9)
    chroma = chroma_raw / (chroma_raw.max(axis=1, keepdims=True) + 1e-9)
    times = np.arange(len(chroma)) * hop_c / SR
    edges = np.concatenate((beat_times, [duration]))
    seg_idx = np.clip(np.searchsorted(edges, times, side="right") - 1, 0, len(beat_times) - 1)
    nb = len(beat_times)
    beat_chroma = np.zeros((nb, 12))
    beat_bass = np.zeros((nb, 12))
    beat_energy = np.zeros(nb)
    counts = np.bincount(seg_idx, minlength=nb).astype(float)
    np.add.at(beat_chroma, seg_idx, chroma_raw)
    np.add.at(beat_bass, seg_idx, bass_raw)
    np.add.at(beat_energy, seg_idx, energy)
    beat_energy = beat_energy / np.maximum(counts, 1)
    beat_chroma = beat_chroma / np.maximum(beat_chroma.max(axis=1, keepdims=True), 1e-9)

    # --- tonalidade global e local
    total = chroma_raw.sum(axis=0)
    ks = key_scores(total)
    best = int(np.argmax(ks))
    tonic, mode = best % 12, ("major" if best < 12 else "minor")
    if mode == "minor":
        mode = harmonic_minor_check(total, tonic)
    order = np.sort(ks)[::-1]
    confidence = float(np.clip((order[0] - order[1]) * 5 + max(order[0], 0) * 0.5, 0, 1))
    if confidence < 0.35:
        warnings.append("Tonalidade incerta; confira e ajuste manualmente se necessário.")
    key_segments = []
    for t0, t1, k in key_path(beat_chroma, beat_times, duration):
        m = "major" if k < 12 else "minor"
        key_segments.append({"start": round(t0, 3), "end": round(t1, 3), "tonic": k % 12, "scale": m,
                             "name": key_name(k % 12, m)})
    if not key_segments:
        key_segments = [{"start": 0.0, "end": duration, "tonic": tonic, "scale": mode,
                         "name": key_name(tonic, mode)}]
    elif len(key_segments) > 1:
        # Com modulações, a tonalidade global é a que ocupa mais tempo (não a "média" das tonalidades).
        span: dict[tuple[int, str], float] = {}
        for k in key_segments:
            span[(k["tonic"], k["scale"])] = span.get((k["tonic"], k["scale"]), 0.0) + k["end"] - k["start"]
        tonic, mode = max(span, key=span.get)
        if mode == "minor":
            mode = harmonic_minor_check(total, tonic)

    # --- acordes
    chords_raw = recognize_chords(beat_chroma, beat_energy, beat_bass)
    chords = []
    for i, (root, quality) in enumerate(chords_raw):
        t0, t1 = float(edges[i]), float(edges[i + 1])
        label = chord_name(root, quality)
        if chords and chords[-1]["label"] == label:
            chords[-1]["end"] = round(t1, 3)
            continue
        chords.append({"start": round(t0, 3), "end": round(t1, 3), "root": root, "quality": quality,
                       "label": label})
    for i, c in enumerate(chords):
        ksg = next((k for k in key_segments if k["start"] <= c["start"] < k["end"]), key_segments[-1])
        c["notes"] = ([NOTE_NAMES[(c["root"] + iv) % 12] for iv in CHORD_QUALITIES[c["quality"]][1]]
                      if c["root"] is not None else [])
        c["scale_notes"] = [NOTE_NAMES[p] for p in sorted(scale_pitch_classes(ksg["tonic"], ksg["scale"]))]
        c["change"] = i > 0

    # --- estrutura e notas predominantes
    feats = np.concatenate([beat_chroma, beat_energy[:, None] * 2.0], axis=1)
    sections = find_sections(feats, beat_times, duration)
    for s in sections:
        sel = (times >= s["start"]) & (times < s["end"])
        prof = (chroma[sel] * energy[sel, None]).sum(axis=0) if sel.any() else np.zeros(12)
        s["notes"] = [NOTE_NAMES[p] for p in np.argsort(prof)[::-1][:4]]

    melody = extract_melody(y)

    return {
        "version": ANALYSIS_VERSION,
        "duration": round(duration, 3),
        "bpm": round(bpm, 1),
        "beats": [round(float(b), 3) for b in beats],
        "key": {"tonic": tonic, "scale": mode, "name": key_name(tonic, mode), "confidence": round(confidence, 2)},
        "key_segments": key_segments,
        "chords": chords,
        "sections": sections,
        "melody": melody,
        "melody_source": "estimated",
        "warnings": warnings,
    }

