"""
Unit tests for games/dave.py - pure Python, no PySide6/display required.

Imports games.dave directly (bypassing games/__init__.py, which also
imports games/dredge.py and therefore PySide6) the same way
test_octopath.py does for games/octopath.py.

Run:
    python3 -m unittest discover -s tests -v
"""
import os
import sys
import json
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "games"))

import dave as dave_game  # noqa: E402


class TestCodecRoundTrip(unittest.TestCase):
    def test_round_trips_ascii(self):
        data = {"PlayerInfo": {"m_Gold": 12345, "m_Bei": 0}}
        encoded = dave_game._dumps(data)
        self.assertIsInstance(encoded, bytes)
        self.assertEqual(dave_game._loads(encoded), data)

    def test_round_trips_non_ascii_text(self):
        # Per-UTF-16-code-unit XOR (not per-byte) is exactly what makes
        # this safe for saves containing non-ASCII text (e.g. CJK names).
        data = {"PlayerName": "다이브 선장", "emoji": "🐟"}
        encoded = dave_game._dumps(data)
        self.assertEqual(dave_game._loads(encoded), data)

    def test_encoded_bytes_are_not_plain_json(self):
        data = {"secret": "value"}
        encoded = dave_game._dumps(data)
        with self.assertRaises((UnicodeDecodeError, json.JSONDecodeError, ValueError)):
            json.loads(encoded.decode("utf-8"))

    def test_matches_known_scheme_manually(self):
        # Sanity check against the XOR scheme spelled out directly, not
        # via the module's own helper - catches a self-cancelling bug in
        # _xor_units that a round-trip test alone wouldn't.
        text = '{"a":1}'
        key = [ord(c) for c in "GameData"]
        expected = bytes(
            "".join(chr(ord(c) ^ key[i % len(key)]) for i, c in enumerate(text)),
            "utf-8",
        )
        self.assertEqual(dave_game._dumps({"a": 1}), expected)


class TestProfile(unittest.TestCase):
    def test_profile_basics(self):
        p = dave_game.PROFILE
        self.assertEqual(p.key, "dave")
        self.assertTrue(p.binary)
        self.assertIn("Gold", p.quick_fields)
        self.assertEqual(p.quick_fields["Gold"], ["PlayerInfo", "m_Gold"])

    def test_profile_dump_load_roundtrip(self):
        p = dave_game.PROFILE
        data = {"PlayerInfo": {"m_Gold": 999}}
        self.assertEqual(p.loads(p.dump(data)), data)

    def test_file_pattern_matches_both_naming_conventions(self):
        # dave-editor's own is_gd_save() accepts both "GameSave_00_GD.sav"
        # and "m_..._GD.sav" - a single "*_GD.sav" glob covers both, and
        # discover_saves()'s fnmatch-based matching is what actually acts
        # on file_patterns.
        import fnmatch
        pattern = dave_game.PROFILE.file_patterns[0][1]
        self.assertTrue(fnmatch.fnmatch("GameSave_00_GD.sav", pattern))
        self.assertTrue(fnmatch.fnmatch("m_12345_GD.sav", pattern))
        self.assertFalse(fnmatch.fnmatch("GameSave_00_PZ.sav", pattern))

    def test_default_save_dirs_are_under_application_support(self):
        for d in dave_game.PROFILE.default_save_dirs:
            self.assertIn("Application Support", d)


class TestPreSaveCheck(unittest.TestCase):
    def test_blocks_when_game_running(self):
        with mock.patch.object(dave_game, "_is_game_running", return_value=True), \
             mock.patch.object(dave_game, "_is_file_open", return_value=False):
            reason = dave_game._pre_save_check("/tmp/whatever.sav")
        self.assertIsNotNone(reason)
        self.assertIn("running", reason)

    def test_blocks_when_file_open_elsewhere(self):
        with mock.patch.object(dave_game, "_is_game_running", return_value=False), \
             mock.patch.object(dave_game, "_is_file_open", return_value=True):
            reason = dave_game._pre_save_check("/tmp/whatever.sav")
        self.assertIsNotNone(reason)
        self.assertIn("open", reason)

    def test_allows_when_safe(self):
        with mock.patch.object(dave_game, "_is_game_running", return_value=False), \
             mock.patch.object(dave_game, "_is_file_open", return_value=False):
            reason = dave_game._pre_save_check("/tmp/whatever.sav")
        self.assertIsNone(reason)

    def test_is_game_running_matches_process_name(self):
        fake_ps_output = "Finder\nDave the Diver\nDock\n"
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout=fake_ps_output)
            self.assertTrue(dave_game._is_game_running())

    def test_is_game_running_false_when_absent(self):
        fake_ps_output = "Finder\nDock\nSafari\n"
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout=fake_ps_output)
            self.assertFalse(dave_game._is_game_running())

    def test_is_game_running_fails_safe_on_error(self):
        with mock.patch("subprocess.run", side_effect=OSError("no ps")):
            self.assertFalse(dave_game._is_game_running())

    def test_is_file_open_false_when_file_missing(self):
        self.assertFalse(dave_game._is_file_open("/nonexistent/path/x.sav"))


class TestItemNamesCatalog(unittest.TestCase):
    def test_catalog_file_is_valid_json_with_entries(self):
        path = os.path.join(ROOT, "data", "dave", "item_names.json")
        with open(path, encoding="utf-8") as f:
            catalog = json.load(f)
        self.assertIsInstance(catalog, dict)
        self.assertGreater(len(catalog), 100)
        # spot-check a couple of known entries rather than the whole file
        self.assertEqual(catalog.get("41010113"), "Gold")


if __name__ == "__main__":
    unittest.main()
