from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
from pathlib import Path

from .products import ProductRegistry, ProductRegistryError


def default_products_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "products"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rebotd")
    parser.add_argument(
        "--products-dir",
        type=Path,
        default=default_products_dir(),
        help="directory containing <product-id>/product.json manifests",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    products = commands.add_parser("products", help="inspect product definitions")
    product_commands = products.add_subparsers(dest="products_command", required=True)
    product_commands.add_parser("list", help="list selectable products")
    show = product_commands.add_parser("show", help="show one product")
    show.add_argument("product_id")

    serve = commands.add_parser("serve", help="run the local robot daemon")
    serve.add_argument("--product", default="b601-rs")
    serve.add_argument(
        "--driver",
        choices=("disconnected", "fake", "rs"),
        default="disconnected",
        help="start detached for in-app CAN discovery, or select a test/legacy direct driver",
    )
    serve.add_argument("--channel", default="can0")
    serve.add_argument("--hardware-config", default="")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--token", default="")
    serve.add_argument("--telemetry-rate", type=float, default=20.0)
    serve.add_argument("--confirm", default="")

    doctor = commands.add_parser("doctor", help="check local RS runtime prerequisites")
    doctor.add_argument("--channel", default="can0")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = ProductRegistry.discover(args.products_dir)
        if args.command == "doctor":
            return _doctor(args.channel)
        if args.command == "serve":
            return _serve(args, registry)
        if args.products_command == "list":
            for product in registry.all():
                print(
                    f"{product.product_id}\t{product.availability}\t"
                    f"{product.display_name}\t{product.driver}"
                )
            return 0

        product = registry.get(args.product_id)
        print(f"id: {product.product_id}")
        print(f"name: {product.display_name}")
        print(f"availability: {product.availability}")
        print(f"driver: {product.driver}")
        print(f"joints: {', '.join(product.joints)}")
        print(f"capabilities: {', '.join(sorted(product.capabilities))}")
        return 0
    except ProductRegistryError as exc:
        print(f"error: {exc}")
        return 2


def _doctor(channel: str) -> int:
    checks = []
    for module in ("numpy", "yaml", "websockets", "motorbridge", "pinocchio"):
        available = importlib.util.find_spec(module) is not None
        checks.append(available)
        print(f"{'OK' if available else 'MISSING'}\tpython module\t{module}")
    channel_path = Path("/sys/class/net") / channel
    channel_exists = channel_path.exists()
    checks.append(channel_exists)
    print(f"{'OK' if channel_exists else 'MISSING'}\tSocketCAN\t{channel}")
    from .core.hardware_config import default_hardware_config_path, repository_root

    resources = (
        default_hardware_config_path(),
        repository_root() / "backend" / "vendor" / "reBotArm_control_py",
        repository_root() / "assets" / "robot" / "b601-rs" / "urdf" / "ReBot_Arm_RS.urdf",
        repository_root() / "assets" / "robot" / "b601-rs" / "meshes_rs" / "link1.STL",
        repository_root() / "assets" / "mujoco" / "b601-rs" / "rs_grasp_scene.xml",
    )
    for path in resources:
        exists = path.exists()
        checks.append(exists)
        print(f"{'OK' if exists else 'MISSING'}\tresource\t{path}")
    return 0 if all(checks) else 1


def _serve(args, registry: ProductRegistry) -> int:
    product = registry.require_supported(args.product)
    if product.product_id != "b601-rs":
        raise ProductRegistryError(
            f"no runtime driver is implemented for {product.product_id}"
        )

    from .drivers import create_rs_driver

    driver = None
    driver_name = "disconnected"
    if args.driver == "rs":
        confirmation = args.confirm or os.environ.get("REBOTARM_HARDWARE_CONFIRM", "")
        if confirmation != "I_UNDERSTAND_REBOTARM_WILL_MOVE":
            raise ProductRegistryError(
                "real hardware requires --confirm I_UNDERSTAND_REBOTARM_WILL_MOVE"
            )
        driver = create_rs_driver(
            channel=args.channel,
            hardware_config=args.hardware_config or None,
        )
        driver_name = "robstride_socketcan"
    else:
        if args.driver == "fake":
            from .drivers import FakeRSDriver

            driver = FakeRSDriver()
            driver_name = "fake_rs"

    from .server import RebotdServer
    from .service import RobotService

    if driver is not None:
        driver.connect()
    service = None
    try:
        service = RobotService(
            driver,
            product_id=product.product_id,
            driver_name=driver_name,
            channel=args.channel if args.driver == "rs" else "",
            driver_factory=lambda *, channel: create_rs_driver(
                channel=channel,
                hardware_config=args.hardware_config or None,
            ),
        )
        server = RebotdServer(
            service,
            host=args.host,
            port=args.port,
            token=args.token,
            telemetry_rate=args.telemetry_rate,
        )
        print(
            f"rebotd: product={product.product_id} driver={driver_name} "
            f"url=ws://{args.host}:{args.port}"
        )
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print("rebotd: stopping")
    finally:
        if service is not None:
            service.shutdown()
        elif driver is not None:
            driver.shutdown(disable_after_safe_home=True)
    return 0
