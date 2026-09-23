from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from .can_discovery import configure_socketcan, scan_socketcan
from .trajectory import TrajectoryExecutor

GRIPPER_TRAVEL_M = 0.0715
GRIPPER_TRAVEL_RAD = 5.0


def gripper_width_to_motor(width_m: float) -> float:
    width = float(np.clip(float(width_m), 0.0, GRIPPER_TRAVEL_M))
    return width / GRIPPER_TRAVEL_M * GRIPPER_TRAVEL_RAD


def gripper_motor_to_width(position_rad: float) -> float:
    position = float(np.clip(float(position_rad), 0.0, GRIPPER_TRAVEL_RAD))
    return position / GRIPPER_TRAVEL_RAD * GRIPPER_TRAVEL_M


class RobotService:
    """Product-neutral command surface used by desktop IPC and WebSocket."""

    def __init__(
        self,
        driver=None,
        *,
        product_id: str,
        driver_name: str = "disconnected",
        channel: str = "",
        driver_factory: Callable[..., Any] | None = None,
        can_scanner: Callable[[], list[dict[str, Any]]] = scan_socketcan,
        can_configurer: Callable[[str], None] = configure_socketcan,
    ) -> None:
        self._driver = driver
        self.product_id = product_id
        self._driver_name = driver_name
        self._driver_factory = driver_factory
        self._can_scanner = can_scanner
        self._can_configurer = can_configurer
        self._hardware_lock = asyncio.Lock()
        self._channel = channel if driver is not None else ""
        self.trajectory = None if driver is None else TrajectoryExecutor(driver)
        self.started_at = time.time()

    @property
    def driver(self):
        if self._driver is None:
            raise RuntimeError("no robot is connected; scan and connect a CAN device first")
        return self._driver

    @property
    def hardware_connected(self) -> bool:
        return self._driver is not None

    @property
    def driver_enabled(self) -> bool:
        return bool(self._driver is not None and self._driver.enabled)

    @property
    def driver_name(self) -> str:
        return self._driver_name if self._driver is not None else "disconnected"

    async def dispatch(self, method: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        handlers = {
            "system.hello": self._hello,
            "system.ping": self._ping,
            "system.status": self.snapshot,
            "hardware.scan": self._scan_hardware,
            "hardware.connect": self._connect_hardware,
            "hardware.disconnect": self._disconnect_hardware,
            "arm.enable": self._enable,
            "arm.disable": self._safe_disable,
            "arm.safe_home": self._safe_home,
            "arm.hold": self._hold,
            "arm.set_zero": self._set_zero,
            "joint.set_target": self._set_joint_target,
            "joint.set_targets": self._set_joint_targets,
            "trajectory.execute": self._execute_trajectory,
            "trajectory.cancel": self._cancel_trajectory,
            "tcp.move_ik": self._move_ik,
            "tcp.move_trajectory": self._move_trajectory,
            "gripper.set": self._set_gripper,
            "gripper.open": self._open_gripper,
            "gripper.close": self._close_gripper,
            "gripper.release": self._release_gripper,
            "gripper.hold": self._hold_gripper,
            "gripper.assist_start": self._assist_gripper,
            "gripper.status": self._gripper_status,
            "gravity.start": self._start_gravity,
            "gravity.stop": self._stop_gravity,
            "gravity.status": self._gravity_status,
        }
        handler = handlers.get(method)
        if handler is None:
            raise ValueError(f"unknown method: {method}")
        result = handler(params)
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _hello(self, _params: dict) -> dict:
        return {
            "protocolVersion": 1,
            "productId": self.product_id,
            "driver": self.driver_name,
            "hardwareConnected": self.hardware_connected,
            "channel": self._channel,
            "jointNames": (
                list(self._driver.joint_names)
                if self._driver is not None
                else [f"joint{index}" for index in range(1, 7)]
            ),
            "capabilities": [
                "joint_streaming",
                "tcp_control",
                "gripper",
                "trajectory",
                "teaching",
                "safe_home",
                "set_zero",
                "gravity_compensation",
            ],
        }

    def _ping(self, _params: dict) -> dict:
        return {"time": time.time()}

    async def snapshot(self, _params: dict | None = None, *, request_feedback: bool = True) -> dict:
        if self._driver is None:
            return self._disconnected_snapshot()
        return await asyncio.to_thread(self._snapshot_sync, request_feedback)

    def _disconnected_snapshot(self) -> dict:
        zeros = [0.0] * 6
        return {
            "timestamp": time.time(),
            "productId": self.product_id,
            "driver": "disconnected",
            "hardwareConnected": False,
            "channel": "",
            "enabled": False,
            "mode": "disconnected",
            "stateMachine": "DISCONNECTED",
            "controlLoopActive": False,
            "jointNames": [f"joint{index}" for index in range(1, 7)],
            "position": zeros,
            "velocity": zeros,
            "torque": zeros,
            "statusCodes": [0] * 6,
            "errors": [],
            "controlTarget": zeros,
            "controlReference": zeros,
            "referenceVelocity": zeros,
            "referenceAcceleration": zeros,
            "gravity": {"active": False, "fault": ""},
            "gripper": {
                "positionRad": 0.0,
                "widthM": 0.0,
                "velocity": 0.0,
                "torque": 0.0,
                "statusCode": 0,
                "manualFree": False,
                "assistActive": False,
            },
        }

    def _snapshot_sync(self, request_feedback: bool) -> dict:
        driver = self.driver
        position, velocity, torque = driver.get_joint_state(
            request_feedback=request_feedback
        )
        target, reference, reference_velocity, reference_acceleration = (
            driver.get_control_reference()
        )
        gripper_position, gripper_velocity, gripper_torque, gripper_status = (
            driver.get_gripper_state(request_feedback=False)
        )
        return {
            "timestamp": time.time(),
            "productId": self.product_id,
            "driver": self.driver_name,
            "hardwareConnected": True,
            "channel": self._channel,
            "enabled": bool(driver.enabled),
            "mode": str(driver.mode),
            "stateMachine": str(driver.state_machine),
            "controlLoopActive": bool(driver.control_loop_active),
            "jointNames": list(driver.joint_names),
            "position": np.asarray(position, dtype=float).tolist(),
            "velocity": np.asarray(velocity, dtype=float).tolist(),
            "torque": np.asarray(torque, dtype=float).tolist(),
            "statusCodes": [int(value) for value in driver.get_joint_status_codes()],
            "errors": list(driver.error_codes),
            "controlTarget": np.asarray(target, dtype=float).tolist(),
            "controlReference": np.asarray(reference, dtype=float).tolist(),
            "referenceVelocity": np.asarray(reference_velocity, dtype=float).tolist(),
            "referenceAcceleration": np.asarray(reference_acceleration, dtype=float).tolist(),
            "gravity": {
                "active": bool(driver.gravity_compensation_active()),
                "fault": str(driver.gravity_compensation_fault()),
            },
            "gripper": {
                "positionRad": float(gripper_position),
                "widthM": gripper_motor_to_width(gripper_position),
                "velocity": float(gripper_velocity),
                "torque": float(gripper_torque),
                "statusCode": int(gripper_status),
                "manualFree": bool(driver.gripper_manual_free()),
                "assistActive": bool(driver.gripper_assist_active()),
            },
        }

    def _scan_hardware(self, _params: dict) -> dict:
        return {
            "interfaces": self._can_scanner(),
            "connected": self.hardware_connected,
            "connectedChannel": self._channel,
            "driver": self.driver_name,
        }

    async def _connect_hardware(self, params: dict) -> dict:
        channel = str(params.get("channel", "can0")).strip()
        confirmation = str(params.get("confirm", ""))
        if confirmation != "I_UNDERSTAND_REBOTARM_WILL_MOVE":
            raise RuntimeError("hardware connection requires explicit motion safety confirmation")
        if str(params.get("productId", self.product_id)) != self.product_id:
            raise ValueError(f"this daemon is configured for {self.product_id}")
        async with self._hardware_lock:
            if self._driver is not None:
                if channel == self._channel:
                    return {"connected": True, "channel": channel, "driver": self.driver_name}
                location = self._channel or "another driver"
                raise RuntimeError(f"a robot is already connected on {location}")
            if self._driver_factory is None:
                raise RuntimeError("this daemon does not support attaching hardware")
            interfaces = self._can_scanner()
            selected = next((item for item in interfaces if item["channel"] == channel), None)
            if selected is None:
                raise RuntimeError(f"CAN interface {channel!r} was not found")
            if not selected.get("ready"):
                await asyncio.to_thread(self._can_configurer, channel)
                interfaces = self._can_scanner()
                selected = next(
                    (item for item in interfaces if item["channel"] == channel),
                    None,
                )
                if selected is None or not selected.get("ready"):
                    raise RuntimeError(
                        f"CAN interface {channel!r} did not become ready at 1 Mbps"
                    )
            candidate = self._driver_factory(channel=channel)
            try:
                await asyncio.to_thread(candidate.connect)
            except Exception:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(candidate.shutdown, True)
                raise
            self._driver = candidate
            self._driver_name = "robstride_socketcan"
            self._channel = channel
            self.trajectory = TrajectoryExecutor(candidate)
            return {
                "connected": True,
                "channel": channel,
                "driver": self.driver_name,
                "adapter": selected.get("adapter", "SocketCAN"),
            }

    async def _disconnect_hardware(self, _params: dict) -> dict:
        async with self._hardware_lock:
            if self._driver is None:
                return {"connected": False, "message": "hardware already disconnected"}
            driver = self._driver
            await asyncio.to_thread(driver.shutdown, True)
            self._driver = None
            self._driver_name = "disconnected"
            self._channel = ""
            self.trajectory = None
            return {"connected": False, "message": "safe shutdown complete"}

    def shutdown(self) -> None:
        driver = self._driver
        if driver is None:
            return
        driver.shutdown(disable_after_safe_home=True)
        self._driver = None
        self._driver_name = "disconnected"
        self._channel = ""
        self.trajectory = None

    async def _enable(self, _params: dict) -> dict:
        await asyncio.to_thread(self.driver.enable)
        return {"message": "enabled"}

    async def _safe_disable(self, _params: dict) -> dict:
        def operation() -> dict:
            self.driver.stop_gravity_compensation()
            homed = False
            if self.driver.enabled and not self.driver.is_near_safe_home():
                self.driver.safe_home()
                if not self.driver.wait_until_near_safe_home():
                    raise RuntimeError("safe_home did not settle near zero; motors remain enabled")
                homed = True
            self.driver.disable()
            return {"message": "safe_home complete; disabled" if homed else "disabled"}

        return await asyncio.to_thread(operation)

    async def _safe_home(self, _params: dict) -> dict:
        def operation() -> dict:
            self.driver.safe_home()
            if not self.driver.wait_until_near_safe_home():
                raise RuntimeError("safe_home did not settle near zero")
            return {"message": "safe_home complete"}

        return await asyncio.to_thread(operation)

    async def _hold(self, _params: dict) -> dict:
        position = await asyncio.to_thread(self.driver.hold_current_position)
        return {"position": np.asarray(position, dtype=float).tolist()}

    async def _set_zero(self, params: dict) -> dict:
        joint_name = str(params.get("jointName", ""))
        self.driver.stop_gravity_compensation()
        success = await asyncio.to_thread(self.driver.set_zero, joint_name)
        return {"success": bool(success), "jointName": joint_name}

    async def _set_joint_target(self, params: dict) -> dict:
        name = str(params["name"])
        position = float(params["position"])
        velocity_limit = float(params.get("velocityLimit", 1.2))
        await asyncio.to_thread(
            self.driver.send_joint_mit_cmd,
            name,
            position,
            velocity_limit,
            0.0,
            0.0,
            0.0,
        )
        return {"accepted": True, "name": name, "position": position}

    async def _set_joint_targets(self, params: dict) -> dict:
        values = params.get("positions")
        if isinstance(values, dict):
            targets = {str(name): float(value) for name, value in values.items()}
        elif isinstance(values, list):
            if len(values) != len(self.driver.joint_names):
                raise ValueError(f"expected {len(self.driver.joint_names)} positions")
            targets = dict(zip(self.driver.joint_names, map(float, values)))
        else:
            raise ValueError("positions must be an object or array")
        unknown = sorted(set(targets) - set(self.driver.joint_names))
        if unknown:
            raise ValueError(f"unknown joints: {', '.join(unknown)}")
        velocity_limit = float(params.get("velocityLimit", 1.2))

        def operation() -> None:
            for name, position in targets.items():
                self.driver.send_joint_mit_cmd(
                    name, position, velocity_limit, 0.0, 0.0, 0.0
                )

        await asyncio.to_thread(operation)
        return {"accepted": True, "positions": targets}

    async def _execute_trajectory(self, params: dict) -> dict:
        if self.trajectory is None:
            raise RuntimeError("no robot is connected; scan and connect a CAN device first")
        points = list(params.get("points") or [])
        teaching = bool(params.get("teaching", False))
        return await asyncio.to_thread(
            self.trajectory.execute, points, teaching=teaching
        )

    def _cancel_trajectory(self, _params: dict) -> dict:
        if self.trajectory is None:
            return {"cancelRequested": False}
        return {"cancelRequested": self.trajectory.cancel()}

    async def _move_ik(self, params: dict) -> dict:
        pose = self._pose_params(params)
        success, solution = await asyncio.to_thread(self.driver.move_to_pose_ik, *pose)
        return {"success": bool(success), "jointSolution": list(solution)}

    async def _move_trajectory(self, params: dict) -> dict:
        pose = self._pose_params(params)
        duration = float(params.get("duration", 2.0))
        success = await asyncio.to_thread(self.driver.move_to_pose_traj, *pose, duration)
        return {
            "success": bool(success),
            "duration": max(duration, float(self.driver.last_motion_duration)),
        }

    @staticmethod
    def _pose_params(params: dict) -> tuple[float, float, float, float, float, float]:
        names = ("x", "y", "z", "roll", "pitch", "yaw")
        return tuple(float(params.get(name, 0.0)) for name in names)

    async def _set_gripper(self, params: dict) -> dict:
        if "widthM" in params:
            target = gripper_width_to_motor(float(params["widthM"]))
        else:
            target = float(params["positionRad"])
        wait = bool(params.get("wait", False))
        if wait:
            reached, position = await asyncio.to_thread(
                self.driver.set_gripper_position, target, float(params.get("timeout", 3.0))
            )
            return {
                "reached": bool(reached),
                "positionRad": float(position),
                "widthM": gripper_motor_to_width(position),
            }
        await asyncio.to_thread(self.driver.set_gripper_target, target)
        return {"accepted": True, "positionRad": target, "widthM": gripper_motor_to_width(target)}

    async def _open_gripper(self, _params: dict) -> dict:
        return await self._set_gripper({"positionRad": self.driver.gripper_open_position})

    async def _close_gripper(self, _params: dict) -> dict:
        return await self._set_gripper({"positionRad": self.driver.gripper_close_position})

    async def _release_gripper(self, _params: dict) -> dict:
        await asyncio.to_thread(self.driver.release_gripper_for_manual)
        return {"message": "gripper released for manual movement"}

    async def _hold_gripper(self, _params: dict) -> dict:
        await asyncio.to_thread(self.driver.hold_gripper_current)
        return {"message": "gripper holding current position"}

    async def _assist_gripper(self, _params: dict) -> dict:
        await asyncio.to_thread(self.driver.start_gripper_assist)
        return {"message": "gripper low-resistance assist active"}

    def _gripper_status(self, _params: dict) -> dict:
        return {
            "assistActive": bool(self.driver.gripper_assist_active()),
            "manualFree": bool(self.driver.gripper_manual_free()),
        }

    async def _start_gravity(self, _params: dict) -> dict:
        already_active = self.driver.gravity_compensation_active()
        await asyncio.to_thread(self.driver.start_gravity_compensation)
        target = self.driver.gravity_compensation_target()
        return {
            "active": True,
            "alreadyActive": bool(already_active),
            "target": None if target is None else np.asarray(target, dtype=float).tolist(),
        }

    async def _stop_gravity(self, _params: dict) -> dict:
        await asyncio.to_thread(self.driver.stop_gravity_compensation)
        return {"active": False}

    def _gravity_status(self, _params: dict) -> dict:
        target = self.driver.gravity_compensation_target()
        return {
            "active": bool(self.driver.gravity_compensation_active()),
            "target": None if target is None else np.asarray(target, dtype=float).tolist(),
            "fault": str(self.driver.gravity_compensation_fault()),
        }
