# Repository guidelines

- The shipped application core must not depend on ROS 2, `rclpy`, ament, colcon, or rosbridge.
- Product-specific behavior belongs under `products/` or behind a backend driver interface.
- Do not branch on product IDs throughout the UI. Read capabilities from the selected product manifest.
- `rebotd` is the sole owner of a real hardware transport. Browser code must never control motors directly.
- Preserve the existing safety state machine, command arbitration, safe-home verification, and watchdog behavior.
- Never copy build outputs, virtual environments, `node_modules`, generated distributions, or ROS logs into this repository.
- Keep B601-RS operational while adding B601-DM; shared code must not silently change RS gains or limits.
- Hardware-affecting changes require unit tests, fake-driver tests, and an explicit hardware acceptance checklist.

