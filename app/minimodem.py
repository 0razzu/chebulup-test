import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

FREQ = 8000
SILENCE_THRESHOLD = 0.01
SILENCE_NEEDED = FREQ // 4


class MinimodemDecoder:
    def __init__(self, baud: int = 300):
        self.buf = np.array([], dtype=np.float32)
        self.baud = baud
        self.silence_samples = 0

    def feed(self, samples: np.ndarray) -> bytes | None:
        self.buf = np.concatenate([self.buf, samples])

        if np.max(np.abs(samples)) < SILENCE_THRESHOLD:
            self.silence_samples += len(samples)
        else:
            self.silence_samples = 0

        if self.silence_samples < SILENCE_NEEDED or len(self.buf) < FREQ // 2:
            return None

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmppath = f.name

        with wave.open(tmppath, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(FREQ)
            wf.writeframes((self.buf * 32767).astype(np.int16).tobytes())

        result = subprocess.run(
            ["minimodem", "--rx", "--rx-one", "-f", tmppath, str(self.baud)],
            capture_output=True,
        )

        Path(tmppath).unlink()

        self.buf = np.array([], dtype=np.float32)
        self.silence_samples = 0

        return result.stdout if result.stdout else None
