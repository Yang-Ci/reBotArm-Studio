# Migration plan

## Phase 1 — RS control core

- Move the existing hardware manager, motion profiles, trajectory profiles, SDK and required
  configuration into `backend/`.
- Replace ROS geometry/message classes with ordinary Python dataclasses.
- Move trajectory execution and cancellation out of ROS actions.
- Add a fake RS driver and golden behavior tests against the existing implementation.

## Phase 2 — daemon and protocol

- Implement the single-owner `rebotd` lifecycle.
- Add product selection, command sequencing, status streaming, session leases, and watchdogs.
- Implement the RS driver behind a common driver protocol.

## Phase 3 — user interface and simulation

- Port the existing control UI to `RobotClient`.
- Move the current Web MuJoCo implementation into `frontend/web-mujoco`.
- Provide explicit product and hardware/simulation selectors.

## Phase 4 — packaging

- Bundle the frontend in Electron.
- Package Python 3.11 and native control dependencies as an onedir backend bundle.
- Produce Ubuntu 24.04 x86_64 deb and AppImage artifacts.

## Phase 5 — DM

- Import the DM model and validated controller into a new `damiao_serial_can` driver.
- Run the same contract suite with DM-specific limits and hardware acceptance checks.
- Change B601-DM availability from `planned` to `supported` only after verification.

