"""
Unit tests for lib/dredge_client.py's client-side validation and grid logic -
pure Python, no dotnet/PySide6/display required. The bridge invocation
itself (inspect_save/edit_save) needs a real local DREDGE install and isn't
testable here; see README.txt.

Run:
    python3 -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import dredge_client as bridge


class TestGridConfig(unittest.TestCase):
    def test_grid_config_name_for_inventory_clamps_tier(self):
        self.assertEqual(bridge.grid_config_name_for("inventory", 1), "Tier1Hull")
        self.assertEqual(bridge.grid_config_name_for("inventory", 5), "Tier5Hull")
        self.assertEqual(bridge.grid_config_name_for("inventory", 0), "Tier1Hull")
        self.assertEqual(bridge.grid_config_name_for("inventory", 99), "Tier5Hull")
        self.assertEqual(bridge.grid_config_name_for("inventory", None), "Tier1Hull")

    def test_grid_config_name_for_storage_containers(self):
        self.assertEqual(bridge.grid_config_name_for("storage"), "Storage")
        self.assertEqual(bridge.grid_config_name_for("overflowStorage"), "OverflowStorage")
        self.assertIsNone(bridge.grid_config_name_for("nonSpatialItems"))
        self.assertIsNone(bridge.grid_config_name_for("somethingElse"))

    def test_cell_accepts_no_config_is_permissive(self):
        self.assertTrue(bridge.cell_accepts(None, 0, 0, 1, 1))

    def test_cell_accepts_blocked_cell(self):
        config = {"cells": {(0, 0): {"itemType": 0, "itemSubtype": 0}}}
        self.assertFalse(bridge.cell_accepts(config, 0, 0, 1, 1))

    def test_cell_accepts_missing_cell_is_blocked(self):
        config = {"cells": {}}
        self.assertFalse(bridge.cell_accepts(config, 5, 5, 1, 1))

    def test_cell_accepts_wildcard_cell(self):
        config = {"cells": {(0, 0): {"itemType": -1, "itemSubtype": -1}}}
        self.assertTrue(bridge.cell_accepts(config, 0, 0, 7, 3))

    def test_cell_accepts_bitmask_match(self):
        # itemType 0b011 accepts anything overlapping bits 0b001 or 0b010
        config = {"cells": {(0, 0): {"itemType": 0b011, "itemSubtype": -1}}}
        self.assertTrue(bridge.cell_accepts(config, 0, 0, 0b010, -1))
        self.assertFalse(bridge.cell_accepts(config, 0, 0, 0b100, -1))


class TestValidatePatch(unittest.TestCase):
    def setUp(self):
        self.original = {
            "integers": {"hull-tier": 1},
            "booleans": {"flag": False},
            "strings": {"name": "Boat"},
            "floats": {"fuel": 50.0},
        }

    def test_valid_patch_passes_through(self):
        patch = {"integers": {"hull-tier": 3}}
        self.assertEqual(bridge.validate_patch(self.original, patch), patch)

    def test_rejects_non_dict_patch(self):
        with self.assertRaises(ValueError):
            bridge.validate_patch(self.original, ["not", "a", "dict"])

    def test_rejects_unknown_group(self):
        with self.assertRaises(ValueError):
            bridge.validate_patch(self.original, {"notagroup": {"x": 1}})

    def test_rejects_unknown_key(self):
        with self.assertRaises(ValueError):
            bridge.validate_patch(self.original, {"integers": {"never-existed": 1}})

    def test_rejects_wrong_type_for_boolean(self):
        with self.assertRaises(ValueError):
            bridge.validate_patch(self.original, {"booleans": {"flag": "yes"}})

    def test_rejects_wrong_type_for_string(self):
        with self.assertRaises(ValueError):
            bridge.validate_patch(self.original, {"strings": {"name": 123}})

    def test_rejects_non_integer_for_integer_group(self):
        with self.assertRaises(ValueError):
            bridge.validate_patch(self.original, {"integers": {"hull-tier": 2.5}})

    def test_accepts_whole_float_for_integer_group(self):
        patch = {"integers": {"hull-tier": 4.0}}
        bridge.validate_patch(self.original, patch)  # should not raise

    def test_rejects_bool_disguised_as_number(self):
        with self.assertRaises(ValueError):
            bridge.validate_patch(self.original, {"floats": {"fuel": True}})


class TestValidateInventoryOps(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "rod1": {"id": "rod1", "name": "Rod", "dimensions": [{"x": 0, "y": 0}],
                      "itemType": 2, "itemSubtype": 1},
        }
        self.save = {
            "inventory": {"items": [
                {"values": {"id": "rod1", "x": 0, "y": 0, "z": 0}},
            ]},
            "storage": {"items": []},
            "overflowStorage": {"items": []},
            "nonSpatialItems": [
                {"values": {"id": "keyitem1"}},
            ],
        }

    def test_rejects_non_list(self):
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, {"not": "a list"}, self.catalog)

    def test_rejects_too_many_ops(self):
        ops = [{"action": "remove", "container": "inventory", "index": 0, "id": "rod1"}] * 101
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, ops, self.catalog)

    def test_valid_spawn(self):
        ops = [{"action": "spawn", "id": "rod1", "target": "inventory", "x": 1, "y": 1, "z": 0}]
        result = bridge.validate_inventory_ops(self.save, ops, self.catalog)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["runtimeType"], "SpatialItemInstance")

    def test_spawn_unknown_item_rejected(self):
        ops = [{"action": "spawn", "id": "nope", "target": "inventory", "x": 0, "y": 0, "z": 0}]
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, ops, self.catalog)

    def test_spawn_bad_target_rejected(self):
        ops = [{"action": "spawn", "id": "rod1", "target": "nonSpatialItems", "x": 0, "y": 0, "z": 0}]
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, ops, self.catalog)

    def test_spawn_bad_rotation_rejected(self):
        ops = [{"action": "spawn", "id": "rod1", "target": "inventory", "x": 0, "y": 0, "z": 45}]
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, ops, self.catalog)

    def test_valid_remove(self):
        ops = [{"action": "remove", "container": "inventory", "index": 0, "id": "rod1"}]
        result = bridge.validate_inventory_ops(self.save, ops, self.catalog)
        self.assertEqual(result, [{"action": "remove", "container": "inventory", "index": 0, "id": "rod1"}])

    def test_remove_stale_id_rejected(self):
        # id doesn't match what's actually at that index anymore - the save
        # must have changed since the snapshot was taken
        ops = [{"action": "remove", "container": "inventory", "index": 0, "id": "wrong-id"}]
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, ops, self.catalog)

    def test_remove_out_of_range_index_rejected(self):
        ops = [{"action": "remove", "container": "inventory", "index": 99, "id": "rod1"}]
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, ops, self.catalog)

    def test_valid_move(self):
        ops = [{"action": "move", "container": "inventory", "index": 0, "id": "rod1",
                "x": 5, "y": 5, "z": 90}]
        result = bridge.validate_inventory_ops(self.save, ops, self.catalog)
        self.assertEqual(result[0]["x"], 5)
        self.assertEqual(result[0]["z"], 90)

    def test_move_cabin_item_rejected(self):
        ops = [{"action": "move", "container": "nonSpatialItems", "index": 0, "id": "keyitem1",
                "x": 0, "y": 0, "z": 0}]
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, ops, self.catalog)

    def test_valid_duplicate_defaults_to_overflow(self):
        ops = [{"action": "duplicate", "container": "inventory", "index": 0, "id": "rod1"}]
        result = bridge.validate_inventory_ops(self.save, ops, self.catalog)
        self.assertEqual(result[0]["target"], "overflowStorage")

    def test_duplicate_cannot_mix_spatial_and_nonspatial(self):
        ops = [{"action": "duplicate", "container": "nonSpatialItems", "index": 0, "id": "keyitem1",
                "target": "inventory"}]
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, ops, self.catalog)

    def test_unknown_action_rejected(self):
        ops = [{"action": "teleport", "container": "inventory", "index": 0, "id": "rod1"}]
        with self.assertRaises(ValueError):
            bridge.validate_inventory_ops(self.save, ops, self.catalog)

    def test_result_ordering_spawns_dupes_moves_then_removals_desc(self):
        ops = [
            {"action": "remove", "container": "inventory", "index": 0, "id": "rod1"},
            {"action": "spawn", "id": "rod1", "target": "inventory", "x": 0, "y": 0, "z": 0},
        ]
        result = bridge.validate_inventory_ops(self.save, ops, self.catalog)
        self.assertEqual([o["action"] for o in result], ["spawn", "remove"])


class TestCandidateLocations(unittest.TestCase):
    def test_returns_two_lists_of_paths(self):
        saves_dirs, managed_dirs = bridge.candidate_locations()
        self.assertIsInstance(saves_dirs, list)
        self.assertIsInstance(managed_dirs, list)
        self.assertTrue(len(saves_dirs) >= 1)
        self.assertTrue(len(managed_dirs) >= 1)


if __name__ == "__main__":
    unittest.main()
