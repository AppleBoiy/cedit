"""
Unit tests for games/octopath.py + lib/octopath_lib.py - pure Python, no
PySide6/display required. Builds a minimal synthetic GVAS-shaped byte blob
(same forging technique the upstream octopath-save-editor project's own
test suite uses - see its tests/test_editor.py) rather than needing a real
save file, so these run anywhere.

Run:
    python3 -m unittest discover -s tests -v
"""

import os
import struct
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
# Import games/octopath.py directly as a top-level module, NOT via the
# `games` package - games/__init__.py also imports games/dredge.py, which
# needs PySide6 (a real display), and these tests should run anywhere.
sys.path.insert(0, os.path.join(ROOT, "games"))

import octopath as octo_game


def prop(name: str, value: int) -> bytes:
    key = name.encode() + b"\0"
    kind = b"IntProperty\0"
    return struct.pack("<I", len(key)) + key + struct.pack("<I", len(kind)) + kind + struct.pack("<Q", 4) + b"\0" + struct.pack("<I", value)


def prop_bool(name: str, value: bool) -> bytes:
    key = name.encode() + b"\0"
    kind = b"BoolProperty\0"
    return struct.pack("<I", len(key)) + key + struct.pack("<I", len(kind)) + kind + struct.pack("<Q", 0) + bytes([1 if value else 0, 0])


def tame_monster_slot(enemy_id: int, count: int, used: bool) -> bytes:
    return prop("EnemyID_13_FAKE", enemy_id) + prop("Count_10_FAKE", count) + prop_bool("Used_15_FAKE", used)


def tame_monster_array(slots) -> bytes:
    payload = b"".join(slots)
    key = b"TameMonsterData\0"
    kind = b"ArrayProperty\0"
    return (struct.pack("<I", len(key)) + key + struct.pack("<I", len(kind)) + kind +
            struct.pack("<Q", len(payload)) + payload)


def fake_ot1_save() -> bytes:
    """A synthetic OT1-shaped save: money/hero, one filled + one empty
    inventory slot, 8 characters each with full stats plus Sword and Shield
    equipment slots, and a 2-slot Capture roster (one filled, one empty)."""
    data = bytearray(b"GVAS" + b"\0" * 60 + b"KSSaveGameBP_C\0")
    data += b"\0" * (1000 - len(data))
    data += prop("Money_2_FAKE", 123)
    data += prop("FirstSelectCharacterID", 3)
    data += prop("ItemID_8_FAKE", 1)      # Healing Grape - editable
    data += prop("Num_5_FAKE", 2)
    data += prop("ItemID_8_FAKE", 0)      # empty slot
    data += prop("Num_5_FAKE", 0)
    data += b"Temp_PlayerBackpack\0"
    for cid in range(1, 9):
        data += prop("CharacterID_6_FAKE", cid)
        for field in ["Level_7_FAKE", "Exp_63_FAKE", "RawHP_68_FAKE", "RawMP_69_FAKE",
                      "JobPoint_119_FAKE", "HP_38_FAKE", "MP_39_FAKE", "BP_36_FAKE", "SP_37_FAKE",
                      "ATK_40_FAKE", "DEF_41_FAKE", "MATK_42_FAKE", "MDEF_43_FAKE",
                      "ACC_44_FAKE", "EVA_45_FAKE", "CON_46_FAKE", "AGI_47_FAKE"]:
            data += prop(field, cid)
        data += prop("FirstJobID_90_FAKE", cid % 12)
        data += prop("SecondJobID_91_FAKE", 0xFFFFFFFF)
        data += prop("Sword_40_FAKE", 1001)          # Battle tested Blade
        data += prop("Shield_41_FAKE", 0xFFFFFFFF)   # empty
    data += tame_monster_array([
        tame_monster_slot(1, 3, False),           # Highland Ratkin I
        tame_monster_slot(0xFFFFFFFF, 0, False),  # empty
    ])
    return bytes(data)


