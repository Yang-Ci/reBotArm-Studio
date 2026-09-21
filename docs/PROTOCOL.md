# rebotd local protocol

The Studio frontend connects to `ws://127.0.0.1:8765`. Messages are UTF-8 JSON.
The daemon is the only process allowed to own the CAN transport.

## Request and response

```json
{"id":"request:1","method":"system.hello","params":{}}
{"id":"request:1","ok":true,"result":{"protocolVersion":1,"productId":"b601-rs"}}
```

Notifications omit `id` and do not receive a response. Errors for requests use
`{"ok":false,"error":{"type":"...","message":"..."}}`.

## Commands

- `system.hello`, `system.ping`, `system.status`
- `arm.enable`, `arm.disable`, `arm.safe_home`, `arm.hold`, `arm.set_zero`
- `joint.set_target`, `joint.set_targets`
- `trajectory.execute`, `trajectory.cancel`
- `tcp.move_ik`, `tcp.move_trajectory`
- `gripper.set`, `gripper.open`, `gripper.close`, `gripper.release`,
  `gripper.hold`, `gripper.assist_start`, `gripper.status`
- `gravity.start`, `gravity.stop`, `gravity.status`

Joint angles use radians, angular velocity uses radians per second, gripper width uses metres,
and Cartesian positions use metres. Trajectory point time is seconds.

## Telemetry

At 20 Hz the daemon emits:

```json
{"event":"telemetry","data":{"position":[0,0,0,0,0,0],"enabled":true}}
```

Telemetry also includes joint velocity/torque/status, control target/reference, state machine,
gravity compensation, gripper feedback, product ID and driver ID. If the last client lease
expires while the arm is enabled, the daemon holds the current position.
