"""
Unit tests for games/duckov.py's spawn_item support - pure Python, no
PySide6/display required.

Imports games.duckov directly (bypassing games/__init__.py, which also
imports games/dredge.py and therefore PySide6), same pattern as the other
games/*.py test modules.

The fixture below is a minimal but structurally faithful synthetic save
(not a real player's save file) - reverse-engineered from a real Escape
from Duckov save's Item/MainCharacterItemData, Inventory/PlayerStorage,
and Inventory/Inventory_Safe shapes; see games/duckov.py's own module
docstring for the container shapes this mirrors.

Run:
    python3 -m unittest discover -s tests -v
"""
import copy
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "games"))

import duckov as duckov_game  # noqa: E402


def fixture():
    return {
        "Item/MainCharacterItemData": {
            "__type": "ItemStatsSystem.Data.ItemTreeData,ItemStatsSystem",
            "value": {
                "rootInstanceID": -100,
                "entries": [
                    {
                        "instanceID": -100,
                        "typeID": 0,
                        "variables": [],
                        "slotContents": [
                            {"slot": "PrimaryWeapon", "instanceID": -108},
                        ],
                        "inventory": [
                            {"position": 0, "instanceID": -116},
                        ],
                        "inventorySortLocks": [],
                    },
                    {
                        "instanceID": -108,
                        "typeID": 252,
                        "variables": [],
                        "slotContents": [],
                        "inventory": [],
                        "inventorySortLocks": [],
                    },
                    {
                        "instanceID": -116,
                        "typeID": 594,
                        "variables": [],
                        "slotContents": [],
                        "inventory": [],
                        "inventorySortLocks": [],
                    },
                ],
            },
        },
        "Inventory/PlayerStorage": {
            "__type": "ItemStatsSystem.Data.InventoryData,ItemStatsSystem",
            "value": {
                "capacity": 4,
                "entries": [
                    {
                        "inventoryPosition": 0,
                        "itemTreeData": {
                            "rootInstanceID": -200,
                            "entries": [
                                {
                                    "instanceID": -200,
                                    "typeID": 10,
                                    "variables": [],
                                    "slotContents": [],
                                    "inventory": [],
                                    "inventorySortLocks": [],
                                },
                            ],
                        },
                    },
                ],
                "lockedIndexes": [],
            },
        },
        "Inventory/Inventory_Safe": {
            "__type": "ItemStatsSystem.Data.InventoryData,ItemStatsSystem",
            "value": {"capacity": 2, "entries": [], "lockedIndexes": []},
        },
    }


def all_instance_ids(data):
    seen = set()
    duckov_game._collect_instance_ids(data, seen)
    return seen


class TestSpawnItemTargets(unittest.TestCase):
    def test_returns_three_fixed_targets(self):
        targets = duckov_game.spawn_item_targets(fixture())
        keys = [key for _label, key in targets]
        self.assertEqual(keys, ["backpack", "playerstorage", "safe"])


class TestSpawnIntoBackpack(unittest.TestCase):
    def test_adds_entry_and_inventory_reference(self):
        data = fixture()
        before_ids = all_instance_ids(data)
        duckov_game.spawn_item(data, "backpack", 777, 1)

        tree = data["Item/MainCharacterItemData"]["value"]
        new_entries = [e for e in tree["entries"] if e["instanceID"] not in before_ids]
        self.assertEqual(len(new_entries), 1)
        self.assertEqual(new_entries[0]["typeID"], 777)

        root_entry = next(e for e in tree["entries"] if e["instanceID"] == tree["rootInstanceID"])
        refs = [c for c in root_entry["inventory"] if c["instanceID"] == new_entries[0]["instanceID"]]
        self.assertEqual(len(refs), 1)

    def test_skips_already_used_positions(self):
        data = fixture()  # position 0 already used by the fixture
        duckov_game.spawn_item(data, "backpack", 777, 1)
        tree = data["Item/MainCharacterItemData"]["value"]
        root_entry = next(e for e in tree["entries"] if e["instanceID"] == tree["rootInstanceID"])
        positions = [c["position"] for c in root_entry["inventory"]]
        self.assertEqual(sorted(positions), [0, 1])

    def test_quantity_creates_separate_entries_not_a_stack(self):
        data = fixture()
        before_ids = all_instance_ids(data)
        duckov_game.spawn_item(data, "backpack", 777, 3)
        tree = data["Item/MainCharacterItemData"]["value"]
        new_entries = [e for e in tree["entries"] if e["instanceID"] not in before_ids]
        self.assertEqual(len(new_entries), 3)
        for entry in new_entries:
            self.assertEqual(entry["typeID"], 777)
            self.assertEqual(entry["variables"], [])  # no fabricated "Count" stack

    def test_missing_container_raises_cleanly(self):
        data = fixture()
        del data["Item/MainCharacterItemData"]
        with self.assertRaises(ValueError):
            duckov_game.spawn_item(data, "backpack", 777, 1)


