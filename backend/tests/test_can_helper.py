from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from rebotd.can_helper import main  # noqa: E402


class CanHelperTests(unittest.TestCase):
    def test_forwards_validated_channel_and_bitrate(self) -> None:
        with patch("rebotd.can_helper.configure_socketcan") as configure:
            result = main(["can0", "1000000"])

        self.assertEqual(result, 0)
        configure.assert_called_once_with(
            "can0",
            bitrate=1_000_000,
            privilege_helper="",
        )

    def test_reports_configuration_failure(self) -> None:
        with patch(
            "rebotd.can_helper.configure_socketcan",
            side_effect=RuntimeError("permission denied"),
        ):
            result = main(["can0", "1000000"])

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
