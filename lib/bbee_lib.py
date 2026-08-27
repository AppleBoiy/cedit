"""
cedit's BlazBlue Entropy Effect save logic - LZ4 framing + the narrow,
verified protobuf edit.

Adapted from AppleBoiy/bbee-se (bbee_editor/save_format.py, MIT licensed).
The parsing/editing logic (_locate_currency, edit_ap, inspect_decoded) is
ported essentially unchanged; decompress_file/compress_bytes (which work
on file paths, matching that project's own CLI/server model) are replaced
with decompress_bytes/compress_to_bytes (bytes in, bytes out) to fit
cedit's GameProfile.loads/dumps(bytes) -> data / data -> bytes contract.

Like DREDGE's save format, this one needs a real external tool cedit
can't bundle: the `lz4` command-line executable (not just the `lz4`
Python package - this shells out to get byte-identical framing behavior
to what the game itself and Steam Cloud already produce, rather than
re-implementing LZ4 framing in Python untested against a real save).
Install it with `brew install lz4` on macOS, or point BBEE_LZ4 at its
path if it's somewhere unusual.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lib.bbee_wire import Field, WireError, bytes_fields, encode_message, one_bytes, parse_message

LZ4_MAGIC = b"\x04\x22\x4d\x18"
CURRENCY_MODEL = "ModelPlayerNewCurrencyPack"
AP_CURRENCY_ID = 1
MAX_AP = 99_999_999


class SaveFormatError(ValueError):
    pass


@dataclass(frozen=True)
class SaveInfo:
    ap: int
    model_count: int
    raw_size: int
    decoded_size: int


def _lz4_binary() -> str:
    override = os.environ.get("BBEE_LZ4")
    candidate = override or shutil.which("lz4")
    if not candidate:
        raise SaveFormatError(
            "lz4 executable not found. Install it with 'brew install lz4' "
            "or set BBEE_LZ4 to its path."
        )
    return candidate


def decompress_bytes(raw: bytes) -> bytes:
    """The on-disk LZ4-framed bytes -> decoded protobuf bytes."""
    if not raw.startswith(LZ4_MAGIC):
        raise SaveFormatError("this doesn't look like a BBEE LZ4 save")
    result = subprocess.run(
        [_lz4_binary(), "-d", "-c"],
        input=raw,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise SaveFormatError(f"could not decompress this save: {detail}")
    return result.stdout


def compress_to_bytes(decoded: bytes) -> bytes:
    """Decoded protobuf bytes -> LZ4-framed bytes ready to write to disk.

    Goes through real temp files (not stdin/stdout pipes) for both sides,
    same as bbee-se's own compress_bytes() - some lz4 CLI builds behave
    inconsistently piping raw binary through stdin/stdout with `-`."""
    with tempfile.TemporaryDirectory(prefix="cedit-bbee-") as tmp_dir:
        source_path = Path(tmp_dir) / "decoded.bin"
        dest_path = Path(tmp_dir) / "encoded.lz4"
        source_path.write_bytes(decoded)
        result = subprocess.run(
            [_lz4_binary(), "-z", "-f", "--content-size", str(source_path), str(dest_path)],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise SaveFormatError(f"could not compress edited save: {detail}")
        return dest_path.read_bytes()


def _text(field: Field, label: str) -> str:
    try:
        return bytes(field.value).decode("utf-8")
    except UnicodeDecodeError as error:
        raise SaveFormatError(f"invalid {label} text") from error


def _locate_currency(decoded: bytes) -> tuple:
    try:
        outer = parse_message(decoded)
        save_name = one_bytes(outer, 1, "save name")
        if _text(save_name, "save name") != "AutoSave":
            raise SaveFormatError("unsupported save record (expected AutoSave)")

        matches = []
        for model_field in bytes_fields(outer, 2):
            model = parse_message(bytes(model_field.value))
            names = bytes_fields(model, 1)
            if len(names) == 1 and _text(names[0], "model name") == CURRENCY_MODEL:
                matches.append((model_field, model))
        if len(matches) != 1:
            raise SaveFormatError(
                f"expected exactly one {CURRENCY_MODEL}; found {len(matches)}"
            )

        model_field, model = matches[0]
        payload_field = one_bytes(model, 2, "currency model payload")
        payload = parse_message(bytes(payload_field.value))
        pack_field = one_bytes(payload, 1, "currency pack")
        pack = parse_message(bytes(pack_field.value))

        currency_matches = []
        for entry_field in bytes_fields(pack, 1):
            entry = parse_message(bytes(entry_field.value))
            keys = [f for f in entry if f.number == 1 and f.wire_type == 0]
            if len(keys) == 1 and keys[0].value == AP_CURRENCY_ID:
                currency_matches.append((entry_field, entry))
        if len(currency_matches) != 1:
            raise SaveFormatError(
                f"expected exactly one AP currency entry; found {len(currency_matches)}"
            )

        entry_field, entry = currency_matches[0]
        value_field = one_bytes(entry, 2, "AP currency value")
        value_message = parse_message(bytes(value_field.value))
        value_keys = [f for f in value_message if f.number == 1 and f.wire_type == 0]
        amounts = [f for f in value_message if f.number == 2 and f.wire_type == 0]
        if len(value_keys) != 1 or value_keys[0].value != AP_CURRENCY_ID or len(amounts) != 1:
            raise SaveFormatError("AP currency entry has an unsupported structure")
        return (
            outer, model_field, model, payload_field, payload,
            pack_field, pack, entry_field, entry, value_field, value_message, amounts[0],
        )
    except WireError as error:
        raise SaveFormatError(str(error)) from error


def inspect_decoded(decoded: bytes, raw_size: int = 0) -> SaveInfo:
    outer, *_rest, amount = _locate_currency(decoded)
    model_count = len(bytes_fields(outer, 2))
    return SaveInfo(int(amount.value), model_count, raw_size, len(decoded))


def edit_ap(decoded: bytes, new_ap: int) -> bytes:
    if not isinstance(new_ap, int) or isinstance(new_ap, bool) or not 0 <= new_ap <= MAX_AP:
        raise SaveFormatError(f"Analysis Points must be a whole number from 0 to {MAX_AP:,}")
    (
        outer, model_field, model, payload_field, payload,
        pack_field, pack, entry_field, entry, value_field, value_fields, amount,
    ) = _locate_currency(decoded)
    amount.value = new_ap

    # Rebuild only the nested containers on the path to AP. All unrelated
    # model payloads and unknown fields keep their original bytes and order.
    value_field.value = encode_message(value_fields)
    entry_field.value = encode_message(entry)
    pack_field.value = encode_message(pack)
    payload_field.value = encode_message(payload)
    model_field.value = encode_message(model)
    edited = encode_message(outer)
    if inspect_decoded(edited).ap != new_ap:
        raise SaveFormatError("edited protobuf did not pass AP verification")
    return edited
