import array
import asyncio
import json
import traceback
from enum import Enum, auto
from pathlib import Path
from uuid import uuid4

import ggwave
import numpy as np
import websockets
from websockets import ServerConnection

from deps.pyogg import OpusDecoder
from models import PayloadHeaderV1, PayloadType

GGWAVE_CHUNK_SIZE = 4096


class HandlerState(Enum):
    WAITING = auto()
    READING_FNAME = auto()
    READING_DATA = auto()


def split_by_channels(recording: bytes) -> tuple[bytes, bytes]:
    samples = array.array("h")
    samples.frombytes(recording)

    l = array.array("h")  # noqa: E741
    r = array.array("h")

    for i in range(0, len(samples), 2):
        l.append(samples[i])
        r.append(samples[i + 1])

    return l.tobytes(), r.tobytes()


def int16_to_float32(recording: bytes) -> bytes:
    pcm = np.frombuffer(recording, dtype=np.int16)
    pcm = pcm.astype(np.float32) / 32768

    return pcm.tobytes()


async def handle_connection(ws: ServerConnection) -> None:  # noqa: PLR0912, PLR0915
    print("New connection established")

    opus_decoder = OpusDecoder()
    opus_decoder.set_channels(2)
    opus_decoder.set_sampling_frequency(48000)

    ggwave_instance = ggwave.init()

    state = HandlerState.WAITING
    buf = b""
    header: PayloadHeaderV1 | None = None
    cur_msg = b""
    cur_len = 0
    audio_f = Path("integration.raw").open("wb")  # noqa: ASYNC230, SIM115
    data_f = None
    # packet_id = 0
    try:
        while True:
            data = await ws.recv()

            if isinstance(data, str):
                data = json.loads(data)
                print(data)
                if data["request"] == "setup":
                    await ws.send(
                        json.dumps(
                            {
                                "response": "setup",
                                "id": data["id"],
                                "codecs": [{"name": "opus"}],
                            }
                        )
                    )
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
                    audio_f.write(payload)
                    buf += payload
                    if len(buf) >= GGWAVE_CHUNK_SIZE:
                        # print("Decoding")
                        chunk = buf[:GGWAVE_CHUNK_SIZE]
                        buf = buf[GGWAVE_CHUNK_SIZE:]
                        ggdecoded: bytes = ggwave.decode(ggwave_instance, chunk)
                        if ggdecoded is not None:
                            print("GOT A PART:", ggdecoded)

                            if state == HandlerState.READING_DATA:
                                cur_msg_end_in_chunk = min(len(ggdecoded), header.len - cur_len)
                                if header.type == PayloadType.TEXT:
                                    cur_msg += ggdecoded[:cur_msg_end_in_chunk]
                                else:
                                    if cur_msg:
                                        data_f.write(cur_msg)
                                        cur_msg = b""
                                    data_f.write(ggdecoded[:cur_msg_end_in_chunk])
                                cur_len += cur_msg_end_in_chunk
                                # TODO process ggdecoded’s continuation

                                print(f"{cur_len} bytes so far")
                            elif state == HandlerState.WAITING:
                                header, offset = PayloadHeaderV1.from_bytes(ggdecoded)
                                cur_msg = ggdecoded[offset:]
                                cur_len = len(ggdecoded) - offset

                                name_len = header.name_len
                                if name_len > 0:
                                    state = HandlerState.READING_FNAME
                                    print(f"EXPECTING file name of {name_len} bytes")

                                    if cur_len >= name_len:  # fname fits this chunk
                                        data_f = Path(cur_msg[:name_len].decode()).open("wb")  # noqa: ASYNC230, SIM115
                                        state = HandlerState.READING_DATA
                                        cur_msg = cur_msg[name_len:]
                                        cur_len -= name_len

                                        state = HandlerState.READING_DATA
                                        print(
                                            f"EXPECTING {header.len} bytes of {header.type}, "
                                            f"already got {cur_len} bytes"
                                        )
                                else:
                                    if header.type == PayloadType.DATA:
                                        data_f = Path(str(uuid4())).open("wb")  # noqa: ASYNC230, SIM115
                                    state = HandlerState.READING_DATA
                                    print(f"EXPECTING {header.len} bytes of {header.type}, already got {cur_len} bytes")
                            elif state == HandlerState.READING_FNAME:
                                if cur_len + len(ggdecoded) >= header.name_len:
                                    name_end = header.name_len - cur_len
                                    name = (cur_msg + ggdecoded[:name_end]).decode()
                                    data_f = Path(name).open("wb")  # noqa: ASYNC230, SIM115
                                    cur_msg = ggdecoded[name_end:]
                                    cur_len = len(ggdecoded) - name_end

                                    state = HandlerState.READING_DATA
                                    if cur_len >= header.len:
                                        cur_msg = cur_msg[: header.len]
                                        cur_len = header.len
                                        state = HandlerState.WAITING

                                else:
                                    cur_msg += ggdecoded
                                    cur_len += len(ggdecoded)

                            if cur_len == header.len:
                                match header.type:
                                    case PayloadType.DATA:
                                        data_f.flush()
                                        data_f.close()
                                        print(f"file {data_f.name} written")
                                    case PayloadType.TEXT:
                                        print(f"FULL MSG: {cur_msg.decode()}")

                                buf = b""
                                header = None
                                cur_msg = b""
                                cur_len = 0
                                data_f = None
                                state = HandlerState.WAITING
                        else:
                            # send(repeat)
                            ...

                except Exception:
                    print(f"Error decoding message: {traceback.format_exc()}")

                # packet_id += 1
    except websockets.exceptions.ConnectionClosed:
        print("Connection closed")
        audio_f.flush()
        audio_f.close()
    finally:
        ggwave.free(ggwave_instance)


async def run_server(host: str, port: int) -> None:
    server = await websockets.serve(handle_connection, host, port)
    print(f"WebSocket server running on ws://{host}:{port}")
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(run_server(host="192.168.57.1", port=12345))
