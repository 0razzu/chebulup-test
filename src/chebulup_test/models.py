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

    def __init__(self, type_: PayloadType, data: bytes) -> None:
        self.type = type_
        self.data = data

    def to_bytes(self) -> bytes:
        return (
            struct.pack("!B", self.v) +
            struct.pack("!B", self.type.value) +
            struct.pack("!Q", len(self.data)) +
            self.data
        )


class PayloadHeaderV1(PayloadHeader):
    v: int = 1

    def __init__(self, type_: PayloadType, length: int) -> None:
        self.type = type_
        self.len = length

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

        (length,) = struct.unpack_from("!Q", raw, offset)
        offset += 8
        if length < 0:
            raise ValueError(f"Invalid payload length: {length}")

        return cls(type_, length), offset
