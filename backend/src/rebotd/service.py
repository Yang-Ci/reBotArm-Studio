from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np

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

    def __init__(self, driver, *, product_id: str, driver_name: str) -> None:
        self.driver = driver
        self.product_id = product_id
        self.driver_name = driver_name
        self.trajectory = TrajectoryExecutor(driver)
        self.started_at = time.time()

    async def dispatch(self, method: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        handlers = {
            "system.hello": self._hello,
            "system.ping": self._ping,
            "system.status": self.snapshot,
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
            "jointNames": list(self.driver.joint_names),
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
        return await asyncio.to_thread(self._snapshot_sync, request_feedback)

    def _snapshot_sync(self, request_feedback: bool) -> dict:
        position, velocity, torque = self.driver.get_joint_state(
            request_feedback=request_feedback
        )
        target, reference, reference_velocity, reference_acceleration = (
            self.driver.get_control_reference()
        )
        gripper_position, gripper_velocity, gripper_torque, gripper_status = (
            self.driver.get_gripper_state(request_feedback=False)
        )
        return {
            "timestamp": time.time(),
            "productId": self.product_id,
            "driver": self.driver_name,
            "enabled": bool(self.driver.enabled),
            "mode": str(self.driver.mode),
            "stateMachine": str(self.driver.state_machine),
            "controlLoopActive": bool(self.driver.control_loop_active),
            "jointNames": list(self.driver.joint_names),
            "position": np.asarray(position, dtype=float).tolist(),
            "velocity": np.asarray(velocity, dtype=float).tolist(),
            "torque": np.asarray(torque, dtype=float).tolist(),
            "statusCodes": [int(value) for value in self.driver.get_joint_status_codes()],
            "errors": list(self.driver.error_codes),
            "controlTarget": np.asarray(target, dtype=float).tolist(),
            "controlReference": np.asarray(reference, dtype=float).tolist(),
            "referenceVelocity": np.asarray(reference_velocity, dtype=float).tolist(),
            "referenceAcceleration": np.asarray(reference_acceleration, dtype=float).tolist(),
            "gravity": {
                "active": bool(self.driver.gravity_compensation_active()),
                "fault": str(self.driver.gravity_compensation_fault()),
            },
            "gripper": {
                "positionRad": float(gripper_position),
                "widthM": gripper_motor_to_width(gripper_position),
                "velocity": float(gripper_velocity),
                "torque": float(gripper_torque),
                "statusCode": int(gripper_status),
                "manualFree": bool(self.driver.gripper_manual_free()),
                "assistActive": bool(self.driver.gripper_assist_active()),
            },
        }

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
        points = list(params.get("points") or [])
        teaching = bool(params.get("teaching", False))
        return await asyncio.to_thread(
            self.trajectory.execute, points, teaching=teaching
        )

    def _cancel_trajectory(self, _params: dict) -> dict:
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
        return tuple(float(params.get(name, 0.0)) for name in ("x", "y", "z", "roll", "pitch", "yaw"))

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
            return {"reached": bool(reached), "positionRad": float(position), "widthM": gripper_motor_to_width(position)}
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
