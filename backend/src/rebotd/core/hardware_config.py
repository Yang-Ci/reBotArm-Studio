from __future__ import annotations

import copy
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


def repository_root() -> Path:
    """Locate source or bundled resources without ament or ROS."""
    configured = os.environ.get("REBOTARM_STUDIO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "backend" / "vendor" / "reBotArm_control_py").is_dir():
            return parent
    raise FileNotFoundError(
        "cannot locate reBotArm Studio resources; set REBOTARM_STUDIO_ROOT"
    )


def ensure_rebot_sdk_in_syspath() -> Path:
    root = repository_root() / "backend" / "vendor" / "reBotArm_control_py"
    if not (root / "reBotArm_control_py").is_dir():
        raise FileNotFoundError(f"vendored reBotArm_control_py is missing at {root}")
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def default_hardware_config_path() -> Path:
    return repository_root() / "backend" / "config" / "rebotarm_hardware.yaml"


def resolve_hardware_config(
    hardware_config: str | None,
    model: str,
    channel: str,
) -> tuple[Path, dict[str, Any]]:
    sdk_root = ensure_rebot_sdk_in_syspath()
    model_name, data = _load_hardware_config(
        sdk_root, hardware_config, model, channel
    )
    path = _write_resolved_hardware_config(model_name, data)
    _sync_sdk_robot_model_config(data)
    return path, copy.deepcopy(data)


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = copy.deepcopy(base)
        for key, value in override.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(override)


def _load_hardware_config(
    sdk_root: Path,
    hardware_config: str | None,
    model: str,
    channel: str,
) -> tuple[str, dict[str, Any]]:
    config_path = (
        Path(hardware_config).expanduser()
        if hardware_config
        else default_hardware_config_path()
    )
    if not config_path.exists():
        raise FileNotFoundError(f"hardware config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as stream:
        app_config = yaml.safe_load(stream) or {}

    model_name = (model or app_config.get("default_model") or "rs").strip().lower()
    models = app_config.get("models", {})
    if model_name not in models:
        choices = ", ".join(sorted(models))
        raise ValueError(f"unknown hardware model {model_name!r}; choices: {choices}")
    model_config = models[model_name] or {}
    sdk_config = model_config.get("sdk_config")
    if not sdk_config:
        raise ValueError(f"models.{model_name}.sdk_config is required")

    sdk_config_path = Path(str(sdk_config)).expanduser()
    if not sdk_config_path.is_absolute():
        sdk_config_path = sdk_root / "config" / sdk_config_path
    if not sdk_config_path.exists():
        raise FileNotFoundError(f"SDK hardware config not found: {sdk_config_path}")
    with sdk_config_path.open("r", encoding="utf-8") as stream:
        merged = yaml.safe_load(stream) or {}

    merged = _deep_merge(merged, model_config.get("overrides", {}) or {})
    urdf_value = str(merged.get("urdf_path", "")).strip()
    urdf_path = Path(urdf_value).expanduser()
    if urdf_value and not urdf_path.is_absolute():
        app_resource = repository_root() / urdf_path
        if app_resource.exists():
            merged["urdf_path"] = str(app_resource.resolve())
    if channel:
        merged["channel"] = channel
    _add_runtime_config(merged)
    return model_name, merged


def _add_runtime_config(data: dict[str, Any]) -> None:
    arm_joints = _arm_joint_names(data)
    size = len(arm_joints)
    gravity = data.get("gravity_compensation", {}) or {}
    control = data.get("control", {}) or {}
    assist_config = data.get("gripper_assist", {}) or {}
    data["_runtime"] = {
        "control": {
            "arm_control_mode": _arm_control_mode(data),
            "mit_kp": _control_gain(data, arm_joints, control, "mit_kp", "kp"),
            "mit_kd": _control_gain(data, arm_joints, control, "mit_kd", "kd"),
            "stream_acceleration_limit": _positive_scalar(
                control.get("stream_acceleration_limit", 4.0),
                "control.stream_acceleration_limit",
            ),
            "stream_jerk_limit": _positive_scalar(
                control.get("stream_jerk_limit", 30.0),
                "control.stream_jerk_limit",
            ),
            "stream_natural_frequency": _positive_scalar(
                control.get("stream_natural_frequency", 8.0),
                "control.stream_natural_frequency",
            ),
        },
        "gravity_compensation": {
            "kp": _gravity_gain(data, arm_joints, gravity, "kp"),
            "kd": _gravity_gain(data, arm_joints, gravity, "kd"),
            "transition_duration": _positive_scalar(
                gravity.get("transition_duration", 0.5),
                "gravity_compensation.transition_duration",
            ),
            "joint_direction": _runtime_vector(
                gravity.get("joint_direction", 1.0), size,
                "gravity_compensation.joint_direction",
            ),
            "tau_scale": _runtime_vector(
                gravity.get("tau_scale", 1.0), size,
                "gravity_compensation.tau_scale",
            ),
            "torque_limit": _nonnegative_vector(
                gravity.get("torque_limit", 0.0), size,
                "gravity_compensation.torque_limit",
            ),
        },
        "gripper_assist": {
            "torque": _nonnegative_scalar(
                assist_config.get("torque", 0.04), "gripper_assist.torque"
            ),
            "kd": _nonnegative_scalar(
                assist_config.get("kd", 0.001), "gripper_assist.kd"
            ),
            "velocity_threshold": _positive_scalar(
                assist_config.get("velocity_threshold", 0.02),
                "gripper_assist.velocity_threshold",
            ),
            "velocity_full": _positive_scalar(
                assist_config.get("velocity_full", 0.22),
                "gripper_assist.velocity_full",
            ),
            "speed_limit": _positive_scalar(
                assist_config.get("speed_limit", 0.8),
                "gripper_assist.speed_limit",
            ),
            "breakaway_fraction": _unit_scalar(
                assist_config.get("breakaway_fraction", 0.30),
                "gripper_assist.breakaway_fraction",
            ),
        },
    }
    directions = data["_runtime"]["gravity_compensation"]["joint_direction"]
    if any(value not in (-1.0, 1.0) for value in directions):
        raise ValueError("gravity_compensation.joint_direction values must be +1 or -1")
    assist = data["_runtime"]["gripper_assist"]
    if assist["velocity_full"] <= assist["velocity_threshold"]:
        raise ValueError("gripper_assist.velocity_full must exceed velocity_threshold")
    if assist["speed_limit"] <= assist["velocity_full"]:
        raise ValueError("gripper_assist.speed_limit must exceed velocity_full")


def _finite_scalar(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _positive_scalar(value: Any, label: str) -> float:
    result = _finite_scalar(value, label)
    if result <= 0.0:
        raise ValueError(f"{label} must be positive")
    return result


def _nonnegative_scalar(value: Any, label: str) -> float:
    result = _finite_scalar(value, label)
    if result < 0.0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _unit_scalar(value: Any, label: str) -> float:
    result = _nonnegative_scalar(value, label)
    if result > 1.0:
        raise ValueError(f"{label} must be between 0 and 1")
    return result


def _arm_control_mode(data: dict[str, Any]) -> str:
    mode = str(
        (data.get("control", {}) or {}).get("arm_control_mode", "posvel")
    ).strip().lower()
    if mode == "pos_vel":
        mode = "posvel"
    if mode not in ("posvel", "mit"):
        raise ValueError("control.arm_control_mode must be 'posvel' or 'mit'")
    return mode


def _arm_joint_names(data: dict[str, Any]) -> list[str]:
    joints = data.get("groups", {}).get("arm", {}).get("joints", [])
    if not joints:
        raise ValueError("hardware config must define groups.arm.joints")
    return [str(name) for name in joints]


def _gravity_gain(
    data: dict[str, Any], joints: list[str], config: dict[str, Any], key: str
) -> list[float]:
    if key in config:
        return _runtime_vector(config[key], len(joints), f"gravity_compensation.{key}")
    joint_map = {str(item.get("name")): item for item in data.get("joints", [])}
    return [float((joint_map[name].get("MIT", {}) or {}).get(key, 0.0)) for name in joints]


def _control_gain(
    data: dict[str, Any],
    joints: list[str],
    config: dict[str, Any],
    config_key: str,
    mit_key: str,
) -> list[float]:
    if config_key in config:
        return _runtime_vector(config[config_key], len(joints), f"control.{config_key}")
    joint_map = {str(item.get("name")): item for item in data.get("joints", [])}
    return [float((joint_map[name].get("MIT", {}) or {}).get(mit_key, 0.0)) for name in joints]


def _runtime_vector(value: Any, size: int, label: str) -> list[float]:
    if isinstance(value, (int, float)):
        return [float(value)] * size
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a scalar or {size} values")
    values = [float(item) for item in value]
    if len(values) == 1:
        return values * size
    if len(values) != size:
        raise ValueError(f"{label} must be a scalar or {size} values")
    return values


def _nonnegative_vector(value: Any, size: int, label: str) -> list[float]:
    values = _runtime_vector(value, size, label)
    if any(not math.isfinite(item) or item < 0.0 for item in values):
        raise ValueError(f"{label} values must be non-negative and finite")
    return values


_resolved_config_dir: Path | None = None


def _write_resolved_hardware_config(model: str, data: dict[str, Any]) -> Path:
    global _resolved_config_dir
    if _resolved_config_dir is None:
        _resolved_config_dir = Path(tempfile.mkdtemp(prefix="rebotarm_studio_"))
    path = _resolved_config_dir / f"{model}_hardware.yaml"
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(data, stream, sort_keys=False)
    return path


def _sync_sdk_robot_model_config(data: dict[str, Any]) -> None:
    import reBotArm_control_py.dynamics.robot_model as dynamics_model
    import reBotArm_control_py.kinematics.robot_model as robot_model

    robot_model._hw_cfg_cache = copy.deepcopy(data)
    dynamics_model._CACHED_MODEL = None
