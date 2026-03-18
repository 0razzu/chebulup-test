import ggwave
import numpy as np
import pyaudio

from scipy.signal import resample

p = pyaudio.PyAudio()

stream = p.open(format=pyaudio.paFloat32, channels=1, rate=8000, input=True, frames_per_buffer=int(1024 * 48000 / 8000))

print('Listening ... Press Ctrl+C to stop')
instance = ggwave.init()

i = 0
try:
    while True:
        i += 1
        print(i)
        data = stream.read(int(15 * 1024 * 48000 / 8000), exception_on_overflow=False)

        data = np.frombuffer(data, dtype=np.float32)
        target_length = int(len(data) * 48000 / 8000)
        data = resample(data, target_length).tobytes()

        # stream2 = p.open(format=pyaudio.paFloat32, channels=1, rate=48000, output=True)
        # stream2.write(data)
        # stream2.stop_stream()
        # stream2.close()

        res = None
        shift = 0
        while res is None and shift < len(data):
            res = ggwave.decode(instance, data[shift:])
            shift += 40
        if res is not None:
            try:
                print('Received text: ' + res.decode("utf-8"))
            except:
                pass
except KeyboardInterrupt:
    pass

ggwave.free(instance)

stream.stop_stream()
stream.close()

p.terminate()
