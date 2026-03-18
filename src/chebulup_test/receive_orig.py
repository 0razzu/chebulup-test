import random

import ggwave
import pyaudio

p = pyaudio.PyAudio()

stream = p.open(format=pyaudio.paFloat32, channels=1, rate=48000, input=True, frames_per_buffer=1024)

print('Listening ... Press Ctrl+C to stop')
instance = ggwave.init()

try:
    while True:
        data = stream.read(1024, exception_on_overflow=False)
        print(random.randint(-1024, 1024))
        res = ggwave.decode(instance, data)
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
