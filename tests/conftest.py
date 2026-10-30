import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "appdata"
    monkeypatch.setenv("VOICESTUDIO_DATA", str(d))
    return d


@pytest.fixture()
def tone_file(tmp_path):
    def make(name="tone.wav", seconds=0.5, sr=44100, freq=440.0, channels=1, fmt=None):
        t = np.arange(int(sr * seconds)) / sr
        data = 0.3 * np.sin(2 * np.pi * freq * t)
        if channels == 2:
            data = np.stack([data, data * 0.5], axis=1)
        path = tmp_path / name
        sf.write(str(path), data, sr, format=fmt)
        return path
    return make


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app
