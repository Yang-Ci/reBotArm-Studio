from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


CAN_CHANNEL_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
PERMISSION_ERRORS = ("operation not permitted", "permission denied", "not permitted")


def scan_socketcan(
    *,
    sys_class_net: Path = Path("/sys/class/net"),
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    """Return CAN interfaces without opening the bus or transmitting frames."""
    devices: list[dict[str, Any]] = []
    if not sys_class_net.is_dir():
        return devices

    for interface in sorted(sys_class_net.iterdir(), key=lambda item: item.name):
        if _read_text(interface / "type") != "280":
            continue
        details = _ip_details(interface.name, run)
        info = ((details.get("linkinfo") or {}).get("info_data") or {})
        timing = info.get("bittiming") or {}
        errors = info.get("berr_counter") or {}
        driver = _device_driver(interface)
        devices.append({
            "channel": interface.name,
            "driver": driver,
            "adapter": _adapter_label(driver),
            "isUp": (
                "UP" in (details.get("flags") or [])
                and _read_text(interface / "operstate") == "up"
            ),
            "carrier": _read_text(interface / "carrier") == "1",
            "state": str(info.get("state") or "UNKNOWN"),
            "bitrate": int(timing.get("bitrate") or 0),
            "txErrors": int(errors.get("tx") or 0),
            "rxErrors": int(errors.get("rx") or 0),
            "ready": (
                "UP" in (details.get("flags") or [])
                and str(info.get("state") or "").upper() != "BUS-OFF"
                and int(timing.get("bitrate") or 0) == 1_000_000
            ),
        })
    return devices


def configure_socketcan(
    channel: str,
    *,
    bitrate: int = 1_000_000,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ip_command: str | None = None,
    privilege_helper: str | None = None,
) -> None:
    """Configure SocketCAN, using graphical Polkit authorization if required."""
    if not CAN_CHANNEL_PATTERN.fullmatch(channel):
        raise ValueError(f"invalid CAN interface name: {channel!r}")
    if bitrate <= 0:
        raise ValueError("CAN bitrate must be positive")

    ip_path = ip_command or shutil.which("ip") or "ip"
    pkexec_path = (
        privilege_helper
        if privilege_helper is not None
        else shutil.which("pkexec")
    )
    commands = (
        [ip_path, "link", "set", "dev", channel, "down"],
        [
            ip_path,
            "link",
            "set",
            "dev",
            channel,
            "type",
            "can",
            "bitrate",
            str(bitrate),
            "restart-ms",
            "100",
        ],
        [ip_path, "link", "set", "dev", channel, "up"],
    )
    for command in commands:
        result = _run_command(run, command, timeout=3.0)
        if result.returncode == 0:
            continue

        detail = (result.stderr or result.stdout or "ip command failed").strip()
        permission_denied = any(marker in detail.lower() for marker in PERMISSION_ERRORS)
        if permission_denied and pkexec_path:
            elevated = [
                pkexec_path,
                sys.executable,
                "-m",
                "rebotd.can_helper",
                channel,
                str(bitrate),
            ]
            result = _run_command(run, elevated, timeout=90.0)
            if result.returncode == 0:
                return
            detail = (
                result.stderr
                or result.stdout
                or "system authorization was cancelled or denied"
            ).strip()
        elif permission_denied:
            detail = "graphical system authorization is unavailable (pkexec not found)"
        raise RuntimeError(f"failed to configure {channel}: {detail}")


def _run_command(
    run: Callable[..., subprocess.CompletedProcess[str]],
    command: list[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "system authorization timed out; approve the App permission dialog and retry"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"could not execute {' '.join(command)}: {exc}") from exc


def _ip_details(
    channel: str,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    try:
        result = run(
            ["ip", "-details", "-json", "link", "show", channel],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        payload = json.loads(result.stdout or "[]")
        return payload[0] if result.returncode == 0 and payload else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return {}


def _device_driver(interface: Path) -> str:
    try:
        return (interface / "device" / "driver").resolve(strict=True).name
    except OSError:
        uevent = _read_text(interface / "device" / "uevent")
        for line in uevent.splitlines():
            if line.startswith("DRIVER="):
                return line.partition("=")[2]
    return "unknown"


def _adapter_label(driver: str) -> str:
    labels = {
        "peak_usb": "PEAK-System PCAN-USB",
        "pcan": "PEAK-System PCAN",
        "gs_usb": "USB-CAN (gs_usb)",
        "slcan": "Serial CAN (slcan)",
    }
    return labels.get(driver, driver if driver != "unknown" else "SocketCAN")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
