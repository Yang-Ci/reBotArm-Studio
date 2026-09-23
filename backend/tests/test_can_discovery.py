from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from rebotd.can_discovery import configure_socketcan, scan_socketcan  # noqa: E402


class CanDiscoveryTests(unittest.TestCase):
    def test_finds_ready_peak_adapter_and_ignores_non_can(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            can = root / "can0"
            can.mkdir()
            (can / "type").write_text("280\n")
            (can / "operstate").write_text("up\n")
            (can / "carrier").write_text("1\n")
            (can / "device").mkdir()
            (can / "device" / "uevent").write_text("DRIVER=peak_usb\n")
            ethernet = root / "eth0"
            ethernet.mkdir()
            (ethernet / "type").write_text("1\n")

            def fake_run(*_args, **_kwargs):
                payload = [{
                    "flags": ["UP", "LOWER_UP"],
                    "linkinfo": {"info_data": {
                        "state": "ERROR-ACTIVE",
                        "berr_counter": {"tx": 0, "rx": 0},
                        "bittiming": {"bitrate": 1_000_000},
                    }},
                }]
                return CompletedProcess([], 0, json.dumps(payload), "")

            devices = scan_socketcan(sys_class_net=root, run=fake_run)

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["channel"], "can0")
        self.assertEqual(devices[0]["adapter"], "PEAK-System PCAN-USB")
        self.assertTrue(devices[0]["ready"])

    def test_rejects_wrong_bitrate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            can = root / "can1"
            can.mkdir()
            (can / "type").write_text("280")
            (can / "operstate").write_text("up")

            def fake_run(*_args, **_kwargs):
                payload = [{
                    "flags": ["UP"],
                    "linkinfo": {"info_data": {
                        "state": "ERROR-ACTIVE",
                        "bittiming": {"bitrate": 500_000},
                    }},
                }]
                return CompletedProcess([], 0, json.dumps(payload), "")

            device = scan_socketcan(sys_class_net=root, run=fake_run)[0]

        self.assertFalse(device["ready"])
        self.assertEqual(device["bitrate"], 500_000)

    def test_configures_interface_without_a_shell(self) -> None:
        commands = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            return CompletedProcess(command, 0, "", "")

        configure_socketcan("can0", run=fake_run)

        self.assertEqual(commands[0], ["ip", "link", "set", "dev", "can0", "down"])
        self.assertIn("1000000", commands[1])
        self.assertEqual(commands[2], ["ip", "link", "set", "dev", "can0", "up"])

    def test_rejects_invalid_interface_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid CAN interface"):
            configure_socketcan("can0; reboot")
