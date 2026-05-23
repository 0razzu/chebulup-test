import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

FREQ = 8000


class MinimodemDecoder:
    def __init__(self) -> None:
        self.buf = np.array([], dtype=np.float32)

    def feed(self, samples: np.ndarray) -> bytes | None:
        self.buf = np.concatenate([self.buf, samples])

        # accumulate ~2 seconds before trying to decode
        if len(self.buf) < FREQ * 2:
            return None

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmppath = f.name

        with wave.open(tmppath, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(FREQ)
            wf.writeframes((self.buf * 32767).astype(np.int16).tobytes())

        result = subprocess.run(  # noqa: S603
            ["minimodem", "--rx", "-f", tmppath, "300"],  # noqa: S607
            capture_output=True,
            check=False,
        )

        Path(tmppath).unlink()

        decoded = result.stdout
        if decoded:
            self.buf = np.array([], dtype=np.float32)
            return decoded

        # keep last 0.5s for overlap in case message straddles a window
        self.buf = self.buf[-4000:]
        return None
