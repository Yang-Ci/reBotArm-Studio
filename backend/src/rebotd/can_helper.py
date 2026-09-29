from __future__ import annotations

import argparse
import sys

from .can_discovery import configure_socketcan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rebotd-can-helper")
    parser.add_argument("channel")
    parser.add_argument("bitrate", type=int)
    args = parser.parse_args(argv)
    try:
        configure_socketcan(
            args.channel,
            bitrate=args.bitrate,
            privilege_helper="",
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
