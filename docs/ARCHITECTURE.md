# reBotArm Studio architecture

## Processes

```text
Electron renderer
    │ restricted IPC
    ▼
Electron main process
    │ Unix domain socket / authenticated localhost channel
    ▼
rebotd ── control core ── product driver ── hardware transport

Renderer ── RobotClient ── Web MuJoCo Worker (simulation mode)
```

The renderer never owns a CAN or serial connection. `rebotd` is the single writer for real
hardware and continues to enforce arbitration and watchdog behavior if the UI disconnects.

## Layers

1. **Product definition** describes discoverable products, transport defaults, joints,
   capabilities, and asset entry points.
2. **Control core** owns common safety state, trajectories, command arbitration, feedback,
   teaching playback, and lifecycle behavior.
3. **Product driver** translates common control references to RS MIT or DM control semantics.
4. **Transport** owns SocketCAN or the DM serial CAN bridge.
5. **RobotClient** exposes the same UI operations for hardware and Web MuJoCo modes.

## Non-goals

- The distributed App does not embed ROS 2.
- Web MuJoCo is not allowed to issue real motor commands.
- Product-specific gains and limits are not shared unless validated independently.
- An optional ROS bridge must be a separate package and process.
