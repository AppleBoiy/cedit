"""
Tests for games/mhw.py's struct (de)serialization and inventory hooks.

Full-file crypto (lib/mhw_crypto.py) is verified separately, against a
real save, at the point it was written - see its own module docstring.
Building a synthetic-but-valid encrypted SAVEDATA1000 fixture from
scratch for these tests isn't practical (every checksum depends on the
whole multi-megabyte buffer), so these tests instead work against a
plain decrypted buffer directly, monkeypatching lib.mhw_crypto's
decrypt_save/encrypt_save to identity functions - that isolates exactly
what this module is actually responsible for: mapping known byte offsets
to/from a Python dict, correctly and without disturbing anything else.
"""
import struct
import unittest
from unittest import mock

from games import mhw
from lib.mhw_crypto import SLOT_REGIONS


def _blank_buffer():
    """A buffer big enough to hold all three save slots at their real
    offsets, zeroed out - not a real save, just large enough to poke at
    with struct.pack_into/unpack_from the same way a real one would be."""
    slot0_off, slot0_len = SLOT_REGIONS[0]
    slot2_off, slot2_len = SLOT_REGIONS[2]
    size = slot2_off + slot2_len + 0x200
    return bytearray(size)


class TestHunterRoundTrip(unittest.TestCase):
    def test_pack_then_unpack_preserves_fields(self):
        raw = _blank_buffer()
        slot_off, _ = SLOT_REGIONS[0]
        hunter = {
            "name": "Test Hunter",
            "hunter_rank": 68,
            "master_rank": 56,
            "zeni": 15872842,
            "research_points": 22454,
            "hunter_rank_xp": 162698,
            "master_rank_xp": 92743,
            "playtime_seconds": 376189,
            "room_preference": 2,
        }
        mhw._pack_hunter(raw, slot_off, hunter)
        result = mhw._unpack_hunter(raw, slot_off)
        self.assertEqual(result, hunter)

    def test_long_name_truncated_not_overflowed(self):
        raw = _blank_buffer()
        slot_off, _ = SLOT_REGIONS[0]
        hunter = {
            "name": "x" * 200,  # way over the 64-byte field
            "hunter_rank": 1, "master_rank": 0, "zeni": 0, "research_points": 0,
            "hunter_rank_xp": 0, "master_rank_xp": 0, "playtime_seconds": 0,
            "room_preference": 0,
        }
        mhw._pack_hunter(raw, slot_off, hunter)  # must not raise/overflow
        result = mhw._unpack_hunter(raw, slot_off)
        self.assertLessEqual(len(result["name"]), 63)
        # and it shouldn't have corrupted the very next field (hunter_rank)
        self.assertEqual(result["hunter_rank"], 1)


class TestItemSlotsRoundTrip(unittest.TestCase):
    def test_item_pouch_round_trips(self):
        raw = _blank_buffer()
        slot_off, _ = SLOT_REGIONS[0]
        pouch = {
            "items": [{"id": i, "amount": i * 2} for i in range(mhw._ITEM_POUCH_ITEMS)],
            "ammo": [{"id": 0, "amount": 0} for _ in range(mhw._ITEM_POUCH_AMMO)],
        }
        mhw._pack_item_pouch(raw, slot_off, pouch)
        result = mhw._unpack_item_pouch(raw, slot_off)
        self.assertEqual(result, pouch)

    def test_storage_round_trips(self):
        raw = _blank_buffer()
        slot_off, _ = SLOT_REGIONS[0]
        storage = {
            "items": [{"id": 0, "amount": 0}] * mhw._STORAGE_ITEMS,
            "ammo": [{"id": 0, "amount": 0}] * mhw._STORAGE_AMMO,
            "materials": [{"id": 5, "amount": 99}] + [{"id": 0, "amount": 0}] * (mhw._STORAGE_MATERIALS - 1),
            "decorations": [{"id": 0, "amount": 0}] * mhw._STORAGE_DECORATIONS,
        }
        mhw._pack_storage(raw, slot_off, storage)
        result = mhw._unpack_storage(raw, slot_off)
        self.assertEqual(result, storage)

    def test_slots_dont_overlap_between_containers(self):
        """Writing into item_pouch shouldn't touch storage's bytes, and
        vice versa - a real risk given both are just fixed byte offsets."""
        raw = _blank_buffer()
        slot_off, _ = SLOT_REGIONS[0]
        pouch = {
            "items": [{"id": 999, "amount": 999} for _ in range(mhw._ITEM_POUCH_ITEMS)],
            "ammo": [{"id": 999, "amount": 999} for _ in range(mhw._ITEM_POUCH_AMMO)],
        }
        mhw._pack_item_pouch(raw, slot_off, pouch)
        storage = mhw._unpack_storage(raw, slot_off)
        self.assertTrue(all(e == {"id": 0, "amount": 0} for e in storage["items"]))


