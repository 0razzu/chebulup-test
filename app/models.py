import struct
from abc import ABC, abstractmethod
from enum import Enum


class PayloadType(Enum):
    DATA = 0b00
    TEXT = 0b01


class Payload(ABC):
    v: int

    @abstractmethod
    def to_bytes(self) -> bytes: ...


class PayloadHeader(ABC):
    v: int

    @classmethod
    def from_bytes(cls, data: bytes) -> tuple["PayloadHeader", int]:
        if len(data) == 0:
            raise ValueError("Empty payload")

        match version := data[0]:
            case 1:
                return PayloadHeaderV1.from_bytes(data)
            case _:
                raise ValueError(f"Unsupported payload version: {version}")


class PayloadV1(Payload):
    v = 1

    def __init__(self, type_: PayloadType, data: bytes, name: str | None = None) -> None:
        self.type = type_
        self.data = data
        self.name = name

    def to_bytes(self) -> bytes:
        buf = struct.pack("!B", self.v) + struct.pack("!B", self.type.value) + struct.pack("!Q", len(self.data))
        if self.type == PayloadType.DATA:
            buf += struct.pack("!H", len(self.name)) + self.name.encode()

        return buf + self.data


class PayloadHeaderV1(PayloadHeader):
    v: int = 1

    def __init__(self, type_: PayloadType, length: int, name_length: int = 0) -> None:
        self.type = type_
        self.len = length
        self.name_len = name_length

    @classmethod
    def from_bytes(cls, raw: bytes) -> tuple["PayloadHeaderV1", int]:
        if len(raw) < 1 + 1 + 8:
            raise ValueError("Payload too short")

        offset = 0

        version = raw[offset]
        offset += 1
        if version != cls.v:
            raise ValueError(f"Expected payload version {cls.v}, got {version}")

        type_byte = raw[offset]
        offset += 1
        type_ = PayloadType(type_byte)

        if type_ == PayloadType.DATA and offset + 2 > len(raw):
            raise ValueError("Payload too short")

        (length,) = struct.unpack_from("!Q", raw, offset)
        offset += 8
        if length < 0:
            raise ValueError(f"Invalid payload length: {length}")

        name_len = 0
        if type_ == PayloadType.DATA:
            (name_len,) = struct.unpack_from("!H", raw, offset)
            offset += 2

        #     if offset + name_len > len(raw):
        #         raise ValueError("Payload too short for name")
        #
        #     name_bytes = raw[offset:offset + name_len]
        #     name = name_bytes.decode()
        #     offset += name_len

        return cls(type_, length, name_len), offset
