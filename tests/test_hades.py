"""
Unit tests for games/hades.py, games/hades2.py, and lib/hades_lib.py.
"""
import os
import sys
import unittest
import struct
import lz4.block

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "games"))

from lib import hades_lib
import hades as hades_game
import hades2 as hades2_game


def create_synthetic_sgb1(
    version=18,
    runs=14,
    location="Location_Home",
    grasp=16,
    prestige=0,
    easy_mode=False,
    hell_mode=False,
    traits=None,
    resources=None
) -> bytes:
    if traits is None:
        traits = ["EnemyCountShrineUpgrade", "WeaponStaffSwing"]
    if resources is None:
        resources = {"MetaCurrency": 664.0, "MetaFabric": 16.0, "OreFSilver": 11.0}

    root_table = {
        "GameState": {
            "Resources": resources
        },
        "CurrentRun": {
            "Hero": {"Health": 2000.0, "MaxHealth": 2000.0}
        }
    }
    lua_bytes = hades_lib.LuaWriter().write_document([root_table])
    compressed = lz4.block.compress(lua_bytes, store_size=False)

    writer = hades_lib.BinaryWriter()
    writer.write_bytes(hades_lib.MAGIC)
    writer.write_u32(0) # Checksum placeholder
    writer.write_i32(version)
    writer.write_u64(1700000000)
    writer.write_str(location)
    writer.write_i32(runs)

    if version >= 17:
        writer.write_bytes(bytes(8))
        writer.write_i32(grasp)
        if version >= 18:
            writer.write_i32(prestige)
    else:
        writer.write_i32(0)
        writer.write_i32(0)

    writer.write_u8(1 if easy_mode else 0)
    writer.write_u8(1 if hell_mode else 0)
    writer.write_str_array(traits)
    writer.write_str("Hub_PreRun")
    writer.write_str("")

    writer.write_i32(len(compressed))
    writer.write_bytes(compressed)

    output = bytearray(writer.finish())
    calc_chk = hades_lib.adler32_checksum(bytes(output[8:]))
    output[4:8] = struct.pack("<I", calc_chk)
    return bytes(output)


class TestHadesLib(unittest.TestCase):
    def test_synthetic_round_trip(self):
        raw = create_synthetic_sgb1()
        parsed = hades_lib.parse_sgb1_save(raw)

        self.assertEqual(parsed["Header"]["SaveVersion"], 18)
        self.assertEqual(parsed["Header"]["Runs"], 14)
        self.assertEqual(parsed["Header"]["Location"], "Location_Home")
        self.assertEqual(parsed["GameState"]["Resources"]["MetaCurrency"], 664.0)
        self.assertEqual(parsed["GameState"]["Resources"]["OreFSilver"], 11.0)

        serialized = hades_lib.serialize_sgb1_save(parsed, raw)
        reparsed = hades_lib.parse_sgb1_save(serialized)
        self.assertEqual(reparsed["GameState"]["Resources"]["MetaCurrency"], 664.0)

    def test_invalid_magic_rejected(self):
        corrupted = b"BAD1" + bytes(100)
        with self.assertRaises(hades_lib.HadesSaveError):
            hades_lib.parse_sgb1_save(corrupted)

    def test_too_short_rejected(self):
        with self.assertRaises(hades_lib.HadesSaveError):
            hades_lib.parse_sgb1_save(b"SGB1" + bytes(4))

    def test_hades_game_profile_loads_and_dumps(self):
        raw = create_synthetic_sgb1(version=16)
        data = hades_game.PROFILE.loads(raw)
        self.assertEqual(data["Header"]["SaveVersion"], 16)
        self.assertEqual(data["GameState"]["Resources"]["MetaCurrency"], 664.0)

        data["GameState"]["Resources"]["MetaCurrency"] = 1000.0
        out = hades_game.PROFILE.dumps(data)
        reparsed = hades_game.PROFILE.loads(out)
        self.assertEqual(reparsed["GameState"]["Resources"]["MetaCurrency"], 1000.0)

    def test_hades2_game_profile_loads_and_dumps(self):
        raw = create_synthetic_sgb1(version=18)
        data = hades2_game.PROFILE.loads(raw)
        self.assertEqual(data["Header"]["SaveVersion"], 18)
        self.assertEqual(data["GameState"]["Resources"]["MetaCurrency"], 664.0)

        data["GameState"]["Resources"]["MetaCurrency"] = 5000.0
        out = hades2_game.PROFILE.dumps(data)
        reparsed = hades2_game.PROFILE.loads(out)
        self.assertEqual(reparsed["GameState"]["Resources"]["MetaCurrency"], 5000.0)


if __name__ == "__main__":
    unittest.main()
