# B601-RS hardware acceptance checklist

This checklist is intentionally not automated. Run it on the physical test bench with the
workspace clear, the emergency stop reachable, and a second person observing. Start at low
velocity and without payload.

## Before motion

- Confirm joint wiring, motor IDs, reduction ratios and zero directions match
  `backend/config/rebotarm_hardware.yaml`.
- Confirm `can0` is up at 1 Mbit/s and `./scripts/doctor.sh can0` reports all checks `OK`.
- Verify each joint can be disabled by the physical emergency stop.
- Start `./scripts/dev.sh --hardware` only after setting the explicit hardware confirmation.
- Connect the browser while its control lock remains off; compare all six joint readings with
  the physical arm.

## Controlled checks

- Enable, hold position, then command each joint separately by no more than 2 degrees.
- Verify direction, feedback, velocity limit and status code for J1–J6.
- Test gripper open, close, hold, manual release and low-resistance assist with no object.
- Run safe-home from a near-zero pose and confirm disable only occurs after settling.
- Run one short multi-joint trajectory, cancel mid-path, and verify hold behavior.
- Test TCP IK and Cartesian trajectory in the centre of the reachable workspace.
- Test gravity compensation start/stop while ready to use the emergency stop.
- Disconnect the browser and verify the daemon watchdog holds the current pose.
- Terminate the local launcher and verify safe-home/disable shutdown behavior.

## Record

Record arm serial number, controller/SDK revision, operator, date, results, and any changed
limits or gains. Do not mark B601-RS packaging-ready until every check passes on the target
Ubuntu machine.