class TestParsing(unittest.TestCase):
    def setUp(self):
        self.raw = fake_ot1_save()
        self.data = octo_game.loads(self.raw)

    def test_basic_fields(self):
        self.assertEqual(self.data["money"], 123)
        self.assertEqual(self.data["hero"], 3)
        self.assertEqual(len(self.data["characters"]), 8)

    def test_inventory_and_bookkeeping_exposed(self):
        self.assertEqual(len(self.data["inventory"]), 1)
        self.assertEqual(self.data["inventory"][0]["name"], "Healing Grape")
        self.assertEqual(self.data["inventory"][0]["count"], 2)
        self.assertIn(1, self.data["_inventory_slots"])
        self.assertEqual(len(self.data["_inventory_empty"]), 1)

    def test_equipment_parsed(self):
        row = self.data["characters"][0]
        by_key = {s["slot_key"]: s for s in row["equipment"]}
        self.assertEqual(by_key["Sword"]["id"], 1001)
        self.assertEqual(by_key["Sword"]["name"], "Battle tested Blade")
        self.assertIsNone(by_key["Shield"]["id"])

    def test_capture_parsed(self):
        slots = self.data["capture"]["slots"]
        self.assertEqual(slots[0]["name"], "Highland Ratkin I")
        self.assertIsNone(slots[1]["id"])


class TestReadOnlyCheck(unittest.TestCase):
    def setUp(self):
        self.data = octo_game.loads(fake_ot1_save())

    def test_root_fields(self):
        self.assertFalse(octo_game.read_only_check(self.data, "money", self.data["money"]))
        self.assertTrue(octo_game.read_only_check(self.data, "characters", self.data["characters"]))

    def test_character_fields(self):
        row = self.data["characters"][0]
        self.assertFalse(octo_game.read_only_check(row, "level", row["level"]))
        self.assertTrue(octo_game.read_only_check(row, "first_job_id", row["first_job_id"]))

    def test_equipment_only_id_writable(self):
        slot = self.data["characters"][0]["equipment"][0]
        self.assertFalse(octo_game.read_only_check(slot, "id", slot["id"]))
        self.assertTrue(octo_game.read_only_check(slot, "name", slot["name"]))

    def test_inventory_editable_flag_gates_count(self):
        editable_item = self.data["inventory"][0]  # Healing Grape, editable
        self.assertFalse(octo_game.read_only_check(editable_item, "count", editable_item["count"]))
        self.assertTrue(octo_game.read_only_check(editable_item, "name", editable_item["name"]))

        readonly_item = {"id": 302, "name": "Translated Tome", "category": "Valuable",
                          "editable": False, "count": 1}
        self.assertTrue(octo_game.read_only_check(readonly_item, "count", 1))

    def test_capture_fields(self):
        slot = self.data["capture"]["slots"][0]
        for field in ("id", "count", "used"):
            self.assertFalse(octo_game.read_only_check(slot, field, slot[field]))
        self.assertTrue(octo_game.read_only_check(slot, "name", slot["name"]))

    def test_internal_keys_always_read_only(self):
        self.assertTrue(octo_game.read_only_check(self.data, "_offsets", {}))