class TestSpawnIntoInventoryData(unittest.TestCase):
    def test_playerstorage_adds_entry(self):
        data = fixture()
        duckov_game.spawn_item(data, "playerstorage", 555, 1)
        inv = data["Inventory/PlayerStorage"]["value"]
        self.assertEqual(len(inv["entries"]), 2)
        new_entry = inv["entries"][-1]
        self.assertEqual(new_entry["inventoryPosition"], 1)  # 0 already used
        self.assertEqual(new_entry["itemTreeData"]["entries"][0]["typeID"], 555)
        self.assertEqual(
            new_entry["itemTreeData"]["rootInstanceID"],
            new_entry["itemTreeData"]["entries"][0]["instanceID"],
        )

    def test_safe_adds_entry(self):
        data = fixture()
        duckov_game.spawn_item(data, "safe", 42, 1)
        inv = data["Inventory/Inventory_Safe"]["value"]
        self.assertEqual(len(inv["entries"]), 1)
        self.assertEqual(inv["entries"][0]["inventoryPosition"], 0)

    def test_respects_capacity_and_does_not_mutate_on_failure(self):
        data = fixture()
        before = copy.deepcopy(data)
        with self.assertRaises(ValueError):
            duckov_game.spawn_item(data, "safe", 42, 3)  # capacity 2
        self.assertEqual(data, before)

    def test_fills_exactly_to_capacity(self):
        data = fixture()
        duckov_game.spawn_item(data, "safe", 42, 2)  # exactly fills capacity 2
        inv = data["Inventory/Inventory_Safe"]["value"]
        self.assertEqual(len(inv["entries"]), 2)

    def test_missing_container_raises_cleanly(self):
        data = fixture()
        del data["Inventory/Inventory_Safe"]
        with self.assertRaises(ValueError):
            duckov_game.spawn_item(data, "safe", 1, 1)


class TestSpawnItemValidation(unittest.TestCase):
    def test_rejects_zero_or_negative_item_id(self):
        data = fixture()
        for bad in (0, -5):
            with self.assertRaises(ValueError):
                duckov_game.spawn_item(data, "backpack", bad, 1)

    def test_rejects_non_integer_item_id(self):
        data = fixture()
        with self.assertRaises(ValueError):
            duckov_game.spawn_item(data, "backpack", "594", 1)

    def test_rejects_bool_item_id(self):
        data = fixture()
        with self.assertRaises(ValueError):
            duckov_game.spawn_item(data, "backpack", True, 1)

    def test_rejects_zero_or_negative_quantity(self):
        data = fixture()
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                duckov_game.spawn_item(data, "backpack", 594, bad)

    def test_rejects_unknown_target(self):
        data = fixture()
        with self.assertRaises(ValueError):
            duckov_game.spawn_item(data, "nonexistent_target", 594, 1)


class TestInstanceIdAllocation(unittest.TestCase):
    def test_new_ids_are_unique_and_more_negative_than_everything_existing(self):
        data = fixture()
        existing = all_instance_ids(data)
        duckov_game.spawn_item(data, "backpack", 1, 1)
        duckov_game.spawn_item(data, "playerstorage", 2, 1)
        duckov_game.spawn_item(data, "safe", 3, 1)
        after = all_instance_ids(data)
        new_ids = after - existing
        self.assertEqual(len(new_ids), 3)  # all mutually unique, none reused
        self.assertTrue(all(new_id < min(existing) for new_id in new_ids))


class TestProfileWiring(unittest.TestCase):
    def test_spawn_hooks_attached_to_profile(self):
        self.assertIs(duckov_game.PROFILE.spawn_item, duckov_game.spawn_item)
        self.assertIs(duckov_game.PROFILE.spawn_item_targets, duckov_game.spawn_item_targets)

    def test_spawned_item_survives_profile_dump_load_round_trip(self):
        data = fixture()
        duckov_game.spawn_item(data, "backpack", 999, 1)
        dumped = duckov_game.PROFILE.dump(data)
        reloaded = duckov_game.PROFILE.loads(dumped)
        tree = reloaded["Item/MainCharacterItemData"]["value"]
        type_ids = [e["typeID"] for e in tree["entries"]]
        self.assertIn(999, type_ids)


if __name__ == "__main__":
    unittest.main()
