import asyncio
import json
import socket
import struct
import traceback
from enum import Enum, auto
from pathlib import Path
from uuid import uuid4

import ggwave
import httpx
import numpy as np
import websockets

from integrity_manager import INTEGRITY_BYTES, remove_integrity_data, sign, validate_checksum
from models import PayloadHeaderV1, PayloadType, PayloadV1

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ASTERISK_HOST = "192.168.57.3"
ASTERISK_PORT = 8088
ASTERISK_USER = "internet-server"
ASTERISK_PASS = "1234"
STASIS_APP    = "internet-server"

SERVER_HOST   = "192.168.57.1"
RTP_PORT      = 7777

SAMPLE_RATE   = 48_000
FRAME_SAMPLES = 960
FRAME_BYTES   = FRAME_SAMPLES * 2

RAW_GGWAVE_CHUNK_SIZE = 140 - INTEGRITY_BYTES
GGWAVE_DECODE_CHUNK   = 4096

ARI_BASE = f"http://{ASTERISK_HOST}:{ASTERISK_PORT}/ari"
ARI_WS   = (
    f"ws://{ASTERISK_HOST}:{ASTERISK_PORT}/ari/events"
    f"?app={STASIS_APP}&api_key={ASTERISK_USER}:{ASTERISK_PASS}"
)
ARI_AUTH = (ASTERISK_USER, ASTERISK_PASS)

# ---------------------------------------------------------------------------
# Shared UDP socket
# ---------------------------------------------------------------------------
rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
rtp_sock.bind((SERVER_HOST, RTP_PORT))
rtp_sock.setblocking(False)


# ---------------------------------------------------------------------------
# ARI HTTP helpers
# ---------------------------------------------------------------------------

def ari_post(path: str, **params) -> dict:
    r = httpx.post(f"{ARI_BASE}{path}", params=params, auth=ARI_AUTH)
    r.raise_for_status()
    return r.json() if r.content else {}


def ari_delete(path: str) -> None:
    r = httpx.delete(f"{ARI_BASE}{path}", auth=ARI_AUTH)
    if r.status_code not in (200, 204, 404):
        r.raise_for_status()


# ---------------------------------------------------------------------------
# PCM / RTP helpers
# ---------------------------------------------------------------------------

def int16_to_float32(pcm: bytes) -> bytes:
    return (np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0).tobytes()


def float32_to_int16(pcm: bytes) -> bytes:
    arr = np.frombuffer(pcm, dtype=np.float32)
    return np.clip(arr * 32768, -32768, 32767).astype(np.int16).tobytes()


def encode_payload(payload_bytes: bytes, seq_no_start: int) -> bytes:
    """Returns LE int16 PCM @ 48 kHz."""
    out = b""
    seq_no = seq_no_start
    for offset in range(0, len(payload_bytes), RAW_GGWAVE_CHUNK_SIZE):
        chunk = payload_bytes[offset:offset + RAW_GGWAVE_CHUNK_SIZE]
        signed = sign(chunk, seq_no)
        seq_no += 1
        pcm_f32 = ggwave.encode(signed.decode("latin-1"), protocolId=1, volume=20)
        out += float32_to_int16(pcm_f32)
    return out


RTP_HEADER_SIZE = 12


def make_rtp(payload: bytes, seq: int, ts: int, ssrc: int, pt: int) -> bytes:
    return struct.pack(
        "!BBHII", 0x80, pt,
        seq & 0xffff, ts & 0xffffffff, ssrc & 0xffffffff,
    ) + payload


def parse_rtp(data: bytes) -> bytes | None:
    return data[RTP_HEADER_SIZE:] if len(data) >= RTP_HEADER_SIZE else None


# ---------------------------------------------------------------------------
# Per-call handler
# ---------------------------------------------------------------------------

