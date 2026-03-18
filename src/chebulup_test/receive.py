import asyncio
import json
import traceback
import wave
from functools import partial

import array
import ggwave
import numpy as np
import pyaudio
import websockets
from g711 import decode_ulaw
from scipy.signal import resample_poly

from pyogg import OpusDecoder
from websockets import ServerConnection


opus_decoder = OpusDecoder()
opus_decoder.set_channels(2)
opus_decoder.set_sampling_frequency(48000)

def split_by_channels(recording: bytes) -> tuple[bytes, bytes]:
    samples = array.array("h")
    samples.frombytes(recording)

    l = array.array("h")
    r = array.array("h")

    for i in range(0, len(samples), 2):
        l.append(samples[i])
        r.append(samples[i + 1])

    return l.tobytes(), r.tobytes()

def int16_to_float32(recording: bytes) -> bytes:
    pcm = np.frombuffer(recording, dtype=np.int16)
    pcm = pcm.astype(np.float32) / 32768

    return pcm.tobytes()

async def handle_connection(ws: ServerConnection, instance):
    print("New connection established")

    try:
        packet_id = 0
        recording_id = -1
        recording = bytearray()
        while True:
            data = await ws.recv()

            if isinstance(data, str):
                data = json.loads(data)
                print(data)
                if data["request"] == "setup":
                    await ws.send(json.dumps({
                        "response": "setup",
                        "id": data["id"],
                        "codecs": data["codecs"],
                    }))
            else:
                try:
                    # res = ggwave.decode(instance, data)
                    # if res is not None:
                    #     print("Received text: " + res.decode("utf-8"))
                    # else:
                    #     # print("No valid ggwave message decoded")
                    #     ...


                    data = opus_decoder.decode(memoryview(bytearray(data)))
                    recording.extend(data)
                    # print(len(recording))
                    if len(recording) >= 16 * 72 * 1024:  # 72 frames (16+16 for markers, 40 for data)
                        recording_id += 1
                        print(f"Analyzing recording #{recording_id}")
                        # with wave.open("out.wav", "wb") as wf:
                        #     wf.setnchannels(2)
                        #     wf.setsampwidth(2)
                        #     wf.setframerate(48000)
                        #     wf.writeframes(recording)
                        p = pyaudio.PyAudio()
                        stream = p.open(format=pyaudio.paFloat32, channels=1, rate=48000, output=True)
                        stream.write(int16_to_float32(split_by_channels(recording)[0]))
                        stream.stop_stream()
                        stream.close()

                        payload = int16_to_float32(split_by_channels(recording)[0])
                        res = ggwave.decode(instance, payload)
                        if res is not None:
                            print("Received text: " + res.decode("utf-8"))

                        recording.clear()
                except Exception as e:
                    print(f"Error decoding message: {traceback.format_exc()}")
                    recording.clear()
            packet_id += 1

    except websockets.exceptions.ConnectionClosed:
        print("Connection closed")


async def run_server(instance):
    host = "192.168.57.1"
    port = 12345
    handler = partial(handle_connection, instance=instance)
    server = await websockets.serve(handler, host, port)
    print(f"WebSocket server running on ws://{host}:{port}")
    await server.wait_closed()


async def main():
    instance = ggwave.init()
    try:
        await run_server(instance)
    except KeyboardInterrupt:
        pass
    finally:
        ggwave.free(instance)


if __name__ == "__main__":
    asyncio.run(main())
