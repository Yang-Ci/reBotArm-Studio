from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable


CAN_CHANNEL_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


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
) -> None:
    """Configure one pre-existing SocketCAN interface after user confirmation."""
    if not CAN_CHANNEL_PATTERN.fullmatch(channel):
        raise ValueError(f"invalid CAN interface name: {channel!r}")
    if bitrate <= 0:
        raise ValueError("CAN bitrate must be positive")

    commands = (
        ["ip", "link", "set", "dev", channel, "down"],
        [
            "ip",
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
        ["ip", "link", "set", "dev", channel, "up"],
    )
    for command in commands:
        try:
            result = run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=3.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"failed to configure {channel}: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "ip command failed").strip()
            if "not permitted" in detail.lower() or "permission denied" in detail.lower():
                detail = "the installed rebotd service lacks CAN network permission"
            raise RuntimeError(f"failed to configure {channel}: {detail}")


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
