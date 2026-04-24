from __future__ import annotations

import sys
import tempfile
import importlib.util
from pathlib import Path
from types import ModuleType

import unittest

SCRIPT_PATH = Path(__file__).with_name("snob_backend_test_selection_shadow.py")


def _load_selection_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("snob_backend_test_selection_shadow", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestSnobBackendTestSelectionShadow(unittest.TestCase):
    def test_classifies_django_api_client_tests(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            tmp_path = Path(root)
            selection = _load_selection_module()
            selection.REPO_ROOT = tmp_path

            test_path = tmp_path / "products" / "feature_flags" / "backend" / "test" / "test_api.py"
            test_path.parent.mkdir(parents=True)
            test_path.write_text(
                "\n".join(
                    [
                        "from rest_framework.test import APIClient",
                        "",
                        "def test_feature_flags_endpoint():",
                        "    client = APIClient()",
                        "    client.get('/api/projects/1/feature_flags/')",
                    ]
                )
            )

            features = selection.classify_test_file("products/feature_flags/backend/test/test_api.py")

            self.assertTrue(features.imports_api_client)
            self.assertTrue(features.calls_http_client)
            self.assertTrue(features.uses_api_url)
            self.assertTrue(features.is_django_api_test)
            self.assertIn("feature_flags", features.api_tokens)

    def test_ast_selection_groups_product_api_client_tests(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            tmp_path = Path(root)
            selection = _load_selection_module()
            selection.REPO_ROOT = tmp_path

            test_path = tmp_path / "products" / "feature_flags" / "backend" / "test" / "test_api.py"
            test_path.parent.mkdir(parents=True)
            test_path.write_text(
                "\n".join(
                    [
                        "def test_feature_flags_endpoint(api_client):",
                        "    api_client.get('/api/projects/1/feature_flags/')",
                    ]
                )
            )

            features_by_path = selection.classify_tests()
            result = selection.ast_select_tests(
                ["products/feature_flags/backend/api/feature_flags.py"],
                features_by_path,
            )

            self.assertEqual(
                {
                    "product_api_client:feature_flags": ["products/feature_flags/backend/test/test_api.py"],
                    "product_api_route_tokens:feature_flags": ["products/feature_flags/backend/test/test_api.py"],
                },
                result.groups,
            )
            self.assertEqual(["products/feature_flags/backend/test/test_api.py"], result.tests)

    def test_snob_selection_filters_to_python_files(self) -> None:
        selection = _load_selection_module()
        seen_changed_files: list[list[str]] = []

        fake_snob = ModuleType("snob_lib")

        def get_tests(changed_files: list[str]) -> set[str]:
            seen_changed_files.append(changed_files)
            return {"posthog/api/test/test_feature_flags.py"}

        fake_snob.get_tests = get_tests  # type: ignore[attr-defined]
        previous_snob = sys.modules.get("snob_lib")
        sys.modules["snob_lib"] = fake_snob
        try:
            result = selection.snob_select_tests(["posthog/api/feature_flags.py", "frontend/src/index.ts"])
        finally:
            if previous_snob is None:
                del sys.modules["snob_lib"]
            else:
                sys.modules["snob_lib"] = previous_snob

        self.assertEqual([["posthog/api/feature_flags.py"]], seen_changed_files)
        self.assertEqual(
            {"status": "ok", "tests": ["posthog/api/test/test_feature_flags.py"], "count": 1},
            result,
        )


if __name__ == "__main__":
    unittest.main()
