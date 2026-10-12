from __future__ import annotations

import sys
import tempfile
import importlib.util
from pathlib import Path
from types import ModuleType

import unittest

from parameterized import parameterized

SCRIPT_PATH = Path(__file__).with_name("warehouse_sources_vendor_selection.py")


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("warehouse_sources_vendor_selection", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


selection = _load_module()

SELECTION_CASES = [
    (
        "one_vendor",
        ["sources/demo_acme/source.py", "sources/demo_acme/tests/test_demo_acme.py"],
        "vendors",
        ("demo_acme",),
        (),
    ),
    (
        "two_vendors",
        ["sources/stripe/source.py", "sources/demo_acme/source.py"],
        "vendors",
        ("demo_acme", "stripe"),
        (),
    ),
    (
        "deleted_vendor_is_dropped",
        ["sources/demo_acme/source.py", "sources/gone/source.py"],
        "vendors",
        ("demo_acme",),
        ("gone",),
    ),
    ("sdk", ["sources/demo_acme/source.py", "sources/sdk/testing.py"], "full", (), ()),
    ("sources_conftest", ["sources/demo_acme/source.py", "sources/conftest.py"], "full", (), ()),
    ("sources_owners_file", ["sources/owners.yaml"], "full", (), ()),
    (
        "product_backend",
        ["sources/demo_acme/source.py", "products/warehouse_sources/backend/temporal/data_imports/pipelines/x.py"],
        "full",
        (),
        (),
    ),
    ("empty_diff", [], "full", (), ()),
]


class TestVendorSelection(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for vendor in ("sdk", "demo_acme", "stripe"):
            (self.root / "sources" / vendor).mkdir(parents=True)

    @parameterized.expand(SELECTION_CASES)
    def test_select(
        self,
        _name: str,
        changed_files: list[str],
        mode: str,
        vendors: tuple[str, ...],
        deleted_vendors: tuple[str, ...],
    ) -> None:
        result = selection.VendorSelector(self.root).select(changed_files)

        self.assertEqual(
            (result.mode, result.vendors, result.deleted_vendors),
            (mode, vendors, deleted_vendors),
        )

    def test_scan_scope_covers_deleted_vendors_too(self) -> None:
        result = selection.VendorSelector(self.root).select(["sources/gone/source.py", "sources/stripe/source.py"])

        self.assertEqual(
            result.github_output(),
            "mode=vendors\nvendors=stripe\nscan_scope=sources/gone sources/stripe",
        )


if __name__ == "__main__":
    unittest.main()
