#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -x "${REPO_DIR}/backend/.venv/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${REPO_DIR}/backend/.venv"
fi

env -u PYTHONPATH -u AMENT_PREFIX_PATH -u COLCON_PREFIX_PATH \
  -u ROS_DISTRO -u ROS_VERSION \
  "${REPO_DIR}/backend/.venv/bin/python" -m pip install -e "${REPO_DIR}/backend" pytest

cd "${REPO_DIR}"
npm install

echo "reBotArm Studio 本地依赖已就绪。"
