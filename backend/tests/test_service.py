from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from rebotd.drivers.fake_rs import FakeRSDriver  # noqa: E402
from rebotd.service import RobotService  # noqa: E402


class RobotServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.driver = FakeRSDriver()
        self.driver.connect()
        self.service = RobotService(
            self.driver,
            product_id="b601-rs",
            driver_name="fake_rs",
        )

    async def test_hello_and_snapshot(self) -> None:
        hello = await self.service.dispatch("system.hello")
        self.assertEqual(hello["productId"], "b601-rs")
        self.assertEqual(hello["jointNames"], self.driver.joint_names)
        snapshot = await self.service.dispatch("system.status")
        self.assertTrue(snapshot["enabled"])
        self.assertEqual(len(snapshot["position"]), 6)
        self.assertIn("controlReference", snapshot)

    async def test_joint_batch_and_gripper_use_explicit_units(self) -> None:
        await self.service.dispatch(
            "joint.set_targets",
            {"positions": {"joint1": 0.2, "joint3": -0.1}, "velocityLimit": 0.4},
        )
        snapshot = await self.service.dispatch("system.status")
        self.assertEqual(snapshot["stateMachine"], "LOWLEVEL_STREAMING")
        self.assertAlmostEqual(snapshot["controlTarget"][0], 0.2)
        self.assertAlmostEqual(snapshot["controlTarget"][2], -0.1)

        result = await self.service.dispatch("gripper.set", {"widthM": 0.0715})
        self.assertAlmostEqual(result["positionRad"], 5.0)

    async def test_gravity_rejects_joint_stream_and_is_idempotent(self) -> None:
        first = await self.service.dispatch("gravity.start")
        second = await self.service.dispatch("gravity.start")
        self.assertTrue(first["active"])
        self.assertTrue(second["alreadyActive"])
        with self.assertRaisesRegex(RuntimeError, "gravity compensation"):
            await self.service.dispatch(
                "joint.set_target", {"name": "joint1", "position": 0.1}
            )
        await self.service.dispatch("gravity.stop")
        result = await self.service.dispatch(
            "joint.set_target", {"name": "joint1", "position": 0.1}
        )
        self.assertTrue(result["accepted"])

    async def test_trajectory_executes_without_ros_messages(self) -> None:
        result = await self.service.dispatch(
            "trajectory.execute",
            {
                "teaching": True,
                "points": [
                    {"time": 0.0, "positions": [0, 0, 0, 0, 0, 0]},
                    {"time": 0.04, "positions": [0.01, -0.01, 0, 0, 0, 0]},
                ],
            },
        )
        self.assertGreaterEqual(result["duration"], 0.04)
        self.assertEqual(self.driver.state_machine, "IDLE")

    async def test_trajectory_is_rejected_during_safe_home(self) -> None:
        self.driver.set_state_machine("SAFE_HOMING")

        with self.assertRaisesRegex(RuntimeError, "SAFE_HOMING"):
            await self.service.dispatch(
                "trajectory.execute",
                {
                    "teaching": True,
                    "points": [
                        {"time": 0.0, "positions": [0, 0, 0, 0, 0, 0]},
                        {"time": 0.1, "positions": [0.01, 0, 0, 0, 0, 0]},
                    ],
                },
            )

        self.assertEqual(self.driver.state_machine, "SAFE_HOMING")

    async def test_disable_safe_homes_before_cutting_enable(self) -> None:
        await self.service.dispatch(
            "joint.set_target", {"name": "joint1", "position": 0.3}
        )
        await asyncio.sleep(0.02)
        result = await self.service.dispatch("arm.disable")
        self.assertFalse(self.driver.enabled)
        self.assertIn("disabled", result["message"])

    async def test_shutdown_after_explicit_disable_does_not_reenable(self) -> None:
        await self.service.dispatch("arm.disable")
        self.driver.shutdown(disable_after_safe_home=True)
        self.assertFalse(self.driver.enabled)


class DetachedRobotServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.created: list[FakeRSDriver] = []

        def factory(*, channel: str):
            self.assertEqual(channel, "can0")
            driver = FakeRSDriver()
            self.created.append(driver)
            return driver

        self.service = RobotService(
            product_id="b601-rs",
            driver_factory=factory,
            can_scanner=lambda: [{
                "channel": "can0",
                "driver": "peak_usb",
                "adapter": "PEAK-System PCAN-USB",
                "isUp": True,
                "carrier": True,
                "state": "ERROR-ACTIVE",
                "bitrate": 1_000_000,
                "txErrors": 0,
                "rxErrors": 0,
                "ready": True,
            }],
        )

    async def test_scan_connect_and_safe_disconnect(self) -> None:
        hello = await self.service.dispatch("system.hello")
        self.assertFalse(hello["hardwareConnected"])
        snapshot = await self.service.dispatch("system.status")
        self.assertEqual(snapshot["stateMachine"], "DISCONNECTED")

        scanned = await self.service.dispatch("hardware.scan")
        self.assertEqual(scanned["interfaces"][0]["adapter"], "PEAK-System PCAN-USB")
        connected = await self.service.dispatch("hardware.connect", {
            "channel": "can0",
            "productId": "b601-rs",
            "confirm": "I_UNDERSTAND_REBOTARM_WILL_MOVE",
        })
        self.assertTrue(connected["connected"])
        self.assertTrue(self.service.hardware_connected)

        disconnected = await self.service.dispatch("hardware.disconnect")
        self.assertFalse(disconnected["connected"])
        self.assertFalse(self.service.hardware_connected)
        self.assertFalse(self.created[0].enabled)

    async def test_connect_requires_explicit_confirmation(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "safety confirmation"):
            await self.service.dispatch("hardware.connect", {"channel": "can0"})

    async def test_commands_are_rejected_while_detached(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no robot is connected"):
            await self.service.dispatch("arm.enable")

    async def test_connect_configures_an_unready_interface(self) -> None:
        configured = []
        scans = 0

        def scanner():
            nonlocal scans
            scans += 1
            return [{
                "channel": "can0",
                "driver": "peak_usb",
                "adapter": "PEAK-System PCAN-USB",
                "state": "STOPPED" if scans == 1 else "ERROR-ACTIVE",
                "bitrate": 0 if scans == 1 else 1_000_000,
                "ready": scans > 1,
            }]

        service = RobotService(
            product_id="b601-rs",
            driver_factory=lambda *, channel: FakeRSDriver(),
            can_scanner=scanner,
            can_configurer=configured.append,
        )
        result = await service.dispatch("hardware.connect", {
            "channel": "can0",
            "productId": "b601-rs",
            "confirm": "I_UNDERSTAND_REBOTARM_WILL_MOVE",
        })

        self.assertTrue(result["connected"])
        self.assertEqual(configured, ["can0"])
        service.shutdown()

    async def test_failed_driver_connect_is_safely_cleaned_up(self) -> None:
        class FailingDriver(FakeRSDriver):
            def __init__(self) -> None:
                super().__init__()
                self.cleaned_up = False

            def connect(self) -> None:
                super().connect()
                raise RuntimeError("simulated connection failure")

            def shutdown(self, disable_after_safe_home: bool = True) -> None:
                self.cleaned_up = True
                super().shutdown(disable_after_safe_home)

        candidate = FailingDriver()
        service = RobotService(
            product_id="b601-rs",
            driver_factory=lambda *, channel: candidate,
            can_scanner=self.service._can_scanner,
        )

        with self.assertRaisesRegex(RuntimeError, "simulated connection failure"):
            await service.dispatch("hardware.connect", {
                "channel": "can0",
                "productId": "b601-rs",
                "confirm": "I_UNDERSTAND_REBOTARM_WILL_MOVE",
            })

        self.assertTrue(candidate.cleaned_up)
        self.assertFalse(candidate.enabled)
        self.assertFalse(service.hardware_connected)


if __name__ == "__main__":
    unittest.main()
