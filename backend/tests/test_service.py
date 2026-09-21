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


if __name__ == "__main__":
    unittest.main()
