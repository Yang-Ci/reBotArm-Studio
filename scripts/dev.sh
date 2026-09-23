#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REBOTD="${REPO_DIR}/backend/.venv/bin/rebotd"
DRIVER="disconnected"

if [[ "${1:-}" == "--fake" ]]; then
  DRIVER="fake"
elif [[ -n "${1:-}" ]]; then
  echo "用法: ./scripts/dev.sh [--fake]" >&2
  echo "真机连接请在 RS 控制台内扫描 CAN 并完成安全确认。" >&2
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
if [[ "${DRIVER}" == "disconnected" ]]; then
  echo "请在 RS 控制台内扫描并连接 PCAN；无需另开真机终端命令。"
fi

cd "${REPO_DIR}/frontend/web-mujoco"
npm run dev
