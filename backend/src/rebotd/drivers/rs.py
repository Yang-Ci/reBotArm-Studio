from __future__ import annotations

from rebotd.core.hardware_manager import HardwareManager


def create_rs_driver(*, channel: str = "can0", hardware_config: str | None = None) -> HardwareManager:
    """Create the validated B601-RS controller without importing ROS."""
    return HardwareManager(
        hardware_config=hardware_config,
        model="rs",
        channel=channel,
    )
