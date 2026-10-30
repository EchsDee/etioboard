"""Pitch Shift (granular de baixa latência) e Formant Shift (STFT com envelope cepstral)."""
from __future__ import annotations

import numpy as np

from effects.base import Effect, ParamSpec, arange
from effects.dsp_utils import DelayLine


class PitchShift(Effect):
    """Pitch shifter por linha de atraso modulada com dois "grãos" sobrepostos.

    É a técnica usada em harmonizadores de hardware: latência média de meia janela
    (~12 ms com a janela padrão), custo baixo e vetorizado. Quando um grão reinicia
    (ganho zero), seu ponto de leitura é alinhado por correlação cruzada com o outro
    grão (estilo SOLA), evitando cancelamento de fase e o som "metálico".
    """

    effect_id = "pitch_shift"
    display_name = "Pitch Shift"
    description = "Altera a altura (tom) da voz em semitons."
    params_spec = (
        ParamSpec("semitones", "Semitons", -12.0, 12.0, 0.0, 0.1, "st", 1),
        ParamSpec("window_ms", "Janela", 15.0, 60.0, 25.0, 1.0, "ms", 0),
        ParamSpec("mix", "Mix", 0.0, 1.0, 1.0, 0.01, "", 2),
    )
    MAX_WINDOW_S = 0.065

    def configure(self) -> None:
        self.ratio = 2.0 ** (self.params["semitones"] / 12.0)
        self.window = max(16, int(self.params["window_ms"] / 1000.0 * self.sr))
        self.latency_s = self.window / 2 / self.sr if abs(self.ratio - 1) > 1e-4 else 0.0

    def reset(self) -> None:
        self.max_shift = int(self.sr / 70.0)        # busca de alinhamento: até 1 período de 70 Hz
        self.corr_len = int(0.008 * self.sr)        # janela de correlação de 8 ms
        self.line = DelayLine(
            int(self.MAX_WINDOW_S * self.sr) + self.max_shift + self.corr_len + self.blocksize * 8
        )
        self.phase = 0.0
        self.delta = [0.0, 0.0]

    def _buf_segment(self, end: int, length: int) -> np.ndarray:
        idx = (np.arange(end - length, end, dtype=np.int64)) & self.line.mask
        return self.line.buf[idx]

    def _align(self, sample_abs: int, base_delay: float, other_delay: float) -> float:
        """Escolhe o deslocamento extra (>= 0) do grão que reinicia para coincidir com o outro."""
        L, P = self.corr_len, self.max_shift
        ref_end = int(round(sample_abs - other_delay))
        ref = self._buf_segment(ref_end, L)
        energy_ref = float(np.dot(ref, ref))
        if energy_ref < 1e-7:
            return 0.0  # silêncio: qualquer alinhamento serve
        base_end = int(round(sample_abs - base_delay))
        search = self._buf_segment(base_end, L + P)
        corr = np.correlate(search, ref, mode="valid")  # índice j -> segmento termina em base_end-P+j
        csum = np.concatenate(([0.0], np.cumsum(search * search)))
        energy = csum[L:] - csum[:-L]
        score = corr / np.sqrt(energy * energy_ref + 1e-12)
        delta_candidates = P - np.arange(len(score))
        score = score - 0.15 * (delta_candidates / P)  # prefere atrasos menores (menos latência)
        j = int(np.argmax(score))
        return float(delta_candidates[j])

    def process_block(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        self.line.write(x)
        mix = self.params["mix"]
        if abs(self.ratio - 1.0) < 1e-4 or mix <= 0.0:
            return x.copy()
        w = self.window
        step = (1.0 - self.ratio) / w
        steps = step * (arange(n) + 1.0)
        phases, deltas, events = [], [], []
        for t, offset in enumerate((0.0, 0.5)):
            start = (self.phase + offset) % 1.0
            p = (start + steps) % 1.0
            prev = np.empty(n)
            prev[0] = start
            prev[1:] = p[:-1]
            for i in np.nonzero(np.abs(p - prev) > 0.5)[0]:
                events.append((int(i), t))
            phases.append(p)
            deltas.append(np.full(n, self.delta[t]))
        if events:
            block_start = self.line.w - n
            for i, t in sorted(events):
                o = 1 - t
                other_delay = phases[o][i] * w + 1.0 + deltas[o][i]
                d = self._align(block_start + i, phases[t][i] * w + 1.0, other_delay)
                deltas[t][i:] = d
                self.delta[t] = d
        self.phase = float(phases[0][-1])
        out = np.zeros(n)
        for t in (0, 1):
            p = phases[t]
            wet = self.line.read_fractional(p * w + 1.0 + deltas[t], n)
            out += wet * np.sin(np.pi * p) ** 2
        if mix < 1.0:
            out = x * (1.0 - mix) + out * mix
        return out


class FormantShift(Effect):
    """Desloca as formantes (ressonâncias do trato vocal) sem alterar o tom.

    STFT com janela de ~21 ms e hop de 1/4; o envelope espectral é estimado por
    cepstro suavizado e "esticado" pelo fator de deslocamento.
    """

    effect_id = "formant_shift"
    display_name = "Formant Shift"
    description = "Altera a ressonância/timbre da voz (mais grave ou mais fina) sem mudar o tom."
    params_spec = (
        ParamSpec("shift", "Deslocamento", -12.0, 12.0, 0.0, 0.1, "st", 1),
        ParamSpec("mix", "Mix", 0.0, 1.0, 1.0, 0.01, "", 2),
    )

    def configure(self) -> None:
        self.factor = 2.0 ** (self.params["shift"] / 12.0)
        if not hasattr(self, "N"):
            self.N = 1024 if self.sr >= 32000 else 512
            self.hop = self.N // 4
            self.win = np.hanning(self.N + 1)[:-1]
            # Normalização do overlap-add (janela de análise * síntese = hann², hop N/4 -> soma 1.5)
            self.ola_norm = 1.0 / 1.5
            self.lifter = max(8, int(self.sr / 700.0))
            self.bins = np.arange(self.N // 2 + 1, dtype=np.float64)
        self.src_bins = self.bins / self.factor
        self.latency_s = (self.N - self.hop) / self.sr

    def reset(self) -> None:
        n = self.N
        self.in_fifo = np.zeros(n)
        self.out_fifo = np.zeros(n)
        self.out_acc = np.zeros(2 * n)
        self.rover = n - self.hop

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        spec = np.fft.rfft(frame * self.win)
        mag = np.abs(spec) + 1e-9
        log_mag = np.log(mag)
        cep = np.fft.irfft(log_mag, self.N)
        L = self.lifter
        cep[L : self.N - L + 1] = 0.0
        env = np.fft.rfft(cep).real
        warped = np.interp(self.src_bins, self.bins, env)
        corr = np.exp(np.clip(warped - env, -6.0, 6.0))
        out = np.fft.irfft(spec * corr, self.N)
        return out * self.win * self.ola_norm

    def process_block(self, x: np.ndarray) -> np.ndarray:
        n_total = len(x)
        y = np.empty(n_total)
        N, hop = self.N, self.hop
        latency = N - hop
        pos = 0
        while pos < n_total:
            k = min(n_total - pos, N - self.rover)
            r = self.rover
            self.in_fifo[r : r + k] = x[pos : pos + k]
            y[pos : pos + k] = self.out_fifo[r - latency : r - latency + k]
            self.rover += k
            pos += k
            if self.rover >= N:
                self.rover = latency
                self.out_acc[:N] += self._process_frame(self.in_fifo)
                self.out_fifo[:hop] = self.out_acc[:hop]
                self.out_acc[: 2 * N - hop] = self.out_acc[hop:]
                self.out_acc[2 * N - hop :] = 0.0
                self.in_fifo[:latency] = self.in_fifo[hop:]
        mix = self.params["mix"]
        if mix < 1.0:
            # o sinal seco precisa do mesmo atraso para não gerar filtragem em pente
            return y * mix + self._delayed_dry(x) * (1.0 - mix)
        return y

    def _delayed_dry(self, x: np.ndarray) -> np.ndarray:
        if not hasattr(self, "_dry_line"):
            self._dry_line = DelayLine(self.N + self.blocksize * 8)
        self._dry_line.write(x)
        return self._dry_line.read_fixed(self.N - self.hop + len(x), len(x))