class TestEquipmentRoundTrip(unittest.TestCase):
    def test_round_trips_exposed_fields(self):
        raw = _blank_buffer()
        slot_off, _ = SLOT_REGIONS[0]
        equipment = [
            {"sort_index": -1, "category": -1, "type": -1, "id": 0, "level": 0,
             "points": 0, "decos": [-1, -1, -1], "pendant": -1}
            for _ in range(mhw._EQUIPMENT_COUNT)
        ]
        equipment[0] = {"sort_index": 0, "category": 1, "type": 0, "id": 252,
                         "level": 2, "points": 100, "decos": [5, -1, -1], "pendant": -1}
        mhw._pack_equipment(raw, slot_off, equipment)
        result = mhw._unpack_equipment(raw, slot_off)
        self.assertEqual(result, equipment)


class TestLoadsAndDumps(unittest.TestCase):
    """loads()/dumps() with the real crypto mocked to identity - see this
    module's own docstring for why."""

    def setUp(self):
        self.raw = bytes(_blank_buffer())
        # mock.patch.object (not a "games.mhw.x" string target) so this
        # doesn't depend on `games.mhw` still being bound as an attribute
        # of the `games` package - TestGamesImportsWithoutPySide6 in
        # tests/test_cli.py deliberately re-imports `games` fresh mid-suite,
        # which can transiently drop that attribute even though the module
        # itself (already bound to the local `mhw` name here) is unaffected.
        patcher1 = mock.patch.object(
            mhw, "decrypt_save",
            side_effect=lambda raw: (bytearray(raw), {0: True, 1: True, 2: True, 3: True}),
        )
        patcher2 = mock.patch.object(mhw, "encrypt_save", side_effect=lambda buf: bytes(buf))
        self.mock_decrypt = patcher1.start()
        self.mock_encrypt = patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)

    def test_loads_produces_three_slots(self):
        data = mhw.loads(self.raw)
        self.assertEqual(len(data["slots"]), 3)
        for slot in data["slots"]:
            self.assertIn("hunter", slot)
            self.assertIn("item_pouch", slot)
            self.assertIn("storage", slot)
            self.assertIn("equipment", slot)

    def test_edit_then_dump_then_reload_preserves_edit(self):
        data = mhw.loads(self.raw)
        data["slots"][0]["hunter"]["zeni"] = 42
        out = mhw.PROFILE.dump(data)
        data2 = mhw.loads(out)
        self.assertEqual(data2["slots"][0]["hunter"]["zeni"], 42)

    def test_dumps_rejects_foreign_data(self):
        with self.assertRaises(TypeError):
            mhw.dumps({"slots": []})

    def test_bad_region_checksum_raises(self):
        self.mock_decrypt.side_effect = lambda raw: (bytearray(raw), {0: False, 1: True, 2: True, 3: True})
        with self.assertRaises(ValueError):
            mhw.loads(self.raw)


class TestInventoryHooks(unittest.TestCase):
    def setUp(self):
        self.data = mhw.MHWSaveData()
        self.data.raw = bytearray()
        self.data["slots"] = [
            {
                "hunter": {"name": "Slot0", "hunter_rank": 1, "master_rank": 0, "zeni": 0,
                           "research_points": 0, "hunter_rank_xp": 0, "master_rank_xp": 0,
                           "playtime_seconds": 0, "room_preference": 0},
                "item_pouch": {
                    "items": [{"id": 0, "amount": 0}] * mhw._ITEM_POUCH_ITEMS,
                    "ammo": [{"id": 0, "amount": 0}] * mhw._ITEM_POUCH_AMMO,
                },
                "storage": {
                    "items": [{"id": 0, "amount": 0}] * mhw._STORAGE_ITEMS,
                    "ammo": [{"id": 0, "amount": 0}] * mhw._STORAGE_AMMO,
                    "materials": [{"id": 0, "amount": 0}] * mhw._STORAGE_MATERIALS,
                    "decorations": [{"id": 0, "amount": 0}] * mhw._STORAGE_DECORATIONS,
                },
                "equipment": [],
            }
        ]

    def test_spawn_into_empty_slot(self):
        msg = mhw.spawn_item(self.data, "0:item_pouch:items", 252, 3)
        self.assertIn("252", msg)
        self.assertEqual(self.data["slots"][0]["item_pouch"]["items"][0], {"id": 252, "amount": 3})

    def test_spawn_rejects_bad_item_id(self):
        with self.assertRaises(ValueError):
            mhw.spawn_item(self.data, "0:item_pouch:items", -1, 1)

    def test_spawn_fails_when_full(self):
        pouch = self.data["slots"][0]["item_pouch"]["items"]
        for i in range(len(pouch)):
            pouch[i] = {"id": 1, "amount": 1}
        with self.assertRaises(ValueError):
            mhw.spawn_item(self.data, "0:item_pouch:items", 5, 1)

    def test_inventory_state_reports_occupied_slots_only(self):
        self.data["slots"][0]["item_pouch"]["items"][3] = {"id": 42, "amount": 7}
        state = mhw.inventory_state(self.data, "0:item_pouch:items")
        self.assertEqual(state["capacity"], mhw._ITEM_POUCH_ITEMS)
        self.assertEqual(state["slots"], [{"position": 3, "instance_id": 3, "type_id": 42}])

    def test_remove_clears_slot(self):
        self.data["slots"][0]["item_pouch"]["items"][3] = {"id": 42, "amount": 7}
        mhw.remove_inventory_item(self.data, "0:item_pouch:items", 3)
        self.assertEqual(self.data["slots"][0]["item_pouch"]["items"][3], {"id": 0, "amount": 0})

    def test_remove_rejects_already_empty_slot(self):
        with self.assertRaises(ValueError):
            mhw.remove_inventory_item(self.data, "0:item_pouch:items", 0)

    def test_unknown_target_key_rejected(self):
        with self.assertRaises(ValueError):
            mhw.inventory_state(self.data, "0:not_a_container:items")

    def test_spawn_item_targets_lists_all_slots_and_containers(self):
        targets = mhw.spawn_item_targets(self.data)
        keys = [key for _label, key in targets]
        self.assertIn("0:item_pouch:items", keys)
        self.assertEqual(len(targets), len(mhw._CONTAINER_LABELS))  # only slot 0 populated here


