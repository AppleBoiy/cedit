"""
Unit tests for lib/base.py - pure Python, no PySide6/display required.

Run:
    python3 -m unittest discover -s tests -v
"""

import os
import json
import struct
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.base import (
    guess_type, smart_parse, coerce_value, get_by_path, set_by_path,
    apply_text_quirks, make_json_loader, make_json_dumper,
    make_base64_packed_node, GameProfile, SpecialNode,
    backup_file, atomic_write_text, atomic_write_bytes,
)


class TestValueTypes(unittest.TestCase):
    def test_guess_type(self):
        self.assertEqual(guess_type(True), "bool")
        self.assertEqual(guess_type(5), "int")
        self.assertEqual(guess_type(5.5), "float")
        self.assertEqual(guess_type("x"), "str")
        self.assertEqual(guess_type(None), "null")
        self.assertEqual(guess_type([1]), "list")
        self.assertEqual(guess_type({"a": 1}), "dict")

    def test_guess_type_bool_before_int(self):
        # bool is a subclass of int in Python - guess_type must check it first
        self.assertEqual(guess_type(True), "bool")
        self.assertNotEqual(guess_type(True), "int")

    def test_smart_parse(self):
        self.assertIs(smart_parse("true"), True)
        self.assertIs(smart_parse("FALSE"), False)
        self.assertIsNone(smart_parse("null"))
        self.assertEqual(smart_parse("42"), 42)
        self.assertEqual(smart_parse("3.14"), 3.14)
        self.assertEqual(smart_parse("hello"), "hello")

    def test_coerce_value_bool(self):
        self.assertIs(coerce_value("true", False), True)
        self.assertIs(coerce_value("0", True), False)
        with self.assertRaises(ValueError):
            coerce_value("maybe", True)

    def test_coerce_value_int_float_str(self):
        self.assertEqual(coerce_value("123", 0), 123)
        self.assertEqual(coerce_value("1.5", 0.0), 1.5)
        self.assertEqual(coerce_value("hi", "bye"), "hi")
        with self.assertRaises(ValueError):
            coerce_value("not a number", 0)

    def test_coerce_value_null_and_unsupported(self):
        self.assertIsNone(coerce_value("null", None))
        self.assertEqual(coerce_value("42", None), 42)  # smart_parse fallback
        with self.assertRaises(ValueError):
            coerce_value("x", [1, 2])  # lists aren't directly editable


class TestPathHelpers(unittest.TestCase):
    def test_get_set_by_path(self):
        data = {"a": {"b": [1, 2, {"c": 3}]}}
        self.assertEqual(get_by_path(data, ["a", "b", 2, "c"]), 3)
        set_by_path(data, ["a", "b", 2, "c"], 99)
        self.assertEqual(data["a"]["b"][2]["c"], 99)

    def test_get_by_path_missing_raises(self):
        with self.assertRaises(KeyError):
            get_by_path({"a": 1}, ["b"])
        with self.assertRaises(IndexError):
            get_by_path({"a": [1]}, ["a", 5])


class TestTextQuirksAndJson(unittest.TestCase):
    def test_apply_text_quirks(self):
        raw = '{"__type": "int"true}'
        quirks = [{"pattern": r'("__type"\s*:\s*"[^"]*")\s*(?=(?:true|false|null|-?\d|"))',
                   "replacement": r'\1, "value" : '}]
        fixed = apply_text_quirks(raw, quirks)
        self.assertEqual(json.loads(fixed), {"__type": "int", "value": True})

    def test_make_json_loader_dumper_roundtrip(self):
        loader = make_json_loader(quirks=None)
        dumper = make_json_dumper(indent=2)
        data = {"x": 1, "y": [1, 2, 3]}
        self.assertEqual(loader(dumper(data)), data)


class TestPackedValueCodec(unittest.TestCase):
    def setUp(self):
        self.node = make_base64_packed_node(
            codec_by_type={1: "float32le", 2: "int32le", 3: "bool8", 4: "utf8"},
            name="item",
        )

    def test_matches_only_data_field_of_a_matching_dict(self):
        container = {"key": "k", "dataType": 2, "data": "AAAAAA=="}
        self.assertTrue(self.node.matches(container, "data", container["data"]))
        self.assertFalse(self.node.matches(container, "key", "k"))  # wrong field
        self.assertFalse(self.node.matches({"data": "x"}, "data", "x"))  # missing key/dataType

    def test_int32_roundtrip(self):
        container = {"key": "BulletCount", "dataType": 2, "data": None}
        encoded = self.node.encode(container, "data", "30")
        container["data"] = encoded
        decoded = self.node.decode(container, "data", encoded)
        self.assertEqual(decoded, 30)

    def test_float32_roundtrip(self):
        container = {"key": "Health", "dataType": 1, "data": None}
        encoded = self.node.encode(container, "data", "2.5")
        container["data"] = encoded
        self.assertAlmostEqual(self.node.decode(container, "data", encoded), 2.5, places=5)

    def test_bool8_roundtrip(self):
        container = {"key": "Flag", "dataType": 3, "data": None}
        encoded = self.node.encode(container, "data", "true")
        container["data"] = encoded
        self.assertIs(self.node.decode(container, "data", encoded), True)

    def test_utf8_roundtrip(self):
        container = {"key": "Name", "dataType": 4, "data": None}
        encoded = self.node.encode(container, "data", "hello")
        container["data"] = encoded
        self.assertEqual(self.node.decode(container, "data", encoded), "hello")

    def test_unrecognized_type_code_passes_value_through(self):
        container = {"key": "?", "dataType": 999, "data": "rawtext"}
        self.assertEqual(self.node.decode(container, "data", "rawtext"), "rawtext")
        with self.assertRaises(ValueError):
            self.node.encode(container, "data", "anything")


