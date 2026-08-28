"""
Monster Hunter World: Iceborne save file (SAVEDATA1000) crypto.

Ported line-for-line from EnderHDMC/MHWISaveEditor's real C++ source
(crypto/iceborne_crypt.h, crypto/blowfish.h, crypto/sha1.h), itself ported
from LEGENDFF/mhw-Savecrypt's original reverse-engineering work - not
guessed or derived from a wiki. Verified byte-for-byte against a real save
file: every one of the file's 5 embedded checksums (the outer SHA1 plus
one custom checksum per encrypted region) passes on decrypt, and the
result decodes to sane values (readable hunter/palico names, a plausible
zenny amount and playtime, small item ids in the item pouch, etc).

The save has two encryption layers stacked:
  1. The WHOLE file is Blowfish-ECB encrypted (key below), with every
     4-byte word byte-swapped immediately before and after the Blowfish
     pass (see _byteswap - this is NOT the same as choosing a different
     Blowfish "endianness mode", it's a literal extra transform layered
     on top). A SHA1 of everything from byte 64 onward is stored at
     byte offset 12 (also byte-swapped) and must match.
  2. FOUR specific byte regions within that decrypted buffer - one shared
     "controls" region, and one region per hunter save slot (0/1/2) - are
     then further encrypted with a bespoke stream cipher: a salt derived
     from a CRC32 of the trailing 0x200 bytes past the region, 32
     different AES-ECB keys derived from that salt (one per contiguous
     sub-range of the region), and a hand-rolled XOR-around-each-block
     step using more of that same salt. Each region's own trailing 0x200
     bytes hold a bespoke (non-SHA) checksum of the region, generated
     from the same INTEGER_CONSTANTS/FLOAT_CONSTANTS lookup tables the
     game itself embeds (see data/mhw/constants.json) - this is what
     REGIONS map + checks below verifies.

This is the file layout that made hunter/item-pouch data look like pure
noise until this second layer was found: the outer Blowfish pass alone
decrypts cleanly (its own SHA1 checks out, and the file's untouched
padding regions come back all-zero), but every actual gameplay field
lives inside one of the four REGIONS below and stays ciphertext until
DecryptRegion() also runs on it.
"""
import hashlib
import json
import struct
from pathlib import Path

from Crypto.Cipher import AES, Blowfish

KEY_SAVEDATA1000 = b"xieZjoe#P2134-3zmaghgpqoe0z8$3azeq"
# rod_insect.rod_inse (kinsect equipment data) - a completely separate
# game data file from the save itself, encrypted the exact same way
# (byteswap + Blowfish-ECB + byteswap - see _blowfish_decrypt) but with
# its own key (types/constants.h's KEY_ROD_INSE), no outer SHA1 hash, and
# no inner per-region layer - see decrypt_rod_inse() below.
KEY_ROD_INSE = b"SFghFQVFJycHnypExurPwut98ZZq1cwvm7lpDpASeP4biRhstQgULzlb"

# (offset, length, save_slot_id) for the four inner-encrypted regions -
# hardcoded straight from EncryptSave/DecryptSave in iceborne_crypt.h,
# not re-derived from the .bt template (which - see games/mhw.py's own
# docstring - drifts slightly from these true offsets).
REGIONS = [
    (0x70, 0xDA50, 3),       # shared controls/keybinds region
    (0x3010D8, 0x2098C0, 0),  # hunter save slot 0
    (0x50AB98, 0x2098C0, 1),  # hunter save slot 1
    (0x714658, 0x2098C0, 2),  # hunter save slot 2
]
SLOT_REGIONS = {slot: (off, length) for off, length, slot in REGIONS if slot in (0, 1, 2)}

_MASK32 = 0xFFFFFFFF
_CONSTANTS_PATH = Path(__file__).resolve().parent.parent / "data" / "mhw" / "constants.json"
with open(_CONSTANTS_PATH, encoding="utf-8") as _f:
    _constants = json.load(_f)
