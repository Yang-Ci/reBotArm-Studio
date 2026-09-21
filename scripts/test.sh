#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${REPO_DIR}/backend/.venv/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "缺少 backend/.venv，请先运行 ./scripts/bootstrap.sh" >&2
  exit 1
fi

env -u PYTHONPATH -u AMENT_PREFIX_PATH -u COLCON_PREFIX_PATH \
  -u ROS_DISTRO -u ROS_VERSION PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  "${PYTHON}" -m pytest "${REPO_DIR}/backend/tests" -q

cd "${REPO_DIR}/frontend/web-mujoco"
npm run smoke
npm run test:explode
npm run build