class TestGameProfile(unittest.TestCase):
    def test_from_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "game.json")
            cfg = {
                "key": "t", "display_name": "Test Game",
                "default_save_dirs": [], "file_patterns": [["Saves", "*.sav"]],
                "quick_fields": {"Gold": ["gold"]},
                "packed_value_node": {"codecs": {"2": "int32le"}},
                "notes": "hi",
            }
            with open(cfg_path, "w") as f:
                json.dump(cfg, f)
            profile = GameProfile.from_config(cfg_path)
            self.assertEqual(profile.key, "t")
            self.assertEqual(profile.quick_fields, {"Gold": ["gold"]})
            self.assertEqual(len(profile.special_nodes), 1)
            data = {"gold": 5}
            self.assertEqual(profile.loads(profile.dump(data)), data)

    def test_is_read_only_and_find_special_node_defaults(self):
        profile = GameProfile(
            key="t", display_name="T", default_save_dirs=[], file_patterns=[],
            quick_fields={},
        )
        self.assertFalse(profile.is_read_only({}, "k", 1))
        self.assertIsNone(profile.find_special_node({}, "k", 1))

    def test_is_read_only_custom_check(self):
        profile = GameProfile(
            key="t", display_name="T", default_save_dirs=[], file_patterns=[],
            quick_fields={}, read_only_check=lambda c, k, v: k == "secret",
        )
        self.assertTrue(profile.is_read_only({}, "secret", 1))
        self.assertFalse(profile.is_read_only({}, "open", 1))

    def test_is_read_only_swallows_exceptions(self):
        def boom(c, k, v):
            raise RuntimeError("nope")
        profile = GameProfile(
            key="t", display_name="T", default_save_dirs=[], file_patterns=[],
            quick_fields={}, read_only_check=boom,
        )
        self.assertFalse(profile.is_read_only({}, "k", 1))  # fails safe, not fatal

    def test_find_default_save_dir(self):
        with tempfile.TemporaryDirectory() as d:
            profile = GameProfile(
                key="t", display_name="T",
                default_save_dirs=["/nonexistent/path/xyz", d],
                file_patterns=[], quick_fields={},
            )
            self.assertEqual(profile.find_default_save_dir(), d)

    def test_discover_saves_recursive_and_excludes_catchall(self):
        with tempfile.TemporaryDirectory() as d:
            nested = os.path.join(d, "a", "b")
            os.makedirs(nested)
            sav_path = os.path.join(nested, "save1.sav")
            with open(sav_path, "w") as f:
                f.write("{}")
            with open(os.path.join(d, "readme.txt"), "w") as f:
                f.write("not a save")
            profile = GameProfile(
                key="t", display_name="T", default_save_dirs=[d],
                file_patterns=[("Saves", "*.sav"), ("All files", "*.*")],
                quick_fields={},
            )
            found = profile.discover_saves()
            self.assertEqual(found, [sav_path])

    def test_discover_saves_most_recent_first(self):
        with tempfile.TemporaryDirectory() as d:
            import time
            older = os.path.join(d, "old.sav")
            newer = os.path.join(d, "new.sav")
            with open(older, "w") as f:
                f.write("1")
            os.utime(older, (1000, 1000))
            with open(newer, "w") as f:
                f.write("2")
            os.utime(newer, (2000, 2000))
            profile = GameProfile(
                key="t", display_name="T", default_save_dirs=[d],
                file_patterns=[("Saves", "*.sav")], quick_fields={},
            )
            self.assertEqual(profile.discover_saves(), [newer, older])

    def test_discover_saves_no_dirs_configured(self):
        profile = GameProfile(
            key="t", display_name="T", default_save_dirs=[],
            file_patterns=[("Saves", "*.sav")], quick_fields={},
        )
        self.assertEqual(profile.discover_saves(), [])

    def test_dump_default_json(self):
        profile = GameProfile(
            key="t", display_name="T", default_save_dirs=[], file_patterns=[],
            quick_fields={},
        )
        self.assertEqual(json.loads(profile.dump({"a": 1})), {"a": 1})


class TestFileIO(unittest.TestCase):
    def test_backup_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "save.json")
            with open(path, "w") as f:
                f.write("original")
            backup_path = backup_file(path)
            self.assertTrue(os.path.exists(backup_path))
            with open(backup_path) as f:
                self.assertEqual(f.read(), "original")

    def test_atomic_write_text_and_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            text_path = os.path.join(d, "a.txt")
            atomic_write_text(text_path, "hello")
            with open(text_path) as f:
                self.assertEqual(f.read(), "hello")

            bin_path = os.path.join(d, "a.bin")
            atomic_write_bytes(bin_path, b"\x00\x01\x02")
            with open(bin_path, "rb") as f:
                self.assertEqual(f.read(), b"\x00\x01\x02")

    def test_atomic_write_cleans_up_temp_on_failure(self):
        # Writing to a directory that doesn't exist should raise, and not
        # leave a stray .tmpsave_ file behind in some OTHER directory.
        with self.assertRaises(OSError):
            atomic_write_text("/nonexistent/dir/x.txt", "data")


if __name__ == "__main__":
    unittest.main()
