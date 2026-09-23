# Desktop shell

Reserved for the Electron main process, preload bridge, window lifecycle, backend supervision,
and Linux packaging hooks. The renderer must use a narrow preload API with Node integration off.

At App startup, the main process will launch `rebotd` in detached-driver mode and wait for its
local health check before showing the control window. CAN discovery, product selection, safety
confirmation, connection, and safe disconnect remain UI operations; no terminal setup is part of
the end-user flow.

The Linux installer must grant the packaged backend the narrow network-administration capability
needed to set a selected SocketCAN interface down/up and configure its bitrate. This capability is
an installer responsibility and must not require a terminal command on each App launch.
