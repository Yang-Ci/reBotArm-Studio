#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REBOTD="${REPO_DIR}/backend/.venv/bin/rebotd"
DRIVER="fake"

if [[ "${1:-}" == "--hardware" ]]; then
  DRIVER="rs"
  if [[ "${REBOTARM_HARDWARE_CONFIRM:-}" != "I_UNDERSTAND_REBOTARM_WILL_MOVE" ]]; then
    echo "真机模式会驱动机械臂。确认安全后设置：" >&2
    echo "  export REBOTARM_HARDWARE_CONFIRM=I_UNDERSTAND_REBOTARM_WILL_MOVE" >&2
    exit 2
  fi
elif [[ -n "${1:-}" ]]; then
  echo "用法: ./scripts/dev.sh [--hardware]" >&2
  exit 2
fi

if [[ ! -x "${REBOTD}" ]]; then
  echo "缺少本地环境，请先运行 ./scripts/bootstrap.sh" >&2
  exit 1
fi

cleanup() {
  if [[ -n "${REBOTD_PID:-}" ]]; then
    kill "${REBOTD_PID}" 2>/dev/null || true
    wait "${REBOTD_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

env -u PYTHONPATH -u AMENT_PREFIX_PATH -u COLCON_PREFIX_PATH \
  -u ROS_DISTRO -u ROS_VERSION \
  "${REBOTD}" serve --driver "${DRIVER}" --host 127.0.0.1 --port 8765 &
REBOTD_PID=$!
sleep 0.2
if ! kill -0 "${REBOTD_PID}" 2>/dev/null; then
  wait "${REBOTD_PID}"
  echo "rebotd 启动失败。" >&2
  exit 1
fi

echo "reBotArm Studio 已启动（driver=${DRIVER}）"
echo "数字孪生: http://127.0.0.1:5173"
echo "RS 控制台: http://127.0.0.1:5173/rs-console/index.html"

cd "${REPO_DIR}/frontend/web-mujoco"
npm run dev