async def handle_call(channel_id: str) -> None:
    print(f"Handling call {channel_id}")

    try:
        ari_post(f"/channels/{channel_id}/answer")
    except Exception as e:
        print(f"Failed to answer {channel_id}: {e}")
        return

    ext_id = bridge_id = None
    try:
        ext = ari_post(
            "/channels/externalMedia",
            app=STASIS_APP,
            external_host=f"{SERVER_HOST}:{RTP_PORT}",
            format="slin48",
        )
        ext_id = ext["id"]
        print(f"External media channel: {ext_id}")

        bridge = ari_post("/bridges", type="mixing")
        bridge_id = bridge["id"]
        ari_post(f"/bridges/{bridge_id}/addChannel", channel=f"{channel_id},{ext_id}")
        print(f"Bridge {bridge_id} created")
    except Exception as e:
        print(f"Setup error: {e}")
        return

    ggwave_instance = ggwave.init()

    class State(Enum):
        WAITING       = auto()
        READING_FNAME = auto()
        READING_DATA  = auto()

    state       = State.WAITING
    header      = None
    cur_msg     = b""
    cur_len     = 0
    data_f      = None
    send_seq_no = 0
    decode_buf  = b""
    rtp_addr    = None
    rtp_pt      = 126   # will be overwritten from first packet
    rtp_seq     = 0
    rtp_ts      = 0
    rtp_ssrc    = 0x12345678

    loop = asyncio.get_event_loop()
    audio_f = Path(f"ari_recv_{channel_id}.raw").open("wb")

    try:
        while True:
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(rtp_sock, 4096),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                print(f"RTP timeout for {channel_id}")
                break

            if rtp_addr is None:
                rtp_addr = addr
                rtp_pt   = data[1] & 0x7f
                print(f"Asterisk RTP addr: {rtp_addr}, PT={rtp_pt}")

            pcm = parse_rtp(data)
            if not pcm:
                continue

            # Asterisk sends BE L16 — convert to LE for processing
            pcm_le = np.frombuffer(pcm, dtype=">i2").astype("<i2").tobytes()
            audio_f.write(pcm_le)
            decode_buf += int16_to_float32(pcm_le)

            while len(decode_buf) >= GGWAVE_DECODE_CHUNK * 4:
                chunk      = decode_buf[:GGWAVE_DECODE_CHUNK * 4]
                decode_buf = decode_buf[GGWAVE_DECODE_CHUNK * 4:]

                try:
                    ggdecoded = ggwave.decode(ggwave_instance, chunk)
                except Exception:
                    print(f"ggwave.decode: {traceback.format_exc()}")
                    continue

                if ggdecoded is None:
                    continue

                print("GOT A PART:", ggdecoded)

                # DEBUG: echo raw chunk back immediately, bypass payload parsing
                echo_bytes = PayloadV1(PayloadType.TEXT, ggdecoded).to_bytes()
                print(f"Echoing {len(echo_bytes)} bytes (debug)")
                pcm_out_le = encode_payload(echo_bytes, send_seq_no)
                send_seq_no += 1

                Path(f"ari_send_{channel_id}_le.raw").write_bytes(pcm_out_le)
                pcm_out_be = np.frombuffer(pcm_out_le, dtype="<i2").astype(">i2").tobytes()
                Path(f"ari_send_{channel_id}_be.raw").write_bytes(pcm_out_be)

                for i in range(0, len(pcm_out_le), FRAME_BYTES):
                    frame = pcm_out_le[i:i + FRAME_BYTES]
                    if len(frame) < FRAME_BYTES:
                        frame += b"\x00" * (FRAME_BYTES - len(frame))
                    pkt = make_rtp(frame, rtp_seq, rtp_ts, rtp_ssrc, rtp_pt)
                    rtp_sock.sendto(pkt, rtp_addr)
                    rtp_seq += 1
                    rtp_ts += FRAME_SAMPLES
                continue
                # END DEBUG

                checksum_valid, _ = validate_checksum(ggdecoded)
                if not checksum_valid:
                    print("ERROR: invalid checksum")
                ggdecoded = remove_integrity_data(ggdecoded)

                if state == State.READING_DATA:
                    end = min(len(ggdecoded), header.len - cur_len)
                    if header.type == PayloadType.TEXT:
                        cur_msg += ggdecoded[:end]
                    else:
                        if cur_msg:
                            data_f.write(cur_msg); cur_msg = b""
                        data_f.write(ggdecoded[:end])
                    cur_len += end
                    print(f"{cur_len} bytes so far")

                elif state == State.WAITING:
                    header, offset = PayloadHeaderV1.from_bytes(ggdecoded)
                    cur_msg = ggdecoded[offset:]
                    cur_len = len(ggdecoded) - offset
                    if header.name_len > 0:
                        state = State.READING_FNAME
                        if cur_len >= header.name_len:
                            data_f = Path(cur_msg[:header.name_len].decode()).open("wb")
                            cur_msg = cur_msg[header.name_len:]
                            cur_len -= header.name_len
                            state = State.READING_DATA
                    else:
                        if header.type == PayloadType.DATA:
                            data_f = Path(str(uuid4())).open("wb")
                        state = State.READING_DATA
                        print(f"EXPECTING {header.len} bytes of {header.type}")

                elif state == State.READING_FNAME:
                    if cur_len + len(ggdecoded) >= header.name_len:
                        name_end = header.name_len - cur_len
                        name = (cur_msg + ggdecoded[:name_end]).decode()
                        data_f = Path(name).open("wb")
                        cur_msg = ggdecoded[name_end:]
                        cur_len = len(ggdecoded) - name_end
                        state = State.READING_DATA
                    else:
                        cur_msg += ggdecoded
                        cur_len += len(ggdecoded)

                if header is not None and cur_len == header.len:
                    if header.type == PayloadType.DATA:
                        data_f.flush(); data_f.close()
                        print(f"File {data_f.name} written")
                        echo_bytes = PayloadV1(PayloadType.DATA, cur_msg, data_f.name).to_bytes()
                    else:
                        print(f"FULL MSG: {cur_msg.decode()}")
                        echo_bytes = PayloadV1(PayloadType.TEXT, cur_msg).to_bytes()

                    if rtp_addr:
                        print(f"Echoing {len(echo_bytes)} bytes")
                        pcm_out_le = encode_payload(echo_bytes, send_seq_no)
                        send_seq_no += len(echo_bytes) // RAW_GGWAVE_CHUNK_SIZE + 1

                        # Save both LE and BE versions for debugging
                        Path(f"ari_send_{channel_id}_le.raw").write_bytes(pcm_out_le)
                        pcm_out_be = np.frombuffer(pcm_out_le, dtype="<i2").astype(">i2").tobytes()
                        Path(f"ari_send_{channel_id}_be.raw").write_bytes(pcm_out_be)

                        for i in range(0, len(pcm_out_le), FRAME_BYTES):
                            frame = pcm_out_le[i:i + FRAME_BYTES]
                            if len(frame) < FRAME_BYTES:
                                frame += b"\x00" * (FRAME_BYTES - len(frame))
                            pkt = make_rtp(frame, rtp_seq, rtp_ts, rtp_ssrc, rtp_pt)
                            rtp_sock.sendto(pkt, rtp_addr)
                            rtp_seq += 1
                            rtp_ts += FRAME_SAMPLES

                    state      = State.WAITING
                    header     = None
                    cur_msg    = b""
                    cur_len    = 0
                    data_f     = None
                    decode_buf = b""

    finally:
        audio_f.flush(); audio_f.close()
        ggwave.free(ggwave_instance)
        if bridge_id:
            try: ari_delete(f"/bridges/{bridge_id}")
            except Exception: pass
        if ext_id:
            try: ari_delete(f"/channels/{ext_id}")
            except Exception: pass
        try: ari_delete(f"/channels/{channel_id}")
        except Exception: pass
        print(f"Call {channel_id} done")


# ---------------------------------------------------------------------------
# ARI WebSocket event loop
# ---------------------------------------------------------------------------

async def run() -> None:
    print(f"Connecting to ARI: {ARI_WS}")
    async with websockets.connect(ARI_WS) as ws:
        print("Connected")
        async for raw in ws:
            ev      = json.loads(raw)
            ev_type = ev.get("type")
            channel = ev.get("channel", {})
            ch_id   = channel.get("id", "")
            ch_name = channel.get("name", "")

            if "UnicastRTP" in ch_name:
                continue

            if ev_type == "StasisStart":
                print(f"StasisStart: {ch_id} ({ch_name})")
                asyncio.create_task(handle_call(ch_id))
            elif ev_type == "StasisEnd":
                print(f"StasisEnd: {ch_id} ({ch_name})")


if __name__ == "__main__":
    asyncio.run(run())