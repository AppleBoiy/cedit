"""
One-off extraction script: itemData.itm + item_eng.gmd -> id -> name JSON.

Ported directly from MHWISaveEditor's own res/mapping/010 Editor/itm.bt and
gmd.bt binary templates, and data/ItemDB.cpp/.h's ItemName()/AdjustItemID()
logic (see cedit's data/mhw/README.md for the full writeup). Not a wiki
datamine - parsed straight from the game's own shipped item table and text
files, which happen to be checked into the MHWISaveEditor-master repo the
user pointed cedit at.
"""
import json
import re
import struct
from pathlib import Path

# Point this at a local MHWISaveEditor-master checkout's res/chunk/common
# folder (https://github.com/EnderHDMC/MHWISaveEditor) to regenerate.
BASE = Path("MHWISaveEditor-master/res/chunk/common")
ITM_PATH = BASE / "item" / "itemData.itm"
GMD_PATH = BASE / "text" / "steam" / "item_eng.gmd"

ITM_ENTRY_FMT = "<IBIBBBHIIHII"
ITM_ENTRY_SIZE = struct.calcsize(ITM_ENTRY_FMT)
assert ITM_ENTRY_SIZE == 32, ITM_ENTRY_SIZE


def parse_itm(path):
    raw = path.read_bytes()
    magic1, magic2, entry_count = struct.unpack_from("<IHI", raw, 0)
    off = struct.calcsize("<IHI")
    ids = []
    for i in range(entry_count):
        entry = struct.unpack_from(ITM_ENTRY_FMT, raw, off)
        ids.append(entry[0])
        off += ITM_ENTRY_SIZE
    return ids


STYL_RE = re.compile(r"<STYL.*?>(.*?)</STYL>", re.DOTALL)


def parse_gmd_strings(path):
    raw = path.read_bytes()
    magic, version, language_id = struct.unpack_from("<4sII", raw, 0)
    assert magic == b"GMD\x00", magic
    off = 12
    off += 8  # unknown[8]
    key_count, string_count, key_block_size, string_block_size, name_length = struct.unpack_from("<IIIII", raw, off)
    off += 20
    off += name_length + 1  # filename

    off += key_count * 32   # gmd_info_entry[key_count]
    off += 256 * 8          # buckets[256] u64

    off += key_block_size   # keys string block, skipped
    strings_block = raw[off:off + string_block_size]

    strings = strings_block.split(b"\x00")
    strings = strings[:string_count]
    return strings


def clean_name(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="replace")
    text = STYL_RE.sub(r"\1", text)
    return text.strip()


_ADJUST = {2270: 819, 819: 2270, 956: 957, 957: 956}


def main():
    ids = parse_itm(ITM_PATH)
    strings = parse_gmd_strings(GMD_PATH)
    print(f"itm entries: {len(ids)}, gmd strings: {len(strings)}")

    names = {}
    for item_id in ids:
        if item_id <= 0:
            continue
        lookup_id = _ADJUST.get(item_id, item_id)
        idx = lookup_id * 2
        if idx >= len(strings):
            continue
        name = clean_name(strings[idx])
        if not name:
            continue
        names[str(item_id)] = name

    out_path = Path(__file__).resolve().parent / "item_names.json"
    out_path.write_text(
        json.dumps(dict(sorted(names.items(), key=lambda kv: int(kv[0]))), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote {len(names)} names -> {out_path}")
    for sample_id in ("219", "252", "19", "179", "2270", "819"):
        print(sample_id, names.get(sample_id))


if __name__ == "__main__":
    main()
