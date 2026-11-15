"""Focused checks for source-backed identity and the four upload entrances."""

import os
import tempfile
import unittest
from unittest.mock import patch

import app
from hardware_identity import extract_log_identity


class FakeMessage:
    def __init__(self, kind, **fields):
        self.kind = kind
        self.__dict__.update(fields)

    def get_type(self):
        return self.kind


class FakeReader:
    def __init__(self, _path):
        self.messages = iter([
            FakeMessage("MSG", Message="APM:Copter V4.5"),
            FakeMessage("MSG", Message="PX4v2 004A002F 33345119 32383433"),
            FakeMessage("MSG", Message="Frame: QUAD"),
            FakeMessage("PARM", Name="BRD_TYPE", Value=2),
        ])

    def recv_match(self, **_kwargs):
        return next(self.messages, None)


class IdentityTests(unittest.TestCase):
    def make_file(self, suffix, content):
        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        with handle:
            handle.write(content)
        return handle.name

    def test_px4_board_target_is_not_a_retail_model(self):
        path = self.make_file(".ulg", b"ULog\x01\x12\x35" + b"\0" * 12)
        class FakeULog:
            def __init__(self, *_args, **_kwargs):
                self.msg_info_dict = {"ver_hw": "AUAV_X21", "ver_sw": "test-build"}
                self.initial_parameters = {"SYS_AUTOSTART": 10020}
        with patch("pyulog.ULog", FakeULog):
            identity = extract_log_identity(path)
        self.assertEqual(identity["board_target"], "AUAV_X21")
        self.assertIsNone(identity["hardware_model"])
        self.assertIsNone(identity["aircraft_model"])

    def test_dataflash_does_not_publish_device_identifier(self):
        path = self.make_file(".bin", b"\xa3\x95\x80\x80" + b"\0" * 12)
        with patch("pymavlink.DFReader.DFReader_binary", FakeReader):
            identity = extract_log_identity(path)
        self.assertEqual(identity["board_target"], "PX4v2")
        self.assertEqual(identity["vehicle_type"], "QUAD")
        self.assertNotIn("004A002F", repr(identity))

    def test_extension_mismatch_is_rejected(self):
        path = self.make_file(".ulg", b"not a log")
        with self.assertRaisesRegex(ValueError, "signature"):
            extract_log_identity(path)

    def test_four_entries_share_optional_confirmation(self):
        client = app.app.test_client()
        for slug in ("performance", "incident", "wind", "team"):
            with self.subTest(slug=slug):
                response = client.get("/start/" + slug)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'name="hardware_model_claim"', response.data)
                self.assertIn(b'name="hardware_model_confirmed"', response.data)
        context = app.extract_report_context({
            "hardware_model_claim": "Cube Orange",
            "hardware_model_confirmed": "on",
        })
        self.assertTrue(context["hardware_model_confirmed"])
        self.assertEqual(context["hardware_model_claim"], "Cube Orange")


if __name__ == "__main__":
    unittest.main()
