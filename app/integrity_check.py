CHECKSUM_SIZE = 2


def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = crc ^ ((byte & 0xFF) << 8)
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if crc & 0x8000 != 0 else crc << 1
    return crc & 0xFFFF


def validate_checksum(chunk: bytes) -> bool:
    checksum_bytes = chunk[-CHECKSUM_SIZE:]
    expected_checksum = int.from_bytes(checksum_bytes)
    actual_checksum = crc16(chunk[:-CHECKSUM_SIZE])

    return actual_checksum == expected_checksum


def remove_checksum(chunk: bytes) -> bytes:
    return chunk[:-CHECKSUM_SIZE]
