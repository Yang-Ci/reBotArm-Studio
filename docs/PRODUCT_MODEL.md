# Multi-product model

Every selectable arm has a manifest at `products/<product-id>/product.json`.

The manifest is used for discovery and UI capability gating. Dynamic implementation is supplied
by the backend driver named in `driver`; the manifest is not executable configuration.

## Availability

- `supported`: visible and allowed to start hardware or simulation sessions.
- `planned`: visible as upcoming, but hardware start is rejected.
- `disabled`: hidden by default because the product failed validation or is intentionally retired.

## Shared behavior

The following concepts are product-independent:

- lifecycle and exclusive hardware ownership;
- command sequencing and stale-command rejection;
- safe-home state and result reporting;
- trajectory progress and cancellation;
- teaching file format;
- control target/reference/feedback telemetry;
- desktop IPC and MCP-facing operations.

## Product-owned behavior

Each product driver owns:

- bus and motor discovery;
- command encoding and motor modes;
- control rates and safe limits;
- joint direction, offsets, gains, and torque scales;
- hardware feedback decoding;
- product-specific error interpretation;
- robot and MuJoCo models.

Adding B601-DM must not change B601-RS parameters. Shared algorithms require separate product
configuration and product-specific regression tests.