INTEGER_CONSTANTS = _constants["integer_constants"]
FLOAT_CONSTANTS = _constants["float_constants"]


def _i32(x):
    x &= _MASK32
    return x - 0x100000000 if x >= 0x80000000 else x


def _u32(x):
    return x & _MASK32


def _byteswap(data):
    """Reverse each 4-byte word in place - the extra transform layered
    around the outer Blowfish-ECB pass (utility/endian.h's byteswap())."""
    for i in range(0, len(data), 4):
        data[i], data[i + 3] = data[i + 3], data[i]
        data[i + 1], data[i + 2] = data[i + 2], data[i + 1]


def _blowfish_decrypt(data, key=KEY_SAVEDATA1000):
    _byteswap(data)
    cipher = Blowfish.new(key, Blowfish.MODE_ECB)
    data[:] = cipher.decrypt(bytes(data))
    _byteswap(data)


def _blowfish_encrypt(data, key=KEY_SAVEDATA1000):
    _byteswap(data)
    cipher = Blowfish.new(key, Blowfish.MODE_ECB)
    data[:] = cipher.encrypt(bytes(data))
    _byteswap(data)


def decrypt_rod_inse(raw):
    """rod_insect.rod_inse's raw bytes -> decrypted bytearray (the plain
    "01 10 09 18"-magic packed struct rod_inse.bt documents - see
    data/mhw/README.md's Kinsect section). Just Blowfish - no SHA1 header
    check and no inner per-region layer like the save file has, so there's
    nothing to validate here beyond "the magic looks right", left to the
    caller."""
    data = bytearray(raw)
    _blowfish_decrypt(data, key=KEY_ROD_INSE)
    return data


def _generate_hash(save, offset):
    h = bytearray(hashlib.sha1(bytes(save[offset:])).digest())
    _byteswap(h)
    return bytes(h)


def _check_hash(save):
    return bytes(save[12:32]) == _generate_hash(save, 64)


def _set_hash(save):
    save[12:32] = _generate_hash(save, 64)


def _crc32(iv, data, offset, length):
    iv = _u32(iv)
    for i in range(offset, offset + length):
        temp = (iv ^ data[i]) & 0xFF
        for _ in range(8):
            temp = (temp >> 1) ^ 0xEDB88320 if (temp & 1) else (temp >> 1)
        iv = ((iv >> 8) ^ temp) & _MASK32
    return iv


def _crc32_ints(iv, values, offset, length):
    iv = _u32(iv)
    for i in range(offset, offset + length):
        val = values[i] & _MASK32
        for j in range(4):
            byte = (val >> (8 * j)) & 0xFF
            temp = (iv ^ byte) & 0xFF
            for _ in range(8):
                temp = (temp >> 1) ^ 0xEDB88320 if (temp & 1) else (temp >> 1)
            iv = ((iv >> 8) ^ temp) & _MASK32
    return iv


