"""
Unit tests for games/bbee.py + lib/bbee_lib.py + lib/bbee_wire.py - no
PySide6/display required.

Imports games.bbee directly (bypassing games/__init__.py, which also
imports games/dredge.py and therefore PySide6), same as test_octopath.py
and test_dave.py.

The wire-format tests (parse_message/encode_message/edit_ap) operate on
already-decompressed protobuf bytes and need no external tool. The
loads()/dumps() tests need the real `lz4` CLI (see lib/bbee_lib.py) since
this profile intentionally shells out to it rather than reimplementing
LZ4 framing in Python untested against a real save - they're skipped
automatically wherever that binary isn't installed (this sandbox
included; it does run on a real macOS dev machine with `brew install
lz4`, and should be installed in CI too).

Run:
    python3 -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "games"))

import bbee as bbee_game  # noqa: E402

from lib import bbee_lib  # noqa: E402
from lib.bbee_wire import Field, WireError, encode_message, parse_message  # noqa: E402

_HAS_LZ4 = bool(os.environ.get("BBEE_LZ4") or shutil.which("lz4"))


def _message(*fields):
    return encode_message(list(fields))


def _b(number, value):
    return Field(number, 2, value.encode() if isinstance(value, str) else value)


def _v(number, value):
    return Field(number, 0, value)


def fixture(ap=200):
    """A byte-forged synthetic BBEE save (adapted verbatim from bbee-se's
    own tests/test_editor.py fixture()) - decompressed protobuf bytes,
    not yet LZ4-compressed."""
    currency_value = _message(_v(1, 1), _v(2, ap), _b(8, b"keep-value"))
    currency_entry = _message(_v(1, 1), _b(2, currency_value), _v(9, 77))
    currency_pack = _message(_b(1, currency_entry), _b(7, b"keep-pack"))
    payload = _message(_b(1, currency_pack), _v(6, 11))
    currency_model = _message(_b(1, "ModelPlayerNewCurrencyPack"), _b(2, payload), _b(12, b"keep-model"))
    other_model = _message(_b(1, "ModelUnknownFutureData"), _b(2, b"\x08\x96\x01"))
    return _message(_b(1, "AutoSave"), _b(2, other_model), _b(2, currency_model), _v(6, 11718))


class TestWireRoundTrip(unittest.TestCase):
    def test_round_trip_is_byte_identical(self):
        raw = fixture()
        self.assertEqual(encode_message(parse_message(raw)), raw)

    def test_rejects_truncated_varint(self):
        with self.assertRaises(WireError):
            parse_message(b"\x80")


class TestLocateAndEditAp(unittest.TestCase):
    def test_inspects_ap_and_models(self):
        info = bbee_lib.inspect_decoded(fixture(1931))
        self.assertEqual(info.ap, 1931)
        self.assertEqual(info.model_count, 2)

    def test_edits_only_the_requested_nested_value(self):
        original = fixture()
        edited = bbee_lib.edit_ap(original, 987654)
        self.assertEqual(bbee_lib.inspect_decoded(edited).ap, 987654)
        for marker in (b"keep-value", b"keep-pack", b"keep-model", b"ModelUnknownFutureData"):
            self.assertEqual(original.count(marker), edited.count(marker))

    def test_rejects_out_of_range_ap(self):
        for value in (-1, bbee_lib.MAX_AP + 1):
            with self.assertRaises(bbee_lib.SaveFormatError):
                bbee_lib.edit_ap(fixture(), value)

    def test_rejects_wrong_save_signature(self):
        wrong = _message(_b(1, "ManualSave"))
        with self.assertRaises(bbee_lib.SaveFormatError):
            bbee_lib.inspect_decoded(wrong)


class TestProfileWiring(unittest.TestCase):
    def test_profile_basics(self):
        p = bbee_game.PROFILE
        self.assertEqual(p.key, "bbee")
        self.assertTrue(p.binary)
        self.assertEqual(p.quick_fields, {"Analysis Points": ["AnalysisPoints"]})

    def test_read_only_check(self):
        check = bbee_game.PROFILE.read_only_check
        self.assertFalse(check({}, "AnalysisPoints", 5))
        self.assertTrue(check({}, "_model_count", 2))
        self.assertTrue(check({}, "_raw_size", 2))
        self.assertTrue(check({}, "SomethingElse", 2))

    def test_file_pattern_matches_single_digit_slots(self):
        import fnmatch
        pattern = bbee_game.PROFILE.file_patterns[0][1]
        for name in ("1", "9"):
            self.assertTrue(fnmatch.fnmatch(name, pattern))
        for name in ("0", "10", "save.json"):
            self.assertFalse(fnmatch.fnmatch(name, pattern))

    def test_dumps_rejects_non_bbee_data(self):
        with self.assertRaises(ValueError):
            bbee_game.dumps({"AnalysisPoints": 5})

    def test_dumps_rejects_non_integer_ap(self):
        data = bbee_game.BbeeData({"AnalysisPoints": "lots"})
        data._raw = b"whatever"
        with self.assertRaises(ValueError):
            bbee_game.dumps(data)

    def test_dumps_rejects_bool_ap(self):
        # bool is a subclass of int - must not silently pass as a valid AP.
        data = bbee_game.BbeeData({"AnalysisPoints": True})
        data._raw = b"whatever"
        with self.assertRaises(ValueError):
            bbee_game.dumps(data)


@unittest.skipUnless(_HAS_LZ4, "requires the lz4 command-line tool (brew install lz4)")
class TestLoadsDumpsRoundTrip(unittest.TestCase):
    def test_loads_reads_ap_and_dumps_edits_it(self):
        original_lz4 = bbee_lib.compress_to_bytes(fixture(200))
        data = bbee_game.loads(original_lz4)
        self.assertEqual(data["AnalysisPoints"], 200)
        self.assertEqual(data["_model_count"], 2)

        data["AnalysisPoints"] = 54321
        edited_lz4 = bbee_game.dumps(data)
        self.assertNotEqual(edited_lz4, original_lz4)

        reloaded = bbee_game.loads(edited_lz4)
        self.assertEqual(reloaded["AnalysisPoints"], 54321)

    def test_dumps_preserves_unrelated_bytes_through_full_round_trip(self):
        original_lz4 = bbee_lib.compress_to_bytes(fixture(1))
        data = bbee_game.loads(original_lz4)
        data["AnalysisPoints"] = 2
        edited_lz4 = bbee_game.dumps(data)

        original_decoded = bbee_lib.decompress_bytes(original_lz4)
        edited_decoded = bbee_lib.decompress_bytes(edited_lz4)
        for marker in (b"keep-value", b"keep-pack", b"keep-model", b"ModelUnknownFutureData"):
            self.assertEqual(original_decoded.count(marker), edited_decoded.count(marker))

    def test_dumps_out_of_range_ap_raises(self):
        original_lz4 = bbee_lib.compress_to_bytes(fixture(1))
        data = bbee_game.loads(original_lz4)
        data["AnalysisPoints"] = bbee_lib.MAX_AP + 1
        with self.assertRaises(ValueError):
            bbee_game.dumps(data)


if __name__ == "__main__":
    unittest.main()
