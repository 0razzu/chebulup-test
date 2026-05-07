import random
from time import sleep

import ggwave
import pyaudio

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paFloat32, channels=1, rate=48000, input=True, frames_per_buffer=1024)

f = open("recording.f32le.raw", "wb")

print('Listening ... Press Ctrl+C to stop')
instance = ggwave.init()

try:
    while True:
        data = stream.read(1024, exception_on_overflow=False)

        # print(random.randint(-1024, 1024))
        res = ggwave.decode(instance, data)

        # outp = pyaudio.PyAudio()
        # outstream = outp.open(format=pyaudio.paFloat32, channels=1, rate=48000, output=True)
        # outstream.write(data)
        # outstream.stop_stream()
        # outstream.close()

        try:
            f.write(data)
        except Exception as e:
            print(e)

        if res is not None:
            try:
                print('Received text: ' + res.decode("utf-8"))
            except Exception as e:
                print(e)
except KeyboardInterrupt:
    print('Stopping ...')

ggwave.free(instance)

stream.stop_stream()
stream.close()

f.flush()
f.close()

p.terminate()
