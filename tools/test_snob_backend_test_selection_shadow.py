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

            assert features.imports_api_client
            assert features.calls_http_client
            assert features.uses_api_url
            assert features.is_django_api_test
            assert "feature_flags" in features.api_tokens

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

            assert "product_api_client:feature_flags" in result.groups
            assert "product_api_route_tokens:feature_flags" in result.groups
            assert "same_app:products/feature_flags/backend" in result.groups
            assert ["products/feature_flags/backend/test/test_api.py"] == result.tests

    def test_ast_selection_matches_posthog_api_test_by_filename(self) -> None:
        selection = _load_selection_module()

        result = selection.ast_select_tests(
            ["posthog/api/project.py"],
            {
                "posthog/api/test/test_project.py": selection.TestFeatures(
                    path="posthog/api/test/test_project.py",
                    imports_api_client=True,
                    api_tokens=("project",),
                ),
                "posthog/api/test/test_user.py": selection.TestFeatures(
                    path="posthog/api/test/test_user.py",
                    imports_api_client=True,
                    api_tokens=("user",),
                ),
            },
        )

        assert "conventional_neighbors" in result.groups
        assert "posthog_api_route_tokens" in result.groups
        # same-app fallback includes all tests under posthog/api/
        assert "same_app:posthog/api" in result.groups
        assert "posthog/api/test/test_project.py" in result.tests
        assert "posthog/api/test/test_user.py" in result.tests

    def test_snob_selection_filters_to_python_files(self) -> None:
        selection = _load_selection_module()
        with tempfile.TemporaryDirectory() as root:
            selection.REPO_ROOT = Path(root)
            selected_test = selection.REPO_ROOT / "posthog" / "api" / "test" / "test_feature_flags.py"
            selected_test.parent.mkdir(parents=True)
            selected_test.write_text("def test_feature_flags():\n    pass\n")

            seen_changed_files: list[list[str]] = []

            fake_snob = ModuleType("snob_lib")

            def get_tests(changed_files: list[str]) -> set[str]:
                seen_changed_files.append(changed_files)
                return {str(selected_test)}

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

            assert [["posthog/api/feature_flags.py"]] == seen_changed_files
            assert {"status": "ok", "tests": ["posthog/api/test/test_feature_flags.py"], "count": 1} == result

    def test_signal_handler_change_expands_to_app_and_api_tests(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            tmp_path = Path(root)
            selection = _load_selection_module()
            selection.REPO_ROOT = tmp_path

            # A signal handler file
            handler = tmp_path / "posthog" / "models" / "signal_handlers.py"
            handler.parent.mkdir(parents=True)
            handler.write_text("from django.db.models.signals import post_save\npost_save.connect(my_handler)\n")

            # A test in the same app
            test_path = tmp_path / "posthog" / "models" / "test" / "test_models.py"
            test_path.parent.mkdir(parents=True)
            test_path.write_text("def test_model(): pass\n")

            # An API test elsewhere
            api_test = tmp_path / "posthog" / "api" / "test" / "test_something.py"
            api_test.parent.mkdir(parents=True)
            api_test.write_text("from rest_framework.test import APIClient\nclient = APIClient()\n")

            features_by_path = selection.classify_tests()
            result = selection.ast_select_tests(
                ["posthog/models/signal_handlers.py"],
                features_by_path,
            )

            assert "signal_handler_app:posthog/models" in result.groups
            assert "posthog/models/test/test_models.py" in result.tests

    def test_middleware_change_expands_to_api_tests(self) -> None:
        selection = _load_selection_module()

        result = selection.ast_select_tests(
            ["posthog/gzip_middleware.py"],
            {
                "posthog/api/test/test_capture.py": selection.TestFeatures(
                    path="posthog/api/test/test_capture.py",
                    imports_api_client=True,
                ),
                "posthog/models/test/test_utils.py": selection.TestFeatures(
                    path="posthog/models/test/test_utils.py",
                ),
            },
        )

        assert "middleware_api_tests" in result.groups
        assert "posthog/api/test/test_capture.py" in result.tests
        # Non-API tests are NOT included by middleware expansion
        assert "posthog/models/test/test_utils.py" not in result.groups.get("middleware_api_tests", [])

    def test_db_router_change_expands_to_api_tests(self) -> None:
        selection = _load_selection_module()

        result = selection.ast_select_tests(
            ["posthog/product_db_router.py"],
            {
                "posthog/api/test/test_user.py": selection.TestFeatures(
                    path="posthog/api/test/test_user.py",
                    imports_api_client=True,
                ),
            },
        )

        assert "db_router_api_tests" in result.groups
        assert "posthog/api/test/test_user.py" in result.tests

    def test_same_app_fallback_includes_sibling_tests(self) -> None:
        selection = _load_selection_module()

        result = selection.ast_select_tests(
            ["products/surveys/backend/models.py"],
            {
                "products/surveys/backend/test/test_api.py": selection.TestFeatures(
                    path="products/surveys/backend/test/test_api.py",
                ),
                "products/experiments/backend/test/test_api.py": selection.TestFeatures(
                    path="products/experiments/backend/test/test_api.py",
                ),
            },
        )

        # Same-app tests included
        assert "products/surveys/backend/test/test_api.py" in result.tests
        # Different app tests NOT included
        assert "products/experiments/backend/test/test_api.py" not in result.tests

    def test_too_many_files_signals_full_run(self) -> None:
        selection = _load_selection_module()

        many_files = [f"posthog/models/model_{i}.py" for i in range(60)]
        result = selection.ast_select_tests(many_files, {})

        assert any("too many changed files" in r for r in result.full_run_reasons)

    def test_high_fanout_file_signals_full_run(self) -> None:
        selection = _load_selection_module()

        original_path = selection.HIGH_FANOUT_PATH
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write("posthog/redis.py\nposthog/models/team/team.py\n")
                selection.HIGH_FANOUT_PATH = Path(f.name)

            result = selection.ast_select_tests(["posthog/redis.py"], {})
            assert any("high-fanout" in r for r in result.full_run_reasons)
        finally:
            selection.HIGH_FANOUT_PATH = original_path

    def test_changed_tests_do_not_trigger_full_run_patterns(self) -> None:
        selection = _load_selection_module()

        result = selection.ast_select_tests(
            ["posthog/test/test_version_requirement.py"],
            {
                "posthog/test/test_version_requirement.py": selection.TestFeatures(
                    path="posthog/test/test_version_requirement.py"
                )
            },
        )

        assert [] == result.full_run_reasons
        assert {"changed_tests": ["posthog/test/test_version_requirement.py"]} == result.groups


if __name__ == "__main__":
    unittest.main()