def _generate_slot_checksum(save, offset, length, save_slot):
    constants = [0x55012174, 0x9FA3690, 0x4F5AE762, 0xA37A55D7]
    slot_constants_generator = [0x2EA10CEB, 0x204DE35E, 0x4BF0CF23, 0x72B401FD,
                                 0x5CDD1F19, 0x681BA6CF, 0x626B4CA, 0x7C8B3AF0]
    length_int = length >> 3

    slot_constants = [
        _i32(slot_constants_generator[i] ^ constants[(-save_slot - i - 1) & 3])
        for i in range(8)
    ]

    crc_lengths = [0] * 8
    for i in range(7):
        sc = slot_constants[i] & _MASK32
        idx = (sc + INTEGER_CONSTANTS[sc & 0xFFF]) & 0xFFF
        variation = FLOAT_CONSTANTS[idx]
        crc_lengths[i] = _i32(int((variation - 0.5) * length_int) + (i + 1) * length_int)
    crc_lengths[7] = length

    partial_crcs = [0] * 8
    crc_init = slot_constants[0]
    current_length = crc_lengths[0]
    cur_offset = offset
    for i in range(8):
        partial_crcs[i] = _i32(_crc32(_u32(crc_init), save, cur_offset, current_length))
        if i < 7:
            cur_offset += current_length
            current_length = crc_lengths[i + 1] - crc_lengths[i]
            crc_init = _i32(partial_crcs[i] ^ slot_constants[i + 1])

    hash_lookup = [_i32(slot_constants[i] ^ partial_crcs[i] ^ partial_crcs[7]) for i in range(7)]
    hash_lookup.append(_i32(slot_constants[7] ^ partial_crcs[7]))

    step1 = _crc32_ints(_u32(0xA37A55D7 ^ constants[3 - save_slot]), slot_constants, 0, 8)
    next_index = _i32(_crc32_ints(_u32(step1), partial_crcs, 0, 8))
    ni_u = _u32(next_index)
    jump = ((ni_u >> 24) + ((ni_u >> 16) & 0xFF) + ((ni_u >> 8) & 0xFF) + (ni_u & 0xFF)) & _MASK32

    checksum = bytearray(0x200)
    cur_next = next_index
    for i in range(0, 0x200, 4):
        current_index = _u32(cur_next) & 0xFFF
        cur_next = _i32((_u32(cur_next) + jump + 1) & 0xFFF)
        val = INTEGER_CONSTANTS[current_index]
        checksum_int = _i32(val ^ hash_lookup[(val + save_slot) & 7])
        if (val & 0x7) == 1:
            checksum_int = _i32(checksum_int ^ 0xBD75F29)
        struct.pack_into("<i", checksum, i, checksum_int)
    return bytes(checksum)


def _generate_salt(key_salt):
    c = _u32(key_salt ^ 0x4BF0CF23)
    ks = _u32(key_salt)
    offset_change = ((ks >> 24) + ((ks >> 16) & 0xFF) + ((ks >> 8) & 0xFF) + (ks & 0xFF) + 1)
    salt = bytearray(0x200)
    off = 0x5D7
    for i in range(0, 0x200, 4):
        salt_int = _u32(INTEGER_CONSTANTS[off & 0xFFF] ^ c)
        if (salt_int & 0x7) == 1:
            salt_int = _u32(salt_int ^ 0xBD75F29)
        struct.pack_into("<I", salt, i, salt_int)
        off += offset_change
    return bytes(salt)


def _generate_keys(key_salt, salt):
    c1 = _u32(0x5A8B79A9 ^ key_salt)
    c2 = _u32(0x34616F90 ^ key_salt)
    c3 = _u32(0xC4C638DF ^ key_salt)
    c4 = _u32(0x94FB64E8 ^ key_salt)
    keys = []
    for i in range(32):
        encoded = struct.unpack_from("<I", salt, i * 4)[0]
        row = bytearray(16)
        for j, c in enumerate((c1, c2, c3, c4)):
            struct.pack_into("<I", row, j * 4, _u32(encoded ^ c))
        keys.append(bytes(row))
    return keys


def _generate_key_length(key_salt, length):
    average_length = length >> 5
    expected_length = average_length
    key_length = [0] * 32
    for i in range(31):
        a = _u32(INTEGER_CONSTANTS[(key_salt + i) & 0xFFF ^ 0x5D7])
        b = FLOAT_CONSTANTS[(a & 0xFFF) ^ 0x885] - 0.5
        c = (int(b * average_length) + expected_length + 0xF) & 0xFFFFFFF0
        key_length[i] = _i32(c)
        expected_length += average_length
    key_length[31] = length
    return key_length


def _xor_region(save, save_offset, branch, salt, salt_offset, lo, hi):
    for k in range(lo, hi):
        save[save_offset + branch + k] ^= salt[(salt_offset + (k - lo)) & 0x1FF]


