#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REBOTD="${REPO_DIR}/backend/.venv/bin/rebotd"

if [[ ! -x "${REBOTD}" ]]; then
  echo "缺少本地环境，请先运行 ./scripts/bootstrap.sh" >&2
  exit 1
fi

env -u PYTHONPATH -u AMENT_PREFIX_PATH -u COLCON_PREFIX_PATH \
  -u ROS_DISTRO -u ROS_VERSION \
  "${REBOTD}" doctor --channel "${1:-can0}"
