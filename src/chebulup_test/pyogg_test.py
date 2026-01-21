import pyaudio

from src.chebulup_test import pyogg

FRAMES = int(48000 * 20 / 1000)

p = pyaudio.PyAudio()

stream = p.open(format=pyaudio.paInt16, channels=1, rate=48000, input=True, frames_per_buffer=FRAMES)

data = stream.read(FRAMES, exception_on_overflow=False)

opus_buffered_encoder = pyogg.OpusBufferedEncoder()
opus_buffered_encoder.set_application("audio")
opus_buffered_encoder.set_sampling_frequency(48000)
opus_buffered_encoder.set_channels(1)
opus_buffered_encoder.set_frame_size(20)

output_filename = "res.ogg"
print(f"Writing OggOpus file to {output_filename}")
ogg_opus_writer = pyogg.OggOpusWriter(output_filename, opus_buffered_encoder)

for _ in range(100):
    data = stream.read(FRAMES, exception_on_overflow=False)
    ogg_opus_writer.write(memoryview(bytearray(data)))

ogg_opus_writer.close()
