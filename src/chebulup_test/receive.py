import asyncio
import json
from functools import partial

import ggwave
import pyaudio
import websockets
from g711 import decode_ulaw
from pyogg import OpusDecoder
from websockets import ServerConnection


opus_decoder = OpusDecoder()
opus_decoder.set_channels(1)
opus_decoder.set_sampling_frequency(48000)

async def handle_connection(ws: ServerConnection, instance):
    print("New connection established")

    try:
        i = 0
        recording = []
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

                    recording += data
                    print(len(recording))
                    if len(recording) > 160 * 50:
                        p = pyaudio.PyAudio()
                        stream = p.open(format=pyaudio.paInt16, channels=1, rate=48000, output=True)
                        with open("recording.opus", "wb") as f:
                            f.write(bytes(recording))
                            f.close()
                        buf = bytearray(recording)
                        opus_decoder.decode(memoryview(buf))
                        stream.write(opus_decoder.decode(memoryview(buf)).tobytes())
                        stream.stop_stream()
                        stream.close()

                        res = ggwave.decode(instance, opus_decoder.decode(memoryview(buf)).tobytes())
                        if res is not None:
                            print("Received text: " + res.decode("utf-8"))

                        recording = []

                    # p = pyaudio.PyAudio()
                    #
                    # stream = p.open(format=pyaudio.paInt16, channels=1, rate=8000, output=True)
                    # stream.write(decode_ulaw(data).tobytes())
                    # stream.stop_stream()
                    # stream.close()

                    # with open(f'files/p{i}.raw', 'wb') as f:
                    #     f.write(data)

                    # p.terminate()
                except Exception as e:
                    print(f"Error decoding message: {e}")
                    recording = []
            i += 1

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
