from __future__ import annotations

import argparse
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = ProductRegistry.discover(args.products_dir)
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

