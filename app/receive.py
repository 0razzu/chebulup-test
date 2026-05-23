import asyncio
import json
import traceback
from enum import Enum, auto
from pathlib import Path
from uuid import uuid4

import audioop
import numpy as np
import websockets
from websockets import ServerConnection

from integrity_manager import remove_integrity_data, validate_checksum
from minimodem import MinimodemDecoder
from models import PayloadHeaderV1, PayloadType

GGWAVE_CHUNK_SIZE = 4096


class HandlerState(Enum):
    WAITING = auto()
    READING_FNAME = auto()
    READING_DATA = auto()


def ulaw_to_float32(recording: bytes) -> np.ndarray:
    pcm16 = audioop.ulaw2lin(recording, 2)
    float32 = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768

    return float32


async def handle_connection(ws: ServerConnection) -> None:  # noqa: PLR0912, PLR0915
    print("New connection established")

    # opus_decoder = OpusDecoder()
    # opus_decoder.set_channels(2)
    # opus_decoder.set_sampling_frequency(48000)

    # opus_encoder = OpusEncoder()
    # opus_encoder.set_channels(1)
    # opus_encoder.set_sampling_frequency(48000)
    # opus_encoder.set_application("audio")

    data_decoder = MinimodemDecoder()

    state = HandlerState.WAITING
    header: PayloadHeaderV1 | None = None
    cur_msg = b""
    cur_len = 0
    audio_f = Path("integration.raw").open("wb")  # noqa: ASYNC230, SIM115
    data_f = None
    last_seq_no = -1
    # pending_seq_nos = set()
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
                                "codecs": [{"name": "ulaw"}],
                            }
                        )
                    )
            else:
                try:
                    # data = opus_decoder.decode(memoryview(bytearray(data)))

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

                    payload = ulaw_to_float32(data)
                    audio_f.write(payload.tobytes())
                    # print("Decoding")
                    decoded = data_decoder.feed(payload)
                    if decoded is not None:
                        print("GOT A PART:", decoded)

                        checksum_valid, gotten_seq_no = validate_checksum(decoded)
                        if not checksum_valid:
                            last_seq_no += 1
                            # pending_seq_nos.add(last_seq_no)

                            print(f"ERROR: invalid checksum, seq_no: {last_seq_no}")

                            # TODO float32_to_int16
                            # ack = Ack(seq_no=last_seq_no, accepted=checksum_valid).to_bytes()
                            # signed_ack = append_checksum(ack)
                            # ggencoded_ack = ggwave.encode(
                            #     payload,
                            #     protocolId=1,
                            #     volume=20,
                            # )
                            # opus_ack = opus_encoder.encode(ggencoded_ack)
                            # await ws.send(opus_ack)
                        else:
                            last_seq_no = gotten_seq_no

                        decoded = remove_integrity_data(decoded)

                        if state == HandlerState.READING_DATA:
                            cur_msg_end_in_chunk = min(len(decoded), header.len - cur_len)
                            if header.type == PayloadType.TEXT:
                                cur_msg += decoded[:cur_msg_end_in_chunk]
                            else:
                                if cur_msg:
                                    data_f.write(cur_msg)
                                    cur_msg = b""
                                data_f.write(decoded[:cur_msg_end_in_chunk])
                            cur_len += cur_msg_end_in_chunk
                            # TODO process decoded’s continuation

                            print(f"{cur_len} bytes so far")
                        elif state == HandlerState.WAITING:
                            header, offset = PayloadHeaderV1.from_bytes(decoded)
                            cur_msg = decoded[offset:]
                            cur_len = len(decoded) - offset

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
                                    print(f"EXPECTING {header.len} bytes of {header.type}, already got {cur_len} bytes")
                            else:
                                if header.type == PayloadType.DATA:
                                    data_f = Path(str(uuid4())).open("wb")  # noqa: ASYNC230, SIM115
                                state = HandlerState.READING_DATA
                                print(f"EXPECTING {header.len} bytes of {header.type}, already got {cur_len} bytes")
                        elif state == HandlerState.READING_FNAME:
                            if cur_len + len(decoded) >= header.name_len:
                                name_end = header.name_len - cur_len
                                name = (cur_msg + decoded[:name_end]).decode()
                                data_f = Path(name).open("wb")  # noqa: ASYNC230, SIM115
                                cur_msg = decoded[name_end:]
                                cur_len = len(decoded) - name_end

                                state = HandlerState.READING_DATA
                                if cur_len >= header.len:
                                    cur_msg = cur_msg[: header.len]
                                    cur_len = header.len
                                    state = HandlerState.WAITING

                            else:
                                cur_msg += decoded
                                cur_len += len(decoded)

                        if cur_len == header.len:
                            match header.type:
                                case PayloadType.DATA:
                                    data_f.flush()
                                    data_f.close()
                                    print(f"file {data_f.name} written")
                                case PayloadType.TEXT:
                                    print(f"FULL MSG: {cur_msg.decode()}")

                            header = None
                            cur_msg = b""
                            cur_len = 0
                            data_f = None
                            state = HandlerState.WAITING

                except Exception:
                    print(f"Error decoding message: {traceback.format_exc()}")

                # packet_id += 1
    except websockets.exceptions.ConnectionClosed:
        print("Connection closed")
        audio_f.flush()
        audio_f.close()
    finally:
        ...


async def run_server(host: str, port: int) -> None:
    server = await websockets.serve(handle_connection, host, port)
    print(f"WebSocket server running on ws://{host}:{port}")
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(run_server(host="192.168.57.1", port=12345))
