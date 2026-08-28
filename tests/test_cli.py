"""
Unit tests for cli.py (cedit-cli) - pure Python, no PySide6/display
required. Confirms `import games` genuinely doesn't need PySide6 (the
whole point of the games/dredge.py + games/dredge_window.py split), then
exercises each subcommand against a synthetic save fixture, same shape as
tests/test_duckov.py's own fixture().

Run:
    python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import cli  # noqa: E402


def fixture():
    return {
        "EconomyData": {"__type": "x", "value": {"money": 1000}},
        "Item/MainCharacterItemData": {
            "__type": "ItemStatsSystem.Data.ItemTreeData,ItemStatsSystem",
            "value": {
                "rootInstanceID": -100,
                "entries": [
                    {
                        "instanceID": -100, "typeID": 0, "variables": [],
                        "slotContents": [], "inventory": [], "inventorySortLocks": [],
                    },
                ],
            },
        },
        "Inventory/PlayerStorage": {
            "__type": "x", "value": {"capacity": 4, "entries": [], "lockedIndexes": []},
        },
        "Inventory/Inventory_Safe": {
            "__type": "x", "value": {"capacity": 2, "entries": [], "lockedIndexes": []},
        },
    }


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.save_path = os.path.join(self.tmpdir.name, "Save_1.sav")
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump(fixture(), f)

    def tearDown(self):
        self.tmpdir.cleanup()

    def run_cli(self, *argv):
        """Runs cli.main(argv), returns stdout - raises SystemExit(1) the
        same way a real invocation would on a CliError."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(list(argv))
        return buf.getvalue()

    def load_save(self):
        with open(self.save_path, encoding="utf-8") as f:
            return json.load(f)


class TestGamesImportsWithoutPySide6(unittest.TestCase):
    def test_games_package_does_not_require_pyside6(self):
        # The entire point of splitting games/dredge_window.py out of
        # games/dredge.py: `import games` (which cli.py itself does at
        # module level) must not need PySide6 installed at all.
        import builtins
        real_import = builtins.__import__

        def blocking_import(name, *args, **kwargs):
            if name == "PySide6" or name.startswith("PySide6."):
                raise ImportError(f"blocked: {name}")
            return real_import(name, *args, **kwargs)

        for mod in ("games", "games.dredge", "games.dredge_window"):
            sys.modules.pop(mod, None)

        builtins.__import__ = blocking_import
        try:
            import games
            profiles = games.list_games()
        finally:
            builtins.__import__ = real_import
            for mod in ("games", "games.dredge", "games.dredge_window"):
                sys.modules.pop(mod, None)
            import games  # noqa: F401 - restore normal state for later tests

        self.assertIn("dredge", [p.key for p in profiles])


class TestListGames(CliTestCase):
    def test_lists_every_registered_game(self):
        out = self.run_cli("list-games")
        self.assertIn("duckov", out)
        self.assertIn("dredge", out)
        self.assertIn("custom_launcher only", out)


class TestGet(CliTestCase):
    def test_get_a_path(self):
        out = self.run_cli("get", "--game", "duckov", "--save", self.save_path, "--path", "EconomyData.value.money")
        self.assertEqual(json.loads(out), 1000)

    def test_get_whole_save_with_no_path(self):
        out = self.run_cli("get", "--game", "duckov", "--save", self.save_path)
        self.assertEqual(json.loads(out), fixture())

    def test_get_missing_path_errors_cleanly(self):
        with self.assertRaises(SystemExit):
            self.run_cli("get", "--game", "duckov", "--save", self.save_path, "--path", "NoSuchKey")

    def test_get_rejects_dredge(self):
        with self.assertRaises(SystemExit):
            self.run_cli("get", "--game", "dredge", "--save", self.save_path)


class TestSet(CliTestCase):
    def test_set_matches_existing_type_and_persists(self):
        self.run_cli("set", "--game", "duckov", "--save", self.save_path,
                     "--path", "EconomyData.value.money", "--value", "999999")
        self.assertEqual(self.load_save()["EconomyData"]["value"]["money"], 999999)

    def test_set_creates_a_backup_by_default(self):
        self.run_cli("set", "--game", "duckov", "--save", self.save_path,
                     "--path", "EconomyData.value.money", "--value", "5")
        backups = [f for f in os.listdir(self.tmpdir.name) if f.endswith(".bak") or ".bak" in f]
        self.assertTrue(backups)

    def test_set_no_backup_skips_it(self):
        self.run_cli("set", "--game", "duckov", "--save", self.save_path,
                     "--path", "EconomyData.value.money", "--value", "5", "--no-backup")
        backups = [f for f in os.listdir(self.tmpdir.name) if ".bak" in f]
        self.assertEqual(backups, [])

    def test_set_with_json_flag_parses_a_literal(self):
        self.run_cli("set", "--game", "duckov", "--save", self.save_path,
                     "--path", "EconomyData.value.money", "--value", "42", "--json")
        self.assertEqual(self.load_save()["EconomyData"]["value"]["money"], 42)


class TestTargets(CliTestCase):
    def test_lists_duckov_targets(self):
        out = self.run_cli("targets", "--game", "duckov", "--save", self.save_path)
        self.assertIn("backpack", out)
        self.assertIn("playerstorage", out)
        self.assertIn("safe", out)


class TestInventoryAndSpawnAndRemove(CliTestCase):
    def test_spawn_then_inventory_then_remove(self):
        self.run_cli("spawn", "--game", "duckov", "--save", self.save_path,
                     "--target", "backpack", "--item", "252", "--quantity", "2")
        out = self.run_cli("inventory", "--game", "duckov", "--save", self.save_path, "--target", "backpack")
        state = json.loads(out)
        self.assertEqual(len(state["slots"]), 2)
        self.assertIsNone(state["capacity"])

        instance_id = state["slots"][0]["instance_id"]
        self.run_cli("remove", "--game", "duckov", "--save", self.save_path,
                     "--target", "backpack", "--instance", str(instance_id))
        out = self.run_cli("inventory", "--game", "duckov", "--save", self.save_path, "--target", "backpack")
        self.assertEqual(len(json.loads(out)["slots"]), 1)

    def test_spawn_rejects_bad_item_id(self):
        with self.assertRaises(SystemExit):
            self.run_cli("spawn", "--game", "duckov", "--save", self.save_path,
                         "--target", "backpack", "--item", "-5", "--quantity", "1")
        # must not have mutated the file
        self.assertEqual(self.load_save(), fixture())


class TestCatalog(CliTestCase):
    def test_search_filters_by_name(self):
        out = self.run_cli("catalog", "--game", "duckov", "--search", "ak74")
        self.assertIn("S_AK74_Lv_2", out)
        for line in out.splitlines():
            self.assertIn("ak74", line.lower())

    def test_no_search_lists_everything(self):
        out = self.run_cli("catalog", "--game", "duckov")
        self.assertGreater(len(out.splitlines()), 1000)

    def test_rejects_a_profile_with_no_catalog(self):
        with self.assertRaises(SystemExit):
            self.run_cli("catalog", "--game", "octopath")


if __name__ == "__main__":
    unittest.main()
