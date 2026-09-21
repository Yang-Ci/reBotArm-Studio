from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from rebotd.products import ProductRegistry, ProductRegistryError  # noqa: E402


class ProductRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ProductRegistry.discover(REPO_ROOT / "products")

    def test_rs_is_supported(self) -> None:
        rs = self.registry.require_supported("b601-rs")
        self.assertEqual(rs.driver, "robstride_socketcan")
        self.assertIn("gravity_compensation", rs.capabilities)

    def test_dm_is_registered_for_future_selection(self) -> None:
        dm = self.registry.get("b601-dm")
        self.assertEqual(dm.availability, "planned")
        self.assertEqual(dm.family, "B601")

    def test_planned_product_cannot_start_hardware(self) -> None:
        with self.assertRaises(ProductRegistryError):
            self.registry.require_supported("b601-dm")

    def test_joint_names_are_unique(self) -> None:
        for product in self.registry.all():
            self.assertEqual(len(product.joints), len(set(product.joints)))


if __name__ == "__main__":
    unittest.main()

