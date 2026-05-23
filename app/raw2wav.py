import wave
from pathlib import Path

import numpy as np

with Path("integration.raw").open("rb") as f:
    samples = np.frombuffer(f.read(), dtype=np.float32)

with wave.open("integration.wav", "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(8000)
    wf.writeframes((samples * 32767).astype(np.int16).tobytes())
