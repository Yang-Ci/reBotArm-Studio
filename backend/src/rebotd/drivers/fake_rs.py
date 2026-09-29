from __future__ import annotations

import threading
import time

import numpy as np


class FakeRSDriver:
    """In-process B601-RS stand-in used by protocol and UI tests.

    It intentionally mirrors the public surface of ``HardwareManager`` while
    never importing MotorBridge or opening a CAN device.
    """

    joint_names = [f"joint{index}" for index in range(1, 7)]
    gripper_open_position = 5.0
    gripper_close_position = 0.0

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._connected = False
        self._enabled = False
        self._state = "IDLE"
        self._position = np.zeros(6, dtype=np.float64)
        self._velocity = np.zeros(6, dtype=np.float64)
        self._torque = np.zeros(6, dtype=np.float64)
        self._target = self._position.copy()
        self._reference = self._position.copy()
        self._reference_velocity = np.zeros(6, dtype=np.float64)
        self._reference_acceleration = np.zeros(6, dtype=np.float64)
        self._gripper_position = 0.0
        self._gripper_target = 0.0
        self._gravity = False
        self._gravity_fault = ""
        self._gripper_free = False
        self._gripper_assist = False
        self._last_update = time.monotonic()
        self._last_motion_duration = 0.0

    @property
    def mode(self) -> str:
        return "mit"

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def control_loop_active(self) -> bool:
        return self._connected and self._enabled

    @property
    def has_gripper(self) -> bool:
        return True

    @property
    def last_motion_duration(self) -> float:
        return self._last_motion_duration

    @property
    def state_machine(self) -> str:
        return self._state

    @property
    def error_codes(self) -> list[str]:
        return []

    def connect(self) -> None:
        self._connected = True
        self._enabled = True

    def shutdown(self, disable_after_safe_home: bool = True) -> None:
        if disable_after_safe_home and self._enabled:
            self.safe_home()
            self.disable()
        self._connected = False

    def enable(self) -> None:
        if not self._connected:
            raise RuntimeError("driver is not connected")
        self._enabled = True
        self._state = "IDLE"

    def disable(self) -> None:
        self._enabled = False
        self._state = "IDLE"
        self._velocity.fill(0.0)

    def set_state_machine(self, state: str) -> None:
        if state not in {"IDLE", "TRAJ_RUNNING", "LOWLEVEL_STREAMING", "GRAVITY_COMP", "SAFE_HOMING"}:
            raise ValueError(f"unsupported state machine value: {state}")
        self._state = state

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise RuntimeError("rejecting command while arm is disabled")

    def _advance(self) -> None:
        now = time.monotonic()
        elapsed = max(0.0, min(now - self._last_update, 0.1))
        self._last_update = now
        if elapsed <= 0.0:
            return
        delta = self._reference - self._position
        velocity = np.clip(delta / elapsed, -1.2, 1.2)
        step = np.clip(delta, -1.2 * elapsed, 1.2 * elapsed)
        self._position += step
        self._velocity = np.where(np.abs(delta) > 1e-8, velocity, 0.0)
        if np.max(np.abs(self._reference - self._position)) < 1e-6:
            self._position[:] = self._reference
            self._velocity.fill(0.0)
        gripper_delta = self._gripper_target - self._gripper_position
        gripper_step = float(np.clip(gripper_delta, -5.0 * elapsed, 5.0 * elapsed))
        self._gripper_position += gripper_step

    def get_joint_state(self, request_feedback: bool = True):
        del request_feedback
        with self._lock:
            self._advance()
            return self._position.copy(), self._velocity.copy(), self._torque.copy()

    def get_joint_positions(self, request: bool = False) -> np.ndarray:
        return self.get_joint_state(request)[0]

    def get_joint_velocities(self, request: bool = False) -> np.ndarray:
        return self.get_joint_state(request)[1]

    def is_near_safe_home(self, tolerance_rad=np.deg2rad(2.0), velocity_tolerance_rad_s=0.15) -> bool:
        position, velocity, _ = self.get_joint_state()
        return bool(np.all(np.abs(position) <= tolerance_rad) and np.all(np.abs(velocity) <= velocity_tolerance_rad_s))

    def wait_until_near_safe_home(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_near_safe_home():
                return True
            time.sleep(0.01)
        return self.is_near_safe_home()

    def safe_home(self) -> None:
        self._require_enabled()
        self._state = "SAFE_HOMING"
        self._target.fill(0.0)
        self._reference.fill(0.0)
        self._position.fill(0.0)
        self._velocity.fill(0.0)
        self._state = "IDLE"

    def hold_current_position(self) -> np.ndarray:
        position = self.get_joint_positions().copy()
        self._target[:] = position
        self._reference[:] = position
        self._reference_velocity.fill(0.0)
        return position

    def set_zero(self, joint_name: str = "") -> bool:
        if joint_name:
            index = self.joint_names.index(joint_name)
            self._position[index] = 0.0
            self._target[index] = 0.0
            self._reference[index] = 0.0
        else:
            self._position.fill(0.0)
            self._target.fill(0.0)
            self._reference.fill(0.0)
        self._enabled = False
        return True

    def send_joint_mit_cmd(self, joint_name, pos, vel, kp, kd, tau) -> None:
        del kp, kd, tau
        self._require_enabled()
        if self._gravity:
            raise RuntimeError("rejecting joint target during gravity compensation")
        index = self.joint_names.index(joint_name)
        self._target[index] = float(pos)
        self._reference[index] = float(pos)
        self._reference_velocity[index] = float(vel)
        self._state = "LOWLEVEL_STREAMING"

    def send_joint_pos_vel_cmd(self, joint_name, pos, vlim) -> None:
        self.send_joint_mit_cmd(joint_name, pos, vlim, 0.0, 0.0, 0.0)

    def set_joint_position_target(self, positions, velocities=None) -> None:
        self._require_enabled()
        target = np.asarray(positions, dtype=np.float64)
        if target.shape != (6,):
            raise ValueError("expected 6 joint targets")
        self._target[:] = target
        self._reference[:] = target
        self._reference_velocity[:] = 0.0 if velocities is None else velocities

    def begin_trajectory_stream(self) -> None:
        self._require_enabled()
        if self._gravity:
            raise RuntimeError("stop gravity compensation before trajectory")
        if self._state in {"SAFE_HOMING", "TRAJ_RUNNING"}:
            raise RuntimeError(f"rejecting trajectory stream in state {self._state}")
        self._state = "TRAJ_RUNNING"

    def update_trajectory_reference(self, positions, velocities) -> None:
        if self._state != "TRAJ_RUNNING":
            raise RuntimeError("trajectory is not running")
        self._target[:] = np.asarray(positions, dtype=np.float64)
        self._reference[:] = self._target
        self._reference_velocity[:] = np.asarray(velocities, dtype=np.float64)
        self._position[:] = self._reference
        self._velocity[:] = self._reference_velocity

    def get_control_reference(self):
        return (
            self._target.copy(),
            self._reference.copy(),
            self._reference_velocity.copy(),
            self._reference_acceleration.copy(),
        )

    def stop_motion(self) -> None:
        self.hold_current_position()
        if self._state != "SAFE_HOMING":
            self._state = "IDLE"

    def motion_active(self) -> bool:
        return False

    def move_to_pose_ik(self, x, y, z, roll, pitch, yaw):
        del x, y, z, roll, pitch, yaw
        return True, self._target.tolist()

    def move_to_pose_traj(self, x, y, z, roll, pitch, yaw, duration):
        del x, y, z, roll, pitch, yaw
        self._last_motion_duration = max(float(duration), 0.0)
        return True

    def current_pose(self):
        return {
            "position": {"x": 0.30, "y": 0.0, "z": 0.30},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        }

    def get_joint_status_codes(self) -> list[int]:
        return [0] * 6

    def start_gravity_compensation(self) -> None:
        self._require_enabled()
        if self._gravity:
            return
        self.hold_current_position()
        self._gravity = True
        self._state = "GRAVITY_COMP"

    def stop_gravity_compensation(self) -> None:
        self._gravity = False
        if self._state == "GRAVITY_COMP":
            self._state = "IDLE"

    def gravity_compensation_active(self) -> bool:
        return self._gravity

    def gravity_compensation_target(self):
        return self._reference.copy() if self._gravity else None

    def gravity_compensation_fault(self) -> str:
        return self._gravity_fault

    def set_gripper_target(self, position: float) -> None:
        self._require_enabled()
        self._gripper_free = False
        self._gripper_assist = False
        self._gripper_target = float(np.clip(position, 0.0, 5.0))

    def set_gripper_position(self, position: float, timeout: float = 3.0):
        del timeout
        self.set_gripper_target(position)
        self._gripper_position = self._gripper_target
        return True, self._gripper_position

    def get_gripper_state(self, request_feedback: bool = True):
        del request_feedback
        self._advance()
        velocity = 0.0 if self._gripper_position == self._gripper_target else 1.0
        return self._gripper_position, velocity, 0.0, 0

    def gripper_reached_target(self) -> bool:
        return abs(self._gripper_position - self._gripper_target) < 0.12

    def send_gripper_mit_cmd(self, pos, vel, kp, kd, tau) -> None:
        del vel, kp, kd, tau
        self.set_gripper_target(pos)

    def send_gripper_pos_vel_cmd(self, pos, vlim) -> None:
        del vlim
        self.set_gripper_target(pos)

    def release_gripper_for_manual(self) -> None:
        self._require_enabled()
        self._gripper_free = True
        self._gripper_assist = False

    def hold_gripper_current(self) -> None:
        self._require_enabled()
        self._gripper_target = self._gripper_position
        self._gripper_free = False
        self._gripper_assist = False

    def start_gripper_assist(self) -> None:
        self._require_enabled()
        self._gripper_free = False
        self._gripper_assist = True

    def gripper_assist_active(self) -> bool:
        return self._gripper_assist

    def gripper_manual_free(self) -> bool:
        return self._gripper_free
