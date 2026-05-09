CHECKSUM_SIZE = 2
SEQ_NO_SIZE = 4
INTEGRITY_BYTES = CHECKSUM_SIZE + SEQ_NO_SIZE


def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = crc ^ ((byte & 0xFF) << 8)
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if crc & 0x8000 != 0 else crc << 1
    return crc & 0xFFFF


def validate_checksum(chunk: bytes) -> tuple[bool, int | None]:
    checksum_bytes = chunk[-CHECKSUM_SIZE:]
    expected_checksum = int.from_bytes(checksum_bytes)
    actual_checksum = crc16(chunk[:-CHECKSUM_SIZE])
    ok = actual_checksum == expected_checksum

    seq_no_bytes = chunk[-INTEGRITY_BYTES:-CHECKSUM_SIZE]
    seq_no = int.from_bytes(seq_no_bytes)

    return ok, (seq_no if ok else None)


def remove_integrity_data(chunk: bytes) -> bytes:
    return chunk[:-INTEGRITY_BYTES]


def append_checksum(chunk: bytes) -> bytes:
    checksum = crc16(chunk)
    return chunk + checksum.to_bytes(CHECKSUM_SIZE)