def _decrypt_region(save, offset, length, save_slot):
    key_salt = _crc32(0xA37A55D7, save, offset + length, 0x200)
    salt = _generate_salt(key_salt)
    keys = _generate_keys(key_salt, salt)
    key_length = _generate_key_length(key_salt, length)

    save_offset = offset
    for i in range(32):
        salt_offset = 0
        cipher = AES.new(keys[i], AES.MODE_ECB)
        target = offset + key_length[i]
        while save_offset < target:
            branch = 4 if (salt[salt_offset & 0x1FF] & 1) == 0 else 0
            _xor_region(save, save_offset, -branch, salt, salt_offset + 8, 4, 8)
            _xor_region(save, save_offset, -branch, salt, salt_offset + 12, 12, 16)

            block = bytes(save[save_offset:save_offset + 16])
            save[save_offset:save_offset + 16] = cipher.decrypt(block)

            _xor_region(save, save_offset, branch, salt, salt_offset + 0, 0, 4)
            _xor_region(save, save_offset, branch, salt, salt_offset + 4, 8, 12)

            salt_offset += 4
            save_offset += 16

    checksum = _generate_slot_checksum(save, offset, length, save_slot)
    stored = bytes(save[offset + length:offset + length + 0x200])
    return stored == checksum


def _encrypt_region(save, offset, length, save_slot):
    checksum = _generate_slot_checksum(save, offset, length, save_slot)
    save[offset + length:offset + length + 0x200] = checksum

    key_salt = _crc32(0xA37A55D7, checksum, 0, 0x200)
    salt = _generate_salt(key_salt)
    keys = _generate_keys(key_salt, salt)
    key_length = _generate_key_length(key_salt, length)

    save_offset = offset
    for i in range(32):
        salt_offset = 0
        cipher = AES.new(keys[i], AES.MODE_ECB)
        target = offset + key_length[i]
        while save_offset < target:
            branch = 4 if (salt[salt_offset & 0x1FF] & 1) == 0 else 0
            _xor_region(save, save_offset, branch, salt, salt_offset + 0, 0, 4)
            _xor_region(save, save_offset, branch, salt, salt_offset + 4, 8, 12)

            block = bytes(save[save_offset:save_offset + 16])
            save[save_offset:save_offset + 16] = cipher.encrypt(block)

            _xor_region(save, save_offset, -branch, salt, salt_offset + 8, 4, 8)
            _xor_region(save, save_offset, -branch, salt, salt_offset + 12, 12, 16)

            salt_offset += 4
            save_offset += 16


def decrypt_save(raw):
    """raw SAVEDATA1000 bytes -> (decrypted bytearray, {slot_id: bool_ok}).

    Raises ValueError if the outer file-level checksum fails (wrong key,
    truncated/corrupt file, or not actually a SAVEDATA1000 file at all).
    Per-region checksum failures are reported in the returned dict rather
    than raised, so a file with one damaged hunter slot can still be
    opened/edited for its other slots."""
    save = bytearray(raw)
    _blowfish_decrypt(save)
    if not _check_hash(save):
        raise ValueError(
            "Outer checksum didn't match - this doesn't look like a valid "
            "SAVEDATA1000 (Iceborne PC) file, or it's corrupted."
        )
    region_ok = {}
    for offset, length, slot in REGIONS:
        region_ok[slot] = _decrypt_region(save, offset, length, slot)
    return save, region_ok


def encrypt_save(save):
    """Fully-decrypted bytearray (same layout decrypt_save() returns,
    after any in-place edits) -> newly encrypted bytes ready to write to
    SAVEDATA1000. Recomputes every checksum from scratch."""
    save = bytearray(save)
    for offset, length, slot in REGIONS:
        _encrypt_region(save, offset, length, slot)
    _set_hash(save)
    _blowfish_encrypt(save)
    return bytes(save)
