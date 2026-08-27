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


class TestInventoryState(unittest.TestCase):
    def test_backpack_state_has_no_capacity_but_notes_why(self):
        state = duckov_game.inventory_state(fixture(), "backpack")
        self.assertIsNone(state["capacity"])
        self.assertIn("isn't stored", state["capacity_note"])
        self.assertEqual(state["slots"], [{"position": 0, "instance_id": -116, "type_id": 594}])

    def test_playerstorage_state_has_real_capacity(self):
        state = duckov_game.inventory_state(fixture(), "playerstorage")
        self.assertEqual(state["capacity"], 4)
        self.assertIsNone(state["capacity_note"])
        self.assertEqual(state["slots"], [{"position": 0, "instance_id": -200, "type_id": 10}])

    def test_safe_state_is_empty(self):
        state = duckov_game.inventory_state(fixture(), "safe")
        self.assertEqual(state["capacity"], 2)
        self.assertEqual(state["slots"], [])

    def test_unknown_target_raises(self):
        with self.assertRaises(ValueError):
            duckov_game.inventory_state(fixture(), "nonexistent_target")

    def test_missing_container_raises(self):
        data = fixture()
        del data["Inventory/PlayerStorage"]
        with self.assertRaises(ValueError):
            duckov_game.inventory_state(data, "playerstorage")


class TestRemoveInventoryItem(unittest.TestCase):
    def test_removes_backpack_item_and_reference(self):
        data = fixture()
        duckov_game.remove_inventory_item(data, "backpack", -116)
        tree = data["Item/MainCharacterItemData"]["value"]
        ids = {e["instanceID"] for e in tree["entries"]}
        self.assertNotIn(-116, ids)
        root_entry = next(e for e in tree["entries"] if e["instanceID"] == tree["rootInstanceID"])
        self.assertEqual(root_entry["inventory"], [])

    def test_removes_backpack_item_and_nested_contents(self):
        data = fixture()
        tree = data["Item/MainCharacterItemData"]["value"]
        tree["entries"].append(
            {"instanceID": -117, "typeID": 999, "variables": [], "slotContents": [], "inventory": [], "inventorySortLocks": []}
        )
        entry_116 = next(e for e in tree["entries"] if e["instanceID"] == -116)
        entry_116["inventory"] = [{"position": 0, "instanceID": -117}]
        duckov_game.remove_inventory_item(data, "backpack", -116)
        ids = {e["instanceID"] for e in tree["entries"]}
        self.assertNotIn(-116, ids)
        self.assertNotIn(-117, ids)

    def test_rejects_removing_the_root_entry(self):
        data = fixture()
        before = copy.deepcopy(data)
        with self.assertRaises(ValueError):
            duckov_game.remove_inventory_item(data, "backpack", -100)
        self.assertEqual(data, before)

    def test_rejects_removing_a_non_top_level_item(self):
        # -108 is equipped via slotContents (PrimaryWeapon), not directly in
        # the backpack's own inventory list.
        data = fixture()
        before = copy.deepcopy(data)
        with self.assertRaises(ValueError):
            duckov_game.remove_inventory_item(data, "backpack", -108)
        self.assertEqual(data, before)

    def test_removes_playerstorage_slot(self):
        data = fixture()
        duckov_game.remove_inventory_item(data, "playerstorage", -200)
        inv = data["Inventory/PlayerStorage"]["value"]
        self.assertEqual(inv["entries"], [])

    def test_rejects_unknown_instance_in_playerstorage(self):
        data = fixture()
        before = copy.deepcopy(data)
        with self.assertRaises(ValueError):
            duckov_game.remove_inventory_item(data, "playerstorage", -999)
        self.assertEqual(data, before)

    def test_unknown_target_raises(self):
        data = fixture()
        with self.assertRaises(ValueError):
            duckov_game.remove_inventory_item(data, "nonexistent_target", -200)


class TestItemNames(unittest.TestCase):
    def test_catalog_loaded_and_nonempty(self):
        # A real catalog ships in data/duckov/item_names.json (see its
        # README for provenance) - this isn't a synthetic fixture like the
        # rest of this test module, it's asserting the actual bundled file
        # loaded successfully.
        self.assertGreater(len(duckov_game._ITEM_NAMES), 1000)

    def test_known_id_resolves_to_known_name(self):
        # typeID 252 is used as the fixture's equipped PrimaryWeapon above -
        # picked because it's also a real id in the bundled catalog.
        self.assertEqual(duckov_game.item_name(252), "S_AK74_Lv_2")

    def test_accepts_str_or_int_id(self):
        self.assertEqual(duckov_game.item_name("252"), duckov_game.item_name(252))

    def test_unknown_id_returns_none(self):
        self.assertIsNone(duckov_game.item_name(-999999))

    def test_describe_entry_only_fires_on_typeid_key(self):
        self.assertEqual(duckov_game._describe_entry(None, "typeID", 252), "S_AK74_Lv_2")
        self.assertIsNone(duckov_game._describe_entry(None, "instanceID", 252))
        self.assertIsNone(duckov_game._describe_entry(None, "typeID", "252"))  # must be an int, not str

    def test_item_catalog_covers_the_full_catalog_sorted_by_name(self):
        rows = duckov_game.item_catalog(fixture())
        self.assertEqual(len(rows), len(duckov_game._ITEM_NAMES))
        names = [name for name, _id in rows]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_item_catalog_ids_are_strings_and_resolve_back_to_their_name(self):
        rows = duckov_game.item_catalog(fixture())
        name, item_id = rows[0]
        self.assertIsInstance(item_id, str)
        self.assertEqual(duckov_game.item_name(item_id), name)


class TestProfileWiring(unittest.TestCase):
    def test_spawn_hooks_attached_to_profile(self):
        self.assertIs(duckov_game.PROFILE.spawn_item, duckov_game.spawn_item)
        self.assertIs(duckov_game.PROFILE.spawn_item_targets, duckov_game.spawn_item_targets)

    def test_inventory_hooks_attached_to_profile(self):
        self.assertIs(duckov_game.PROFILE.inventory_state, duckov_game.inventory_state)
        self.assertIs(duckov_game.PROFILE.remove_inventory_item, duckov_game.remove_inventory_item)

    def test_describe_entry_attached_to_profile(self):
        self.assertIs(duckov_game.PROFILE.describe_entry, duckov_game._describe_entry)

    def test_item_catalog_attached_to_profile(self):
        self.assertIs(duckov_game.PROFILE.item_catalog, duckov_game.item_catalog)

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
