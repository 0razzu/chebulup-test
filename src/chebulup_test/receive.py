import array
import asyncio
import json
import traceback

import ggwave
import numpy as np
import websockets
from websockets import ServerConnection

from pyogg import OpusDecoder
from src.chebulup_test.models import PayloadHeaderV1, PayloadType


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


async def handle_connection(ws: ServerConnection):
    print("New connection established")

    opus_decoder = OpusDecoder()
    opus_decoder.set_channels(2)
    opus_decoder.set_sampling_frequency(48000)

    ggwave_instance = ggwave.init()

    buf = b""
    header: PayloadHeaderV1 | None = None
    cur_msg = b""
    cur_msg_len = 0
    f = open("integration.raw", "wb")
    # packet_id = 0
    try:
        while True:
            data = await ws.recv()

            if isinstance(data, str):
                data = json.loads(data)
                print(data)
                if data["request"] == "setup":
                    await ws.send(json.dumps({
                        "response": "setup",
                        "id": data["id"],
                        "codecs": [{"name": "opus"}],
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
                    f.write(payload)
                    buf += payload
                    if len(buf) >= 4096:
                        # print("Decoding")
                        chunk = buf[:4096]
                        buf = buf[4096:]
                        res: bytes = ggwave.decode(ggwave_instance, chunk)
                        if res is not None:
                            print("GOT A PART:", res)

                            if header is not None:
                                cur_msg += res
                                cur_msg_len += len(res)

                                if cur_msg_len == header.len:
                                    print("FULL MSG: ", end="")
                                    match header.type:
                                        case PayloadType.DATA:
                                            print(cur_msg)
                                        case PayloadType.TEXT:
                                            print(cur_msg.decode())

                                    buf = b""
                                    header = None
                                    cur_msg = b""
                                    cur_msg_len = 0
                            else:
                                header, offset = PayloadHeaderV1.from_bytes(res)
                                cur_msg += res[offset:]
                                cur_msg_len += len(res) - offset
                        else:
                            # send(repeat)
                            ...

                except Exception as e:
                    print(f"Error decoding message: {traceback.format_exc()}")

                # packet_id += 1
    except websockets.exceptions.ConnectionClosed:
        print("Connection closed")
        f.flush()
        f.close()
    finally:
        ggwave.free(ggwave_instance)


async def run_server(host: str, port: int):
    server = await websockets.serve(handle_connection, host, port)
    print(f"WebSocket server running on ws://{host}:{port}")
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(run_server(host="192.168.57.1", port=12345))
