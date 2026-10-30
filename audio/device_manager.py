"""Enumeração de dispositivos de áudio e detecção de cabos virtuais (VB-CABLE, Voicemeeter...)."""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import sounddevice as sd

log = logging.getLogger(__name__)

PREFERRED_HOSTAPIS = ("Windows WASAPI", "Windows DirectSound", "MME", "Windows WDM-KS")

# Dispositivos de SAÍDA que alimentam um microfone virtual.
VIRTUAL_OUTPUT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("VB-CABLE", re.compile(r"cable\s*(?:-\w\s*)?input", re.I)),
    ("VB-CABLE", re.compile(r"vb-audio virtual cable", re.I)),
    ("Hi-Fi Cable", re.compile(r"hi-fi cable input", re.I)),
    ("Voicemeeter", re.compile(r"voicemeeter\s*(?:aux\s*|vaio3\s*)?input", re.I)),
    ("Voicemeeter", re.compile(r"vb-audio voicemeeter", re.I)),
    ("Virtual Audio Cable", re.compile(r"\bline\s*\d+\s*\(virtual audio cable\)", re.I)),
]

VB_CABLE_URL = "https://vb-audio.com/Cable/"


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float

    @property
    def is_input(self) -> bool:
        return self.max_input_channels > 0

    @property
    def is_output(self) -> bool:
        return self.max_output_channels > 0

    def virtual_kind(self) -> str | None:
        if not self.is_output:
            return None
        for kind, pattern in VIRTUAL_OUTPUT_PATTERNS:
            if pattern.search(self.name):
                return kind
        return None


class DeviceManager:
    """Consulta dispositivos via PortAudio. A lista é congelada até `refresh()`."""

    def __init__(self):
        self._lock = threading.RLock()
        self._devices: list[DeviceInfo] = []
        self._hostapis: list[dict] = []
        self._load()

    def _load(self) -> None:
        with self._lock:
            self._hostapis = [dict(h) for h in sd.query_hostapis()]
            devices = []
            for i, d in enumerate(sd.query_devices()):
                devices.append(
                    DeviceInfo(
                        index=i,
                        name=d["name"],
                        hostapi=self._hostapis[d["hostapi"]]["name"],
                        max_input_channels=d["max_input_channels"],
                        max_output_channels=d["max_output_channels"],
                        default_samplerate=d["default_samplerate"],
                    )
                )
            self._devices = devices

    def refresh(self) -> None:
        """Reinicializa o PortAudio para enxergar dispositivos conectados/desconectados.

        Só pode ser chamado com todos os streams fechados.
        """
        with self._lock:
            try:
                sd._terminate()
            finally:
                sd._initialize()
            self._load()
        log.info("Lista de dispositivos atualizada (%d dispositivos)", len(self._devices))

    # ------------------------------------------------------------------ consulta
    def hostapis(self) -> list[str]:
        with self._lock:
            names = [h["name"] for h in self._hostapis]
        return sorted(names, key=lambda n: PREFERRED_HOSTAPIS.index(n) if n in PREFERRED_HOSTAPIS else 99)

    def preferred_hostapi(self) -> str:
        """Prefere a API com microfone e saídas disponíveis, na ordem WASAPI > DirectSound > MME."""
        # WDM-KS só é escolhido manualmente: muitos drivers não abrem streams por ele.
        apis = [a for a in self.hostapis() if a != "Windows WDM-KS"]
        for name in apis:
            if self.inputs(name) and self.outputs(name):
                return name
        for name in apis:
            if self.outputs(name):
                return name
        return apis[0] if apis else "MME"

    def devices(self, hostapi: str | None = None) -> list[DeviceInfo]:
        with self._lock:
            return [d for d in self._devices if hostapi is None or d.hostapi == hostapi]

    def inputs(self, hostapi: str | None) -> list[DeviceInfo]:
        return [d for d in self.devices(hostapi) if d.is_input]

    def outputs(self, hostapi: str | None) -> list[DeviceInfo]:
        return [d for d in self.devices(hostapi) if d.is_output]

    def default_device(self, hostapi: str, kind: str) -> DeviceInfo | None:
        with self._lock:
            for h in self._hostapis:
                if h["name"] == hostapi:
                    idx = h["default_input_device" if kind == "input" else "default_output_device"]
                    if 0 <= idx < len(self._devices):
                        dev = self._devices[idx]
                        if (dev.is_input if kind == "input" else dev.is_output):
                            return dev
        candidates = self.inputs(hostapi) if kind == "input" else self.outputs(hostapi)
        candidates = [d for d in candidates if d.virtual_kind() is None] or candidates
        return candidates[0] if candidates else None

    def find(self, name: str | None, hostapi: str, kind: str) -> DeviceInfo | None:
        """Encontra um dispositivo pelo nome (exato ou por prefixo — o MME trunca nomes em 31 chars)."""
        if not name:
            return None
        pool = self.inputs(hostapi) if kind == "input" else self.outputs(hostapi)
        for d in pool:
            if d.name == name:
                return d
        low = name.lower()
        for d in pool:
            dn = d.name.lower()
            if dn.startswith(low[:31]) or low.startswith(dn):
                return d
        return None

    @staticmethod
    def _mic_score(d: DeviceInfo) -> int:
        name = d.name.lower()
        score = 0
        if any(k in name for k in ("mic", "microfone", "microphone", "headset")):
            score += 3
        if any(k in name for k in ("voicemeeter", "cable", "stereo mix", "mixagem", "what u hear", "virtual")):
            score -= 4
        if "line" in name or "entrada" in name:
            score -= 1
        return score

    def best_input(self, hostapis: list[str]) -> DeviceInfo | None:
        """Melhor microfone físico disponível entre as APIs dadas (fallback quando falta na API escolhida)."""
        candidates = [d for api in hostapis for d in self.inputs(api)]
        if not candidates:
            return None
        order = {api: i for i, api in enumerate(hostapis)}
        return max(candidates, key=lambda d: (self._mic_score(d), -order.get(d.hostapi, 99)))

    def virtual_outputs(self, hostapi: str | None = None) -> list[DeviceInfo]:
        return [d for d in self.devices(hostapi) if d.virtual_kind()]

    def detect_virtual_output(self, hostapi: str) -> DeviceInfo | None:
        """Sugere o melhor cabo virtual: VB-CABLE primeiro, depois os demais."""
        found = self.virtual_outputs(hostapi)
        found.sort(key=lambda d: 0 if d.virtual_kind() == "VB-CABLE" else 1)
        return found[0] if found else None

    def virtual_driver_installed(self) -> bool:
        return bool(self.virtual_outputs(None))
