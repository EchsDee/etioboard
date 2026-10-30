"""Motor de áudio.

Fluxo:  Microfone → InputStream → [ring] → thread DSP (voz + soundboard + mixer)
        → [ring] → OutputStream (cabo virtual)  e  → [ring] → OutputStream (monitor/fones)

* Callbacks do PortAudio só copiam memória (sem processamento pesado).
* A thread de DSP é "relogada" pelo microfone; sem microfone, pelo consumo da saída.
* Um supervisor monitora os streams e reabre tudo automaticamente se um dispositivo
  for desconectado, sem bloquear a interface.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
import sounddevice as sd

from audio.audio_loader import SampleCache
from audio.audio_mixer import AudioMixer
from audio.device_manager import DeviceInfo, DeviceManager
from audio.ring_buffer import RingBuffer
from audio.song_player import SongPlayer
from audio.soundboard_player import SoundboardPlayer
from audio.test_recorder import TestRecorder
from audio.voice_processor import VoiceProcessor

log = logging.getLogger(__name__)

LATENCY_MODES = {
    # modo: (latência sugerida ao PortAudio, blocos de pré-buffer)
    "low": ("low", 1),
    "balanced": ("low", 2),
    "safe": ("high", 4),
}
MAX_EXTRA_BLOCKS = 4
INPUT_STALL_S = 1.5
RECOVERY_INTERVAL_S = 3.0


@dataclass(frozen=True)
class EngineConfig:
    hostapi: str | None = None
    input_device: str | None = None
    input_hostapi: str | None = None   # None = mesma API das saídas
    virtual_device: str | None = None
    virtual_enabled: bool = True
    monitor_device: str | None = None
    monitor_enabled: bool = True
    samplerate: int = 48000
    blocksize: int = 256
    latency_mode: str = "balanced"


@dataclass
class EngineStatus:
    state: str = "stopped"  # stopped | starting | running | degraded | error
    message: str = ""
    hostapi: str = ""
    input_name: str | None = None
    virtual_name: str | None = None
    monitor_name: str | None = None
    virtual_missing: bool = False
    latency_ms: float = 0.0
    samplerate: int = 0
    blocksize: int = 0
    warnings: list[str] = field(default_factory=list)


class _Output:
    def __init__(self, kind: str, device: DeviceInfo, channels: int, blocksize: int, prefill: int,
                 wake: threading.Event):
        self.kind = kind
        self.wake = wake
        self.device = device
        self.channels = channels
        self.blocksize = blocksize
        self.prefill = prefill
        self.extra = 0
        self.ring = RingBuffer(blocksize * 64, channels)
        self.stream: sd.OutputStream | None = None
        self.seen_underruns = 0
        self.calls = 0

    @property
    def target_frames(self) -> int:
        return (self.prefill + self.extra) * self.blocksize

    def callback(self, outdata, frames, time_info, status) -> None:
        self.ring.read_into(outdata)
        self.calls += 1
        self.wake.set()  # acorda o DSP para repor o que foi consumido


class _Session:
    """Um conjunto de streams abertos com uma configuração específica."""

    def __init__(self, engine: "AudioEngine", cfg: EngineConfig):
        self.engine = engine
        self.cfg = cfg
        self.status = EngineStatus(state="starting", samplerate=cfg.samplerate, blocksize=cfg.blocksize)
        self.outputs: list[_Output] = []
        self.in_stream: sd.InputStream | None = None
        self.in_ring: RingBuffer | None = None
        self.in_device: DeviceInfo | None = None
        self.last_input_time = 0.0
        self.input_calls = 0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started_at = 0.0
        self.dsp_error: str | None = None
        self.dsp_load = 0.0
        self.sync_offset_s = 0.0

    # ------------------------------------------------------------ abertura
    def open(self) -> EngineStatus:
        cfg, dm, st = self.cfg, self.engine.devices, self.status
        apis = dm.hostapis()
        hostapi = cfg.hostapi if cfg.hostapi in apis else dm.preferred_hostapi()
        st.hostapi = hostapi
        latency_hint, prefill = LATENCY_MODES.get(cfg.latency_mode, LATENCY_MODES["balanced"])
        extra = sd.WasapiSettings(auto_convert=True) if hostapi == "Windows WASAPI" else None
        bs, sr = cfg.blocksize, cfg.samplerate

        # --- resolução de dispositivos
        in_api = cfg.input_hostapi if cfg.input_hostapi in apis else hostapi
        in_dev = dm.find(cfg.input_device, in_api, "input")
        if cfg.input_device and in_dev is None:
            st.warnings.append(f"Microfone '{cfg.input_device}' não encontrado; usando o padrão.")
        if in_dev is None:
            in_dev = dm.physical_default(in_api, "input")
            if dm.default_is_virtual(in_api, "input") and in_dev is not None:
                st.warnings.append(f"O microfone padrão do Windows é um cabo virtual; usando '{in_dev.name}'.")
        elif in_dev.is_virtual:
            st.warnings.append(f"A entrada '{in_dev.name}' é um cabo virtual, não um microfone.")
        if in_dev is None:
            # Sem microfone nesta API: procura o melhor em outra (os streams são independentes).
            in_dev = dm.best_input([a for a in apis if a != in_api])
            if in_dev is not None:
                st.warnings.append(f"Sem microfone em {in_api}; usando '{in_dev.name}' ({in_dev.hostapi}).")

        virt_dev = None
        if cfg.virtual_enabled:
            virt_dev = dm.find(cfg.virtual_device, hostapi, "output") if cfg.virtual_device else None
            if cfg.virtual_device and virt_dev is None:
                st.warnings.append(f"Saída virtual '{cfg.virtual_device}' não encontrada.")
            if virt_dev is None and not cfg.virtual_device:
                virt_dev = dm.detect_virtual_output(hostapi)
            st.virtual_missing = virt_dev is None

        mon_dev = None
        if cfg.monitor_enabled:
            mon_dev = dm.find(cfg.monitor_device, hostapi, "output") if cfg.monitor_device else None
            if cfg.monitor_device and mon_dev is None:
                st.warnings.append(f"Saída de monitor '{cfg.monitor_device}' não encontrada; usando a padrão.")
            if mon_dev is None:
                mon_dev = dm.physical_default(hostapi, "output")
                if dm.default_is_virtual(hostapi, "output"):
                    st.warnings.append("A saída padrão do Windows é um cabo virtual: o som do PC (jogos, vídeos) "
                                       "está indo para o cabo. Volte seus fones/alto-falantes como padrão no Windows.")
            if mon_dev and virt_dev and mon_dev.index == virt_dev.index:
                mon_dev = None  # evita abrir o mesmo dispositivo duas vezes

        # --- saídas primeiro (já com pré-buffer de silêncio)
        for kind, dev in (("virtual", virt_dev), ("monitor", mon_dev)):
            if dev is None:
                continue
            channels = 2 if dev.max_output_channels >= 2 else 1
            out = _Output(kind, dev, channels, bs, prefill, self._wake)
            try:
                out.stream = sd.OutputStream(
                    device=dev.index, samplerate=sr, blocksize=bs, channels=channels,
                    dtype="float32", latency=latency_hint, callback=out.callback,
                    extra_settings=extra,
                )
                out.ring.write(np.zeros((out.target_frames, channels), dtype=np.float32))
                self.outputs.append(out)
            except Exception as exc:  # noqa: BLE001
                log.error("Falha ao abrir saída %s (%s): %s", kind, dev.name, exc)
                st.warnings.append(f"Não foi possível abrir '{dev.name}': {exc}")
                if kind == "virtual":
                    st.virtual_missing = True

        if in_dev is not None:
            channels = min(2, in_dev.max_input_channels)
            self.in_ring = RingBuffer(bs * 64, 1)
            try:
                in_extra = sd.WasapiSettings(auto_convert=True) if in_dev.hostapi == "Windows WASAPI" else None
                self.in_stream = sd.InputStream(
                    device=in_dev.index, samplerate=sr, blocksize=bs, channels=channels,
                    dtype="float32", latency=latency_hint, callback=self._input_callback,
                    extra_settings=in_extra,
                )
                self.in_device = in_dev
            except Exception as exc:  # noqa: BLE001
                log.error("Falha ao abrir microfone (%s): %s", in_dev.name, exc)
                st.warnings.append(f"Não foi possível abrir o microfone '{in_dev.name}': {exc}")
                self.in_ring = None
        else:
            st.warnings.append("Nenhum microfone disponível nesta API de áudio.")

        if not self.outputs:
            self.close()
            st.state = "error"
            st.message = "Nenhuma saída de áudio pôde ser aberta. " + " ".join(st.warnings)
            return st

        # --- prepara processadores com a taxa/bloco desta sessão
        self.engine.voice.prepare(sr, bs)
        self.engine.soundboard.set_samplerate(sr)
        self.engine.song.set_samplerate(sr)

        self._thread = threading.Thread(target=self._dsp_loop, name="dsp", daemon=True)
        self._thread.start()
        try:
            for out in self.outputs:
                out.stream.start()
            if self.in_stream:
                self.in_stream.start()
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao iniciar streams")
            self.close()
            st.state = "error"
            st.message = f"Falha ao iniciar o áudio: {exc}"
            return st

        self.started_at = time.monotonic()
        self.last_input_time = self.started_at
        st.input_name = in_dev.name if self.in_stream else None
        st.virtual_name = next((o.device.name for o in self.outputs if o.kind == "virtual"), None)
        st.monitor_name = next((o.device.name for o in self.outputs if o.kind == "monitor"), None)
        st.latency_ms = self.estimate_latency_ms()
        mon = next((o for o in self.outputs if o.kind == "monitor"), None)
        self.sync_offset_s = (
            (self.in_stream.latency if self.in_stream else 0.0)
            + ((mon.stream.latency + mon.target_frames / sr) if mon and mon.stream else 0.0)
        )
        st.state = "degraded" if (st.warnings or not self.in_stream) else "running"
        st.message = "Áudio em funcionamento" if st.state == "running" else "Áudio funcionando com avisos"
        return st

    def estimate_latency_ms(self) -> float:
        lat = 0.0
        if self.in_stream:
            lat += self.in_stream.latency
        virt = next((o for o in self.outputs if o.kind == "virtual"), None) or self.outputs[0]
        if virt.stream:
            lat += virt.stream.latency
        lat += virt.target_frames / self.cfg.samplerate
        lat += self.engine.voice.latency_s()
        return lat * 1000.0

    # ------------------------------------------------------------ callbacks
    def _input_callback(self, indata, frames, time_info, status) -> None:
        self.in_ring.write(indata[:, :1])
        self.input_calls += 1
        self.last_input_time = time.monotonic()
        self._wake.set()

    # ------------------------------------------------------------ DSP
    def _dsp_loop(self) -> None:
        bs = self.cfg.blocksize
        silence = np.zeros(bs, dtype=np.float32)
        block_s = bs / self.cfg.samplerate
        busy = 0.0
        window_start = time.perf_counter()
        while not self._stop.is_set():
            self._wake.wait(block_s)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                t0 = time.perf_counter()
                input_alive = (
                    self.in_ring is not None
                    and time.monotonic() - self.last_input_time < 0.25
                )
                if input_alive:
                    while self.in_ring.available >= bs:
                        self._render(self.in_ring.read(bs)[:, 0])
                else:
                    clock = self.outputs[0]
                    guard = 0
                    while clock.ring.available < clock.target_frames and guard < 16:
                        self._render(silence)
                        guard += 1
                self._regulate(input_alive)
                busy += time.perf_counter() - t0
                elapsed = time.perf_counter() - window_start
                if elapsed >= 1.0:
                    self.dsp_load = busy / elapsed
                    busy = 0.0
                    window_start = time.perf_counter()
            except Exception as exc:  # noqa: BLE001
                log.exception("Erro na thread de DSP")
                self.dsp_error = str(exc)
                time.sleep(0.05)

    def _render(self, mic: np.ndarray) -> None:
        eng = self.engine
        music = eng.song.render(len(mic))
        at = eng.voice.autotune
        if at is not None:
            # Sincronização por timestamp: a voz que chega agora responde ao que o usuário OUVIU,
            # ou seja, à música de (latência de saída do monitor + latência de entrada) atrás.
            if eng.song.playing or music is not None:
                at.song_time = eng.song.block_start / self.cfg.samplerate - self.sync_offset_s
            else:
                at.song_time = None
        voice = eng.voice.process(mic)
        sb_main, sb_preview = eng.soundboard.render(len(mic))
        want_monitor = any(o.kind == "monitor" for o in self.outputs)
        out, mon = eng.mixer.mix(voice, sb_main, sb_preview, want_monitor, music)
        eng.recorder.feed(out)
        for o in self.outputs:
            data = out if o.kind == "virtual" else mon
            if o.channels == 1:
                data = data.mean(axis=1, keepdims=True)
            o.ring.write(data)

    def _regulate(self, input_clocked: bool) -> None:
        """Compensa jitter e diferença de clock entre dispositivos."""
        warm = time.monotonic() - self.started_at > 0.75
        bs = self.cfg.blocksize
        for o in self.outputs:
            under = o.ring.underruns
            if under != o.seen_underruns:
                if warm and o.extra < MAX_EXTRA_BLOCKS:
                    o.extra += 1
                    log.info("Underrun em %s: aumentando buffer para %d blocos", o.kind, o.prefill + o.extra)
                    if input_clocked:
                        o.ring.write(np.zeros((bs, o.channels), dtype=np.float32))
                o.seen_underruns = under
            excess = o.ring.available - (o.target_frames + 3 * bs)
            if excess > 0:
                o.ring.discard(excess)

    # ------------------------------------------------------------ saúde
    def check_health(self) -> str | None:
        if self.dsp_error:
            return f"Erro no processamento: {self.dsp_error}"
        for o in self.outputs:
            if o.stream is not None and not o.stream.active:
                return f"O dispositivo de saída '{o.device.name}' parou de responder."
        if self.in_stream is not None:
            if not self.in_stream.active:
                return f"O microfone '{self.in_device.name}' parou de responder."
            if time.monotonic() - self.last_input_time > INPUT_STALL_S:
                return f"O microfone '{self.in_device.name}' não está enviando áudio."
        return None

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        streams = [o.stream for o in self.outputs if o.stream] + ([self.in_stream] if self.in_stream else [])
        for s in streams:
            try:
                s.abort(ignore_errors=True)
                s.close(ignore_errors=True)
            except Exception:  # noqa: BLE001
                log.debug("Erro ao fechar stream", exc_info=True)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self.outputs = []
        self.in_stream = None


class AudioEngine:
    def __init__(self, devices: DeviceManager | None = None):
        self.devices = devices or DeviceManager()
        self.voice = VoiceProcessor()
        self.soundboard = SoundboardPlayer(48000)
        self.mixer = AudioMixer()
        self.cache = SampleCache()
        self.recorder = TestRecorder()
        self.song = SongPlayer(48000)
        self.config = EngineConfig()
        self._status = EngineStatus()
        self._session: _Session | None = None
        self._want_running = False
        self._commands: queue.Queue = queue.Queue()
        self._status_listeners: list[Callable[[EngineStatus], None]] = []
        self._next_recovery = 0.0
        self._supervisor = threading.Thread(target=self._supervise, name="audio-supervisor", daemon=True)
        self._supervisor.start()

    # ------------------------------------------------------------ API pública
    def add_status_listener(self, cb: Callable[[EngineStatus], None]) -> None:
        self._status_listeners.append(cb)

    @property
    def status(self) -> EngineStatus:
        return self._status

    def start(self, cfg: EngineConfig | None = None) -> None:
        self._commands.put(("start", cfg))

    def stop(self) -> None:
        self._commands.put(("stop", None))

    def refresh_devices(self, done: Callable[[], None] | None = None) -> None:
        self._commands.put(("refresh", done))

    def shutdown(self) -> None:
        self._commands.put(("quit", None))
        self._supervisor.join(timeout=3.0)
        self.cache.shutdown()

    @property
    def running(self) -> bool:
        return self._session is not None

    @property
    def has_monitor(self) -> bool:
        s = self._session
        return bool(s and any(o.kind == "monitor" for o in s.outputs))

    def levels(self) -> dict[str, float]:
        lv = dict(self.mixer.levels)
        lv["input"] = self.voice.level_in
        lv["processed"] = self.voice.level_out
        lv["music"] = self.mixer.levels.get("music", 0.0)
        return lv

    def dsp_load(self) -> float:
        s = self._session
        return s.dsp_load if s else 0.0

    def xruns(self) -> int:
        s = self._session
        if not s:
            return 0
        return sum(o.ring.underruns for o in s.outputs)

    def current_latency_ms(self) -> float:
        s = self._session
        return s.estimate_latency_ms() if s else 0.0

    # ------------------------------------------------------------ supervisor
    def _set_status(self, status: EngineStatus) -> None:
        self._status = status
        for cb in list(self._status_listeners):
            try:
                cb(status)
            except Exception:  # noqa: BLE001
                log.exception("Erro em listener de status")

    def _open_session(self) -> None:
        self._close_session()
        self._set_status(EngineStatus(state="starting", message="Iniciando áudio..."))
        self.cache.set_samplerate(self.config.samplerate)
        self.soundboard.clear()
        session = _Session(self, self.config)
        try:
            status = session.open()
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro ao abrir sessão de áudio")
            session.close()
            status = EngineStatus(state="error", message=f"Erro ao iniciar o áudio: {exc}")
        if status.state in ("running", "degraded"):
            self._session = session
            log.info("Áudio iniciado: api=%s in=%s virt=%s mon=%s sr=%d bs=%d lat=%.1fms",
                     status.hostapi, status.input_name, status.virtual_name, status.monitor_name,
                     status.samplerate, status.blocksize, status.latency_ms)
        else:
            self._next_recovery = time.monotonic() + RECOVERY_INTERVAL_S
        self._set_status(status)

    def _close_session(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def _supervise(self) -> None:
        # O PortAudio (WASAPI/COM) precisa ser inicializado na mesma thread que abre os streams.
        try:
            self.devices.refresh()
        except Exception:  # noqa: BLE001
            log.exception("Falha ao inicializar o PortAudio")
        while True:
            try:
                cmd, arg = self._commands.get(timeout=0.5)
            except queue.Empty:
                cmd, arg = None, None
            try:
                if cmd == "quit":
                    self._want_running = False
                    self._close_session()
                    return
                if cmd == "start":
                    if arg is not None:
                        self.config = arg
                    self._want_running = True
                    self._open_session()
                elif cmd == "stop":
                    self._want_running = False
                    self._close_session()
                    self._set_status(EngineStatus(state="stopped", message="Áudio parado"))
                elif cmd == "refresh":
                    was_running = self._session is not None
                    self._close_session()
                    self.devices.refresh()
                    if was_running or self._want_running:
                        self._open_session()
                    if arg:
                        arg()
                self._health_tick()
            except Exception:  # noqa: BLE001
                log.exception("Erro no supervisor de áudio")

    def _health_tick(self) -> None:
        if not self._want_running:
            return
        if self._session is not None:
            problem = self._session.check_health()
            if problem:
                log.warning("Problema no áudio: %s", problem)
                self._close_session()
                self._set_status(replace(self._status, state="error",
                                         message=problem + " Tentando reconectar..."))
                self._next_recovery = time.monotonic() + 1.0
            elif self._status.latency_ms and abs(self._session.estimate_latency_ms() - self._status.latency_ms) > 2:
                self._set_status(replace(self._status, latency_ms=self._session.estimate_latency_ms()))
        elif time.monotonic() >= self._next_recovery:
            try:
                self.devices.refresh()
            except Exception:  # noqa: BLE001
                log.exception("Falha ao atualizar dispositivos")
            self._open_session()