class TestItemCatalog(unittest.TestCase):
    """games/mhw.py's item name catalog (data/mhw/item_names.json) - see
    data/mhw/README.md for how it was extracted."""

    def test_catalog_loaded_from_real_game_data(self):
        # A regression floor, not an exact count - data/mhw/item_names.json
        # is a real extracted file, not a fixture; this just confirms it's
        # actually there and non-trivial, not that its size is frozen.
        self.assertGreater(len(mhw._ITEM_NAMES), 1000)

    def test_item_name_known_and_unknown_ids(self):
        self.assertEqual(mhw.item_name(1), "Potion")
        self.assertIsNone(mhw.item_name(0))
        self.assertIsNone(mhw.item_name(99999999))

    def test_item_name_accepts_str_or_int(self):
        self.assertEqual(mhw.item_name("1"), mhw.item_name(1))

    def test_item_catalog_rows_sorted_by_name(self):
        rows = mhw.item_catalog(None)
        names = [name for name, _id in rows]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertIn(("Potion", "1"), rows)

    def test_describe_entry_names_item_pouch_slots(self):
        # An item_pouch/storage slot dict ({"id", "amount"}) gets a name...
        hint = mhw._describe_entry({"id": 1, "amount": 5}, "id", 1)
        self.assertEqual(hint, "Potion")

    def test_describe_entry_ignores_equipment_ids(self):
        # ...but an equipment entry's "id" is a different (unmapped) id
        # space - no "amount" key present, so it must not be looked up here.
        equipment_entry = {"sort_index": 0, "category": 1, "type": 0, "id": 1, "level": 0}
        self.assertIsNone(mhw._describe_entry(equipment_entry, "id", 1))

    def test_describe_entry_ignores_other_keys(self):
        self.assertIsNone(mhw._describe_entry({"id": 1, "amount": 5}, "amount", 5))


class TestProfileWiring(unittest.TestCase):
    def test_profile_basics(self):
        self.assertEqual(mhw.PROFILE.key, "mhw")
        self.assertTrue(mhw.PROFILE.binary)
        self.assertIsNotNone(mhw.PROFILE.spawn_item_targets)
        self.assertIsNotNone(mhw.PROFILE.spawn_item)
        self.assertIsNotNone(mhw.PROFILE.inventory_state)
        self.assertIsNotNone(mhw.PROFILE.remove_inventory_item)
        self.assertIsNotNone(mhw.PROFILE.describe_entry)
        self.assertIsNotNone(mhw.PROFILE.item_catalog)
        self.assertIsNotNone(mhw.PROFILE.custom_launcher)

    def test_registered_in_games_registry(self):
        from games import get_game
        self.assertIs(get_game("mhw"), mhw.PROFILE)

    def test_custom_launcher_defers_pyside6_import(self):
        """games/mhw.py itself must stay importable with no PySide6 (see
        games/dredge.py's identical convention) - only games/mhw_window.py
        (imported lazily inside launch()) may depend on it."""
        import ast
        import inspect
        source = inspect.getsource(mhw)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", None) or ""
                names = [a.name for a in node.names]
                self.assertNotIn("PySide6", [module] + names)


if __name__ == "__main__":
    unittest.main()
