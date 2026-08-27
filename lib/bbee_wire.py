"""
Small schema-less protobuf reader/writer which preserves field ordering
and unknown-field bytes exactly.

Vendored unmodified from AppleBoiy/bbee-se (bbee_editor/wire.py, MIT
licensed) - see games/bbee.py's module docstring for how it's used.
"""

from __future__ import annotations

from dataclasses import dataclass


class WireError(ValueError):
    pass


def decode_varint(data: bytes, offset: int) -> tuple:
    value = 0
    shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise WireError("invalid or truncated protobuf varint")


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise WireError("negative varints are not supported")
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


@dataclass
class Field:
    number: int
    wire_type: int
    value: object  # int for wire_type 0, bytes otherwise

    def encode(self) -> bytes:
        output = bytearray(encode_varint((self.number << 3) | self.wire_type))
        if self.wire_type == 0:
            output += encode_varint(int(self.value))
        elif self.wire_type == 1:
            raw = bytes(self.value)
            if len(raw) != 8:
                raise WireError("fixed64 must contain 8 bytes")
            output += raw
        elif self.wire_type == 2:
            raw = bytes(self.value)
            output += encode_varint(len(raw)) + raw
        elif self.wire_type == 5:
            raw = bytes(self.value)
            if len(raw) != 4:
                raise WireError("fixed32 must contain 4 bytes")
            output += raw
        else:
            raise WireError(f"unsupported protobuf wire type {self.wire_type}")
        return bytes(output)


def parse_message(data: bytes) -> list:
    fields: list = []
    offset = 0
    while offset < len(data):
        key, offset = decode_varint(data, offset)
        number, wire_type = key >> 3, key & 7
        if number == 0 or wire_type not in (0, 1, 2, 5):
            raise WireError("invalid protobuf field")
        if wire_type == 0:
            value, offset = decode_varint(data, offset)
        elif wire_type == 1:
            value = data[offset:offset + 8]
            offset += 8
        elif wire_type == 5:
            value = data[offset:offset + 4]
            offset += 4
        else:
            length, offset = decode_varint(data, offset)
            value = data[offset:offset + length]
            offset += length
        if offset > len(data):
            raise WireError("truncated protobuf field")
        fields.append(Field(number, wire_type, value))
    return fields


def encode_message(fields: list) -> bytes:
    return b"".join(field.encode() for field in fields)


def bytes_fields(fields: list, number: int) -> list:
    return [field for field in fields if field.number == number and field.wire_type == 2]


def one_bytes(fields: list, number: int, label: str) -> Field:
    matches = bytes_fields(fields, number)
    if len(matches) != 1:
        raise WireError(f"expected exactly one {label}; found {len(matches)}")
    return matches[0]
