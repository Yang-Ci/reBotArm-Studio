# Migration plan

## Phase 1 — RS control core ✅ local

- Move the existing hardware manager, motion profiles, trajectory profiles, SDK and required
  configuration into `backend/`.
- Replace ROS geometry/message classes with ordinary Python dataclasses.
- Move trajectory execution and cancellation out of ROS actions.
- Add a fake RS driver and golden behavior tests against the existing implementation.

## Phase 2 — daemon and protocol ✅ local

- Implement the single-owner `rebotd` lifecycle.
- Add product selection, command sequencing, status streaming, session leases, and watchdogs.
- Implement the RS driver behind a common driver protocol.

## Phase 3 — user interface and simulation 🚧

- The existing RS control UI now uses the `rebotd` compatibility client.
- Web MuJoCo and its B601-RS assets now live in `frontend/web-mujoco` and `assets/mujoco`.
- Remaining: consolidate both pages behind the final product/mode selector and port the
  optional RealSense/LLM helpers without restoring a ROS runtime dependency.

## Phase 4 — packaging (after local and hardware acceptance)

- Bundle the frontend in Electron.
- Package Python 3.11 and native control dependencies as an onedir backend bundle.
- Produce Ubuntu 24.04 x86_64 deb and AppImage artifacts.

## Phase 5 — DM

- Import the DM model and validated controller into a new `damiao_serial_can` driver.
- Run the same contract suite with DM-specific limits and hardware acceptance checks.
- Change B601-DM availability from `planned` to `supported` only after verification.
