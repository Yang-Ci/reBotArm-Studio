from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

from .core.trajectory_profiles import retime_cubic_hermite, sample_cubic_hermite

MAX_ACTION_SPEED_RAD_S = 0.60
MAX_TEACHING_SPEED_RAD_S = 1.20


class TrajectoryCanceled(RuntimeError):
    pass


class TrajectoryExecutor:
    def __init__(self, driver) -> None:
        self.driver = driver
        self._cancel = threading.Event()
        self._active_lock = threading.Lock()

    def cancel(self) -> bool:
        self._cancel.set()
        return self.driver.state_machine == "TRAJ_RUNNING"

    def execute(
        self,
        points: list[dict],
        *,
        teaching: bool = False,
        on_progress: Callable[[dict], None] | None = None,
    ) -> dict:
        if not points:
            raise ValueError("trajectory must contain at least one point")
        if not self._active_lock.acquire(blocking=False):
            raise RuntimeError("a trajectory is already running")
        self._cancel.clear()
        try:
            targets = [np.asarray(point["positions"], dtype=np.float64) for point in points]
            if any(target.shape != (len(self.driver.joint_names),) for target in targets):
                raise ValueError(f"every point must contain {len(self.driver.joint_names)} positions")
            point_times = [float(point["time"]) for point in points]
            if any(not np.isfinite(value) or value < 0.0 for value in point_times):
                raise ValueError("trajectory times must be finite and non-negative")
            if any(right < left for left, right in zip(point_times, point_times[1:])):
                raise ValueError("trajectory times must be monotonic")

            self.driver.begin_trajectory_stream()
            current = self.driver.get_joint_positions().copy()
            if point_times[0] > 0.0 or np.max(np.abs(targets[0] - current)) > 1e-6:
                targets.insert(0, current)
                point_times.insert(0, 0.0)
            point_times, velocities = retime_cubic_hermite(
                targets,
                point_times,
                velocity_limit=(MAX_TEACHING_SPEED_RAD_S if teaching else MAX_ACTION_SPEED_RAD_S),
            )
            start = time.monotonic()
            for index in range(1, len(targets)):
                q0, q1 = targets[index - 1], targets[index]
                v0, v1 = velocities[index - 1], velocities[index]
                t0, t1 = point_times[index - 1], max(point_times[index], point_times[index - 1])
                while True:
                    self._check_canceled()
                    if self.driver.state_machine == "SAFE_HOMING":
                        raise TrajectoryCanceled("trajectory preempted by safe_home")
                    elapsed = time.monotonic() - start
                    ratio = 1.0 if t1 <= t0 else max(0.0, min(1.0, (elapsed - t0) / (t1 - t0)))
                    target, desired_velocity = sample_cubic_hermite(q0, q1, v0, v1, t1 - t0, ratio)
                    self.driver.update_trajectory_reference(target, desired_velocity)
                    if on_progress:
                        actual = self.driver.get_joint_positions()
                        on_progress({
                            "progress": 1.0 if point_times[-1] <= 0.0 else min(elapsed / point_times[-1], 1.0),
                            "desired": target.tolist(),
                            "actual": actual.tolist(),
                        })
                    if elapsed >= t1:
                        break
                    time.sleep(0.01)

            final = targets[-1]
            self.driver.update_trajectory_reference(final, np.zeros_like(final))
            settle_deadline = time.monotonic() + 2.0
            while time.monotonic() < settle_deadline:
                self._check_canceled()
                position = self.driver.get_joint_positions()
                velocity = self.driver.get_joint_velocities()
                if np.max(np.abs(final - position)) <= 0.025 and np.max(np.abs(velocity)) <= 0.15:
                    break
                time.sleep(0.02)
            return {
                "positions": self.driver.get_joint_positions().tolist(),
                "velocities": self.driver.get_joint_velocities().tolist(),
                "duration": point_times[-1],
            }
        except TrajectoryCanceled:
            self.driver.hold_current_position()
            raise
        except Exception:
            self.driver.hold_current_position()
            raise
        finally:
            if self.driver.state_machine != "SAFE_HOMING":
                self.driver.set_state_machine("IDLE")
            self._active_lock.release()

    def _check_canceled(self) -> None:
        if self._cancel.is_set():
            raise TrajectoryCanceled("trajectory canceled")
