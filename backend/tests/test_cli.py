from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from rebotd.cli import build_parser  # noqa: E402


class CliTests(unittest.TestCase):
    def test_serve_starts_detached_by_default(self) -> None:
        args = build_parser().parse_args(["serve"])

        self.assertEqual(args.driver, "disconnected")

    def test_fake_driver_remains_available_for_local_testing(self) -> None:
        args = build_parser().parse_args(["serve", "--driver", "fake"])

        self.assertEqual(args.driver, "fake")


if __name__ == "__main__":
    unittest.main()
