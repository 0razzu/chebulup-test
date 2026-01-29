import asyncio
import json
import wave
from functools import partial

import ggwave
import pyaudio
import websockets
from g711 import decode_ulaw
from pyogg import OpusDecoder
from websockets import ServerConnection


opus_decoder = OpusDecoder()
opus_decoder.set_channels(2)
opus_decoder.set_sampling_frequency(48000)

async def handle_connection(ws: ServerConnection, instance):
    print("New connection established")

    try:
        packet_id = 0
        recording_id = -1
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


                    data = opus_decoder.decode(memoryview(bytearray(data)))
                    recording += data
                    # print(len(recording))
                    if len(recording) > 16000 * 50:
                        recording_id += 1
                        print(f"Analyzing recording #{recording_id}")
                        with wave.open("out.wav", "wb") as wf:
                            wf.setnchannels(2)
                            wf.setsampwidth(2)
                            wf.setframerate(48000)
                            wf.writeframes(b"".join(recording))
                        p = pyaudio.PyAudio()
                        stream = p.open(format=pyaudio.paInt16, channels=2, rate=48000, output=True)
                        stream.write(b"".join(recording))
                        stream.stop_stream()
                        stream.close()

                        res = ggwave.decode(instance, b"".join(recording))
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
