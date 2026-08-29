"""
Unit tests for games/hades.py, games/hades2.py, and lib/hades_lib.py.

Tests SGB1 container parsing, header metadata extraction, quick-fields,
and byte-exact round-trip serialization.

Run:
    python3 -m unittest discover -s tests -v
"""
import io
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "games"))

from lib import hades_lib
import hades as hades_game
import hades2 as hades2_game


def create_synthetic_sgb1(
    magic=b"SGB1",
    version=18,
    timestamp=1700000000,
    runs=5,
    location="Location_Home",
    shrine_points=10,
    easy_mode=True,
    hard_mode=False,
    traits=None,
    dev_save_name="Hub_PreRun",
    current_room="",
    payload=None
) -> bytes:
    if traits is None:
        traits = ["EnemyCountShrineUpgrade", "WeaponStaffSwing"]
    if payload is None:
        payload = bytes.fromhex("540000000000000000")
    
    stream = io.BytesIO()
    stream.write(magic)
    hades_lib.write_u32(stream, 12345678)
    hades_lib.write_u32(stream, version)
    hades_lib.write_u32(stream, timestamp)
    hades_lib.write_u32(stream, runs)
    hades_lib.write_str(stream, location)

    hades_lib.write_u32(stream, shrine_points)
    hades_lib.write_u32(stream, 0)
    hades_lib.write_u32(stream, 5)
    hades_lib.write_u32(stream, 16)
    hades_lib.write_u32(stream, 0)

    stream.write(bytes([1 if easy_mode else 0, 1 if hard_mode else 0]))
    hades_lib.write_str_list(stream, traits)

    hades_lib.write_str(stream, dev_save_name)
    hades_lib.write_str(stream, current_room)
    stream.write(payload)
    return stream.getvalue()


class TestHadesLib(unittest.TestCase):
    def test_synthetic_round_trip(self):
        raw = create_synthetic_sgb1()
        parsed = hades_lib.parse_sgb1_save(raw)

        self.assertEqual(parsed["Header"]["Magic"], "SGB1")
        self.assertEqual(parsed["Header"]["SaveVersion"], 18)
        self.assertEqual(parsed["Header"]["Runs"], 5)
        self.assertEqual(parsed["Header"]["Location"], "Location_Home")
        self.assertEqual(parsed["Header"]["ShrinePoints"], 10)
        self.assertTrue(parsed["Header"]["EasyMode"])
        self.assertFalse(parsed["Header"]["HardMode"])
        self.assertEqual(len(parsed["ActiveTraits"]), 2)

        serialized = hades_lib.serialize_sgb1_save(parsed, raw)
        self.assertEqual(serialized, raw)

    def test_invalid_magic_rejected(self):
        corrupted = b"BAD1" + bytes(100)
        with self.assertRaises(hades_lib.HadesSaveError):
            hades_lib.parse_sgb1_save(corrupted)

    def test_too_short_rejected(self):
        with self.assertRaises(hades_lib.HadesSaveError):
            hades_lib.parse_sgb1_save(b"SGB1" + bytes(4))

    def test_hades_game_profile_loads_and_dumps(self):
        raw = create_synthetic_sgb1(version=16, shrine_points=8)
        data = hades_game.loads(raw)
        self.assertEqual(data["Header"]["SaveVersion"], 16)
        self.assertEqual(data["Header"]["ShrinePoints"], 8)

        data["Header"]["ShrinePoints"] = 24
        out = hades_game.dumps(data)
        reparsed = hades_game.loads(out)
        self.assertEqual(reparsed["Header"]["ShrinePoints"], 24)

    def test_hades2_game_profile_loads_and_dumps(self):
        raw = create_synthetic_sgb1(version=18, shrine_points=14)
        data = hades2_game.loads(raw)
        self.assertEqual(data["Header"]["SaveVersion"], 18)
        self.assertEqual(data["Header"]["ShrinePoints"], 14)

        data["Header"]["Runs"] = 42
        out = hades2_game.dumps(data)
        reparsed = hades2_game.loads(out)
        self.assertEqual(reparsed["Header"]["Runs"], 42)


if __name__ == "__main__":
    unittest.main()