class TestDumpsRoundTrip(unittest.TestCase):
    def setUp(self):
        self.raw = fake_ot1_save()

    def test_character_stat_edit_round_trips(self):
        data = octo_game.loads(self.raw)
        data["characters"][1]["level"] = 42
        data["money"] = 9999
        new_bytes = octo_game.dumps(data)
        self.assertEqual(len(new_bytes), len(self.raw))
        reparsed = octo_game.loads(new_bytes)
        self.assertEqual(reparsed["money"], 9999)
        self.assertEqual(reparsed["characters"][1]["level"], 42)

    def test_equipment_swap_round_trips(self):
        data = octo_game.loads(self.raw)
        sword_slot = next(s for s in data["characters"][0]["equipment"] if s["slot_key"] == "Sword")
        sword_slot["id"] = 1002  # Haralds Sword - still a Sword, should be fine
        new_bytes = octo_game.dumps(data)
        reparsed = octo_game.loads(new_bytes)
        new_sword = next(s for s in reparsed["characters"][0]["equipment"] if s["slot_key"] == "Sword")
        self.assertEqual(new_sword["id"], 1002)
        self.assertEqual(new_sword["name"], "Haralds Sword")

    def test_equipment_wrong_category_rejected(self):
        data = octo_game.loads(self.raw)
        sword_slot = next(s for s in data["characters"][0]["equipment"] if s["slot_key"] == "Sword")
        sword_slot["id"] = 1601  # a Shield, not a Sword
        with self.assertRaises(ValueError):
            octo_game.dumps(data)

    def test_equipment_unequip_round_trips(self):
        data = octo_game.loads(self.raw)
        sword_slot = next(s for s in data["characters"][0]["equipment"] if s["slot_key"] == "Sword")
        sword_slot["id"] = None
        new_bytes = octo_game.dumps(data)
        reparsed = octo_game.loads(new_bytes)
        new_sword = next(s for s in reparsed["characters"][0]["equipment"] if s["slot_key"] == "Sword")
        self.assertIsNone(new_sword["id"])

    def test_inventory_count_edit_round_trips(self):
        data = octo_game.loads(self.raw)
        data["inventory"][0]["count"] = 50
        new_bytes = octo_game.dumps(data)
        reparsed = octo_game.loads(new_bytes)
        self.assertEqual(reparsed["inventory"][0]["count"], 50)

    def test_inventory_count_out_of_bounds_rejected(self):
        data = octo_game.loads(self.raw)
        data["inventory"][0]["count"] = 100  # limit is 0-99
        with self.assertRaises(ValueError):
            octo_game.dumps(data)

    def test_inventory_new_item_fills_empty_slot(self):
        data = octo_game.loads(self.raw)
        data["inventory"].append({"id": 2, "name": "Healing Grape M", "category": "Item",
                                   "editable": True, "count": 5})
        new_bytes = octo_game.dumps(data)
        reparsed = octo_game.loads(new_bytes)
        counts = {row["id"]: row["count"] for row in reparsed["inventory"]}
        self.assertEqual(counts.get(2), 5)
        self.assertEqual(len(reparsed["_inventory_empty"]), 0)  # the one empty slot got used

    def test_inventory_no_empty_slot_rejected(self):
        data = octo_game.loads(self.raw)
        # Consume the save's only empty slot first, then try to add a second new item.
        data["inventory"].append({"id": 2, "name": "Healing Grape M", "category": "Item",
                                   "editable": True, "count": 1})
        data["inventory"].append({"id": 3, "name": "Healing Grape Bunch", "category": "Item",
                                   "editable": True, "count": 1})
        with self.assertRaises(ValueError):
            octo_game.dumps(data)

    def test_inventory_zeroing_existing_item_frees_its_slot(self):
        data = octo_game.loads(self.raw)
        data["inventory"][0]["count"] = 0
        new_bytes = octo_game.dumps(data)
        reparsed = octo_game.loads(new_bytes)
        self.assertEqual(len(reparsed["inventory"]), 0)
        self.assertEqual(len(reparsed["_inventory_empty"]), 2)

    def test_inventory_progression_item_rejected_even_if_smuggled_in(self):
        # Simulates a raw-JSON paste bypassing the UI's own read_only_check -
        # dumps() must still refuse to write a progression-linked item.
        data = octo_game.loads(self.raw)
        data["inventory"].append({"id": 302, "name": "Translated Tome", "category": "Valuable",
                                   "editable": False, "count": 1})
        with self.assertRaises(ValueError):
            octo_game.dumps(data)

    def test_capture_edit_round_trips(self):
        data = octo_game.loads(self.raw)
        data["capture"]["slots"][0]["count"] = 9
        data["capture"]["slots"][1]["id"] = 2  # fill the empty slot
        new_bytes = octo_game.dumps(data)
        reparsed = octo_game.loads(new_bytes)
        self.assertEqual(reparsed["capture"]["slots"][0]["count"], 9)
        self.assertEqual(reparsed["capture"]["slots"][1]["name"], "Highland Ratkin II")

    def test_capture_clear_round_trips(self):
        data = octo_game.loads(self.raw)
        data["capture"]["slots"][0]["id"] = None
        new_bytes = octo_game.dumps(data)
        reparsed = octo_game.loads(new_bytes)
        self.assertIsNone(reparsed["capture"]["slots"][0]["id"])

    def test_capture_unknown_monster_rejected(self):
        data = octo_game.loads(self.raw)
        data["capture"]["slots"][1]["id"] = 999999
        with self.assertRaises(ValueError):
            octo_game.dumps(data)

    def test_unrelated_fields_are_unaffected_by_a_single_edit(self):
        data = octo_game.loads(self.raw)
        data["characters"][3]["level"] = 77
        new_bytes = octo_game.dumps(data)
        reparsed = octo_game.loads(new_bytes)
        # every OTHER character's stats should be untouched
        for i, row in enumerate(reparsed["characters"]):
            if i == 3:
                continue
            self.assertEqual(row["level"], i + 1)


if __name__ == "__main__":
    unittest.main()
