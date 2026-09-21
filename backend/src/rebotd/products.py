from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class ProductRegistryError(ValueError):
    """Raised when a product manifest is missing or inconsistent."""


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    display_name: str
    family: str
    availability: str
    driver: str
    transport: dict[str, Any]
    joints: tuple[str, ...]
    capabilities: frozenset[str]
    manifest_path: Path

    @property
    def supported(self) -> bool:
        return self.availability == "supported"

    @classmethod
    def from_manifest(cls, path: Path) -> "ProductDefinition":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductRegistryError(f"cannot read product manifest {path}: {exc}") from exc

        required = (
            "id",
            "displayName",
            "family",
            "availability",
            "driver",
            "transport",
            "joints",
            "capabilities",
        )
        missing = [key for key in required if key not in data]
        if missing:
            raise ProductRegistryError(
                f"product manifest {path} is missing: {', '.join(missing)}"
            )

        availability = str(data["availability"])
        if availability not in {"supported", "planned", "disabled"}:
            raise ProductRegistryError(
                f"invalid availability {availability!r} in {path}"
            )

        joints = tuple(str(name) for name in data["joints"])
        if not joints or len(joints) != len(set(joints)):
            raise ProductRegistryError(f"product joints must be unique and non-empty: {path}")

        return cls(
            product_id=str(data["id"]),
            display_name=str(data["displayName"]),
            family=str(data["family"]),
            availability=availability,
            driver=str(data["driver"]),
            transport=dict(data["transport"]),
            joints=joints,
            capabilities=frozenset(str(item) for item in data["capabilities"]),
            manifest_path=path,
        )


class ProductRegistry:
    def __init__(self, products: Iterable[ProductDefinition]) -> None:
        by_id: dict[str, ProductDefinition] = {}
        for product in products:
            if product.product_id in by_id:
                raise ProductRegistryError(f"duplicate product id: {product.product_id}")
            by_id[product.product_id] = product
        if not by_id:
            raise ProductRegistryError("product registry is empty")
        self._products = by_id

    @classmethod
    def discover(cls, products_dir: Path) -> "ProductRegistry":
        manifests = sorted(products_dir.glob("*/product.json"))
        return cls(ProductDefinition.from_manifest(path) for path in manifests)

    def all(self, *, include_disabled: bool = False) -> tuple[ProductDefinition, ...]:
        products = self._products.values()
        if not include_disabled:
            products = (item for item in products if item.availability != "disabled")
        return tuple(sorted(products, key=lambda item: item.product_id))

    def get(self, product_id: str) -> ProductDefinition:
        try:
            return self._products[product_id]
        except KeyError as exc:
            choices = ", ".join(sorted(self._products))
            raise ProductRegistryError(
                f"unknown product {product_id!r}; choices: {choices}"
            ) from exc

    def require_supported(self, product_id: str) -> ProductDefinition:
        product = self.get(product_id)
        if not product.supported:
            raise ProductRegistryError(
                f"product {product_id!r} is {product.availability}, not supported yet"
            )
        return product

