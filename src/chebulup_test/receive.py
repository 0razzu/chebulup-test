import array
import asyncio
import json
import traceback
from functools import partial

import ggwave
import numpy as np
import pyaudio
import websockets
from websockets import ServerConnection

from pyogg import OpusDecoder

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

    # f = open("integration.raw", "wb")
    packet_id = 0
    decodable_sequence = b""
    while True:
        try:
            data = await ws.recv()
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
            # f.flush()
            # f.close()
            return

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
                data = opus_decoder.decode(memoryview(bytearray(data)))
                # print(f"Packet #{packet_id}")
                # with wave.open("out.wav", "wb") as wf:
                #     wf.setnchannels(2)
                #     wf.setsampwidth(2)
                #     wf.setframerate(48000)
                #     wf.writeframes(recording)

                # p = pyaudio.PyAudio()
                # stream = p.open(format=pyaudio.paFloat32, channels=1, rate=48000, output=True)
                # stream.write(int16_to_float32(split_by_channels(data)[0]))
                # stream.stop_stream()
                # stream.close()

                payload = int16_to_float32(split_by_channels(data)[0])
                # f.write(payload)
                decodable_sequence += payload
                if len(decodable_sequence) >= 4096:
                    # print("Decoding")
                    chunk = decodable_sequence[:4096]
                    decodable_sequence = decodable_sequence[4096:]
                    res = ggwave.decode(instance, chunk)
                    if res is not None:
                        print("Received text: " + res.decode("utf-8"))

            except Exception as e:
                print(f"Error decoding message: {traceback.format_exc()}")

            packet_id += 1


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
