from __future__ import annotations

import os
import sys
import tempfile
import subprocess
import importlib.util
from pathlib import Path
from types import ModuleType

import unittest
from unittest import mock

from parameterized import parameterized

SCRIPT_PATH = Path(__file__).with_name("snob_backend_test_selection_shadow.py")


def _load_selection_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("snob_backend_test_selection_shadow", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_BASE_SETTINGS = 'CSRF_COOKIE_NAME = "csrftoken"\nEXISTING = get_from_env("EXISTING", "a")\n'
_NEW_URL = _BASE_SETTINGS + 'NEW_URL = get_from_env("NEW_URL", "https://example.com")\n'


def _git_in(root: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    ).stdout.strip()


def _git_init(root: str) -> None:
    _git_in(root, "init", "-q")


def _commit(root: str, files: dict[str, str]) -> str:
    for path, content in files.items():
        (Path(root) / path).parent.mkdir(parents=True, exist_ok=True)
        (Path(root) / path).write_text(content)
    _git_in(root, "add", "-A")
    _git_in(root, "commit", "-q", "-m", "test")
    return _git_in(root, "rev-parse", "HEAD")


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

            self.assertIn("product_api_client:feature_flags", result.groups)
            self.assertIn("product_api_route_tokens:feature_flags", result.groups)
            self.assertIn("same_app:products/feature_flags/backend", result.groups)
            self.assertEqual(["products/feature_flags/backend/test/test_api.py"], result.tests)

    def test_ast_selection_ignores_deleted_test_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            selection = _load_selection_module()
            selection.REPO_ROOT = Path(root)

            result = selection.ast_select_tests(["posthog/test/test_deleted.py"], {})

            self.assertEqual({}, result.groups)
            self.assertEqual([], result.tests)

    def test_ast_selection_matches_posthog_api_test_by_filename(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            tmp_path = Path(root)
            selection = _load_selection_module()
            selection.REPO_ROOT = tmp_path

            neighbor = tmp_path / "posthog" / "api" / "test" / "test_project.py"
            neighbor.parent.mkdir(parents=True)
            neighbor.touch()

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

            self.assertIn("conventional_neighbors", result.groups)
            self.assertIn("posthog_api_route_tokens", result.groups)
            # same-app fallback includes all tests under posthog/api/
            self.assertIn("same_app:posthog/api", result.groups)
            self.assertIn("posthog/api/test/test_project.py", result.tests)
            self.assertIn("posthog/api/test/test_user.py", result.tests)

    def test_snob_selection_filters_to_python_files(self) -> None:
        selection = _load_selection_module()
        with tempfile.TemporaryDirectory() as root:
            selection.REPO_ROOT = Path(root)
            selected_test = selection.REPO_ROOT / "posthog" / "api" / "test" / "test_feature_flags.py"
            selected_test.parent.mkdir(parents=True)
            selected_test.write_text("def test_feature_flags():\n    pass\n")
            deleted_test = selection.REPO_ROOT / "posthog" / "api" / "test" / "test_deleted.py"
            (selection.REPO_ROOT / "pytest.ini").write_text(
                "[pytest]\naddopts = --reuse-db --ignore=posthog/user_scripts\n"
            )
            pytest_ignored_file = selection.REPO_ROOT / "posthog" / "user_scripts" / "aggregate_funnel_test.py"
            pytest_ignored_file.parent.mkdir(parents=True)
            pytest_ignored_file.write_text("")

            seen_changed_files: list[list[str]] = []

            fake_snob = ModuleType("snob_lib")

            def get_tests(changed_files: list[str]) -> set[str]:
                seen_changed_files.append(changed_files)
                return {str(selected_test), str(deleted_test), str(pytest_ignored_file)}

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

            self.assertIn("signal_handler_app:posthog/models", result.groups)
            self.assertIn("posthog/models/test/test_models.py", result.tests)

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

        self.assertIn("middleware_api_tests", result.groups)
        self.assertIn("posthog/api/test/test_capture.py", result.tests)
        # Non-API tests are NOT included by middleware expansion
        self.assertNotIn("posthog/models/test/test_utils.py", result.groups.get("middleware_api_tests", []))

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

        self.assertIn("db_router_api_tests", result.groups)
        self.assertIn("posthog/api/test/test_user.py", result.tests)

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
        self.assertIn("products/surveys/backend/test/test_api.py", result.tests)
        # Different app tests NOT included
        self.assertNotIn("products/experiments/backend/test/test_api.py", result.tests)

    def test_too_many_files_signals_full_run(self) -> None:
        selection = _load_selection_module()

        many_files = [f"posthog/models/model_{i}.py" for i in range(60)]
        result = selection.ast_select_tests(many_files, {})

        self.assertTrue(any("too many changed files" in r for r in result.full_run_reasons))

    def test_high_fanout_file_signals_full_run(self) -> None:
        selection = _load_selection_module()

        original_path = selection.HIGH_FANOUT_PATH
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write("posthog/redis.py\nposthog/models/team/team.py\n")
                selection.HIGH_FANOUT_PATH = Path(f.name)

            result = selection.ast_select_tests(["posthog/redis.py"], {})
            self.assertTrue(any("high-fanout" in r for r in result.full_run_reasons))
        finally:
            selection.HIGH_FANOUT_PATH = original_path

    def test_changed_tests_do_not_trigger_full_run_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            selection = _load_selection_module()
            selection.REPO_ROOT = Path(root)
            test_path = selection.REPO_ROOT / "posthog" / "test" / "test_version_requirement.py"
            test_path.parent.mkdir(parents=True)
            test_path.touch()

            result = selection.ast_select_tests(
                ["posthog/test/test_version_requirement.py"],
                {
                    "posthog/test/test_version_requirement.py": selection.TestFeatures(
                        path="posthog/test/test_version_requirement.py"
                    )
                },
            )

            self.assertEqual([], result.full_run_reasons)
            self.assertEqual({"changed_tests": ["posthog/test/test_version_requirement.py"]}, result.groups)

    # ci-backend's `legacy` paths filter routes these into test selection, but none of
    # them is Python, so the import graph reaches no test through them. Without a full-run
    # pattern the selector returns an empty set and the narrowed run gates on nothing.
    @parameterized.expand(
        [
            ("quarantine_lift", ".test_quarantine.json"),
            ("hogql_parser_sources", "common/hogql_parser/HogQLParser.cpp"),
            ("hogql_parser_rs_sources", "rust/hogql/parser/src/lib.rs"),
            ("hogvm", "common/hogvm/python/execute.py"),
            ("personhog_stubs", "packages/personhog-proto/personhog/types/v1/person_pb2.py"),
        ]
    )
    def test_non_python_legacy_inputs_signal_full_run(self, _name: str, path: str) -> None:
        selection = _load_selection_module()

        result = selection.ast_select_tests([path], {})

        self.assertTrue(result.full_run_reasons, f"{path} selected nothing and forced no full run")

    @parameterized.expand(
        [
            ("root_conftest", "conftest.py", True),
            ("posthog_conftest", "posthog/api/test/conftest.py", True),
            # products/signals/backend/emission runs in the Temporal leg, below both of these.
            ("products_root_conftest", "products/conftest.py", True),
            ("temporal_leg_product_conftest", "products/signals/backend/conftest.py", True),
            ("product_conftest", "products/surveys/backend/test/conftest.py", False),
            ("settings_module_without_a_base", "posthog/settings/web.py", True),
            ("settings_data_file", "posthog/settings/allowlist.json", True),
            ("settings_owners", "posthog/settings/owners.yaml", False),
            ("posthog_test_helper", "posthog/test/base.py", True),
            ("product_manifest", "products/surveys/manifest.tsx", False),
            ("products_json", "frontend/src/products.json", True),
        ]
    )
    def test_full_run_scope(self, _name: str, path: str, expect_full_run: bool) -> None:
        selection = _load_selection_module()

        result = selection.ast_select_tests([path], {})

        self.assertEqual(bool(result.full_run_reasons), expect_full_run, result.full_run_reasons)

    def test_repo_invariants_baseline_selects_the_repo_invariants_guards(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            selection = _load_selection_module()
            selection.REPO_ROOT = Path(root)
            guard = "posthog/test/repo_invariants/test_startup_import_budget.py"
            (selection.REPO_ROOT / guard).parent.mkdir(parents=True)
            (selection.REPO_ROOT / guard).touch()

            result = selection.ast_select_tests(
                ["posthog/test/repo_invariants/setup_receivers_baseline.txt"],
                {
                    guard: selection.TestFeatures(path=guard),
                    "posthog/api/test/test_user.py": selection.TestFeatures(path="posthog/api/test/test_user.py"),
                },
            )

            self.assertEqual([], result.full_run_reasons)
            self.assertEqual({"repo_invariants_baselines": [guard]}, result.groups)

    @parameterized.expand(
        [
            ("adds_a_name_a_changed_file_reads", _NEW_URL, {"posthog/consumer.py": "settings.NEW_URL\n"}, False),
            (
                "adds_a_name_with_a_type_cast",
                _BASE_SETTINGS + 'NEW_URL = get_from_env("NEW_URL", 1, type_cast=int)\n',
                {"posthog/consumer.py": "settings.NEW_URL\n"},
                False,
            ),
            ("comment_only", _BASE_SETTINGS + "# A note.\n", {}, False),
            (
                "passes_a_callback_that_mutates_an_existing_setting",
                _BASE_SETTINGS + "NEW_URL = min([{}], key=EXISTING.update)\n",
                {"posthog/consumer.py": "settings.NEW_URL\n"},
                True,
            ),
            (
                "adds_a_django_setting_in_a_new_namespace",
                _BASE_SETTINGS + "PREPEND_WWW = True\n",
                {"posthog/consumer.py": "settings.PREPEND_WWW\n"},
                True,
            ),
            ("adds_a_name_nothing_reads", _NEW_URL, {}, True),
            (
                "adds_a_name_an_unchanged_file_reads",
                _BASE_SETTINGS + "PRESET = 1\n",
                {"posthog/consumer.py": "settings.PRESET\n"},
                True,
            ),
            (
                "changes_an_existing_value",
                _BASE_SETTINGS.replace('"a"', '"b"'),
                {"posthog/consumer.py": "settings.EXISTING\n"},
                True,
            ),
            (
                "renames_a_setting",
                _BASE_SETTINGS.replace("EXISTING =", "RENAMED ="),
                {"posthog/consumer.py": "settings.RENAMED\n"},
                True,
            ),
            (
                "reassigns_a_name_from_another_settings_module",
                _BASE_SETTINGS + "ALREADY = 2\n",
                {"posthog/consumer.py": "settings.ALREADY\n"},
                True,
            ),
            (
                "calls_a_function_with_side_effects",
                _BASE_SETTINGS + "NEW_URL = configure()\n",
                {"posthog/consumer.py": "settings.NEW_URL\n"},
                True,
            ),
            (
                "assignment_expression",
                _BASE_SETTINGS + "NEW_URL = (EXISTING := 1)\n",
                {"posthog/consumer.py": "settings.NEW_URL\n"},
                True,
            ),
            (
                "adds_to_a_namespace_a_framework_reads",
                _BASE_SETTINGS + "CSRF_COOKIE_AGE = 1\n",
                {"posthog/consumer.py": "settings.CSRF_COOKIE_AGE\n"},
                True,
            ),
            ("unparsable", _NEW_URL + "BROKEN = (\n", {"posthog/consumer.py": "settings.NEW_URL\n"}, True),
            (
                "reorders_statements",
                'EXISTING = get_from_env("EXISTING", "a")\nCSRF_COOKIE_NAME = "csrftoken"\n',
                {},
                True,
            ),
        ]
    )
    def test_settings_change_runs_in_full_unless_it_only_adds_names_the_diff_reads(
        self, _name: str, head_settings: str, head_files: dict[str, str], expect_full_run: bool
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            selection = _load_selection_module()
            selection.REPO_ROOT = Path(root)
            _git_init(root)
            base = _commit(
                root,
                {
                    "posthog/settings/web.py": _BASE_SETTINGS,
                    "posthog/settings/other.py": "ALREADY = 1\n",
                    "posthog/reader.py": "settings.EXISTING\n",
                    "posthog/preset_reader.py": "settings.PRESET\n",
                },
            )
            _commit(root, {"posthog/settings/web.py": head_settings, **head_files})

            result = selection.ast_select_tests(["posthog/settings/web.py", *head_files], {}, base)

            self.assertEqual(bool(result.full_run_reasons), expect_full_run, result.full_run_reasons)

    @parameterized.expand(
        [
            ("repo_invariant_helper", "posthog/test/repo_invariants/ratchet.py"),
            ("repo_invariant_guard", "posthog/test/repo_invariants/test_ratchet.py"),
            ("temporal_workflow_catalog", "posthog/temporal/workflow_catalog.json"),
        ]
    )
    def test_inputs_with_no_django_reader_select_nothing(self, _name: str, path: str) -> None:
        selection = _load_selection_module()
        features_by_path = {
            "posthog/temporal/tests/test_workflow.py": selection.TestFeatures(
                path="posthog/temporal/tests/test_workflow.py", uses_temporal=True
            ),
            "posthog/test/repo_invariants/test_ratchet.py": selection.TestFeatures(
                path="posthog/test/repo_invariants/test_ratchet.py"
            ),
        }

        result = selection.ast_select_tests([path], features_by_path)

        self.assertEqual([], result.full_run_reasons)
        self.assertEqual({}, result.groups)

    @parameterized.expand(
        [
            ("sibling", "posthog/api/test/__snapshots__/test_query.ambr", ["posthog/api/test/test_query.py"]),
            (
                "schema_variant",
                "posthog/api/test/__snapshots__/test_query.new_events_schema.ambr",
                ["posthog/api/test/test_query.py"],
            ),
            ("under_full_run_prefix", "posthog/test/__snapshots__/test_team.ambr", ["posthog/test/test_team.py"]),
            (
                "shared_file_falls_back_to_directory",
                "posthog/hogql/test/__snapshots__/parser_ast.ambr",
                ["posthog/hogql/test/test_parser_cpp_json.py", "posthog/hogql/test/test_parser_rust_json.py"],
            ),
        ]
    )
    def test_changed_snapshot_selects_the_tests_that_own_it(self, _name: str, path: str, expected: list[str]) -> None:
        with tempfile.TemporaryDirectory() as root:
            selection = _load_selection_module()
            selection.REPO_ROOT = Path(root)
            test_files = [
                "posthog/api/test/test_query.py",
                "posthog/api/test/test_team.py",
                "posthog/test/test_team.py",
                "posthog/hogql/test/test_parser_cpp_json.py",
                "posthog/hogql/test/test_parser_rust_json.py",
            ]
            for test_file in test_files:
                (selection.REPO_ROOT / test_file).parent.mkdir(parents=True, exist_ok=True)
                (selection.REPO_ROOT / test_file).touch()

            result = selection.ast_select_tests(
                [path], {test_file: selection.TestFeatures(path=test_file) for test_file in test_files}
            )

            self.assertEqual([], result.full_run_reasons)
            self.assertEqual(expected, result.groups.get("snapshot_owners"))

    @parameterized.expand(
        [
            ("core", "posthog/models/test_a.py", {"core"}),
            # POE patterns run in both the Core matrix and the person-on-events matrix.
            ("poe_runs_in_core_too", "posthog/clickhouse/test_b.py", {"core", "poe"}),
            ("temporal", "posthog/temporal/tests/test_c.py", {"temporal"}),
            # The Temporal invocation runs the product suites alongside posthog/temporal.
            ("temporal_signals_emission", "products/signals/backend/emission/test_c.py", {"temporal"}),
            # Explicitly ignored by the Core invocation, and not a draft-narrowable matrix.
            ("core_ignored_dags", "posthog/dags/test_e.py", set()),
            ("core_ignored_repo_invariants", "posthog/test/repo_invariants/test_f.py", set()),
            # Product/turbo tests are not part of any draft-narrowable Django matrix.
            ("turbo_product", "products/warehouse_sources/backend/test_d.py", set()),
        ]
    )
    def test_segments_for_test_file_mirrors_matrix_partition(self, _name: str, path: str, expected: set[str]) -> None:
        selection = _load_selection_module()

        self.assertEqual(selection.segments_for_test_file(path), frozenset(expected))

    @parameterized.expand(
        [
            (
                "compat_targets_set",
                "posthog/clickhouse ee/clickhouse",
                ["ee/clickhouse/test_g.py", "posthog/clickhouse/test_b.py"],
            ),
            ("no_compat_targets", "", []),
        ]
    )
    def test_selected_files_by_segment_reads_compat_targets_from_the_env(
        self, _name: str, targets: str, expected_compat: list[str]
    ) -> None:
        selection = _load_selection_module()

        selected = [
            "ee/clickhouse/test_g.py",
            "posthog/clickhouse/test_b.py",
            "posthog/dags/test_e.py",
            "posthog/models/test_a.py",
            "posthog/temporal/tests/test_c.py",
            "products/warehouse_sources/backend/test_d.py",
        ]

        with mock.patch.dict(os.environ, {"CLICKHOUSE_COMPAT_PYTEST_TARGETS": targets}):
            by_segment = selection.selected_files_by_segment(selected)

        self.assertEqual(
            by_segment,
            {
                "core": ["ee/clickhouse/test_g.py", "posthog/clickhouse/test_b.py", "posthog/models/test_a.py"],
                "poe": ["ee/clickhouse/test_g.py", "posthog/clickhouse/test_b.py"],
                "temporal": ["posthog/temporal/tests/test_c.py"],
                "compat": expected_compat,
            },
        )

    def test_narrowable_baseline_excludes_turbo_product_tests(self) -> None:
        selection = _load_selection_module()

        durations = {
            "posthog/models/test_a.py::t1": 100.0,
            "posthog/clickhouse/test_b.py::t2": 70.0,
            "posthog/temporal/tests/test_c.py::t3": 210.0,
            "posthog/dags/test_e.py::t5": 42.0,  # ignored path
            "products/warehouse_sources/backend/test_d.py::t4": 100_000.0,  # turbo-tests
        }

        # Only the Core/POE/Temporal universe counts; the huge product test and the ignored
        # path are excluded, so a draft can never be credited with skipping them.
        self.assertEqual(selection.narrowable_baseline_seconds(durations), 380.0)

    def test_selected_seconds_by_segment_splits_the_matrix_legs(self) -> None:
        selection = _load_selection_module()

        durations = {
            "posthog/models/test_a.py::t1": 100.0,
            "posthog/clickhouse/test_b.py::t2": 70.0,
            "posthog/temporal/tests/test_c.py::t3": 210.0,
            "posthog/models/test_unselected.py::t4": 5_000.0,
            "products/warehouse_sources/backend/test_d.py::t5": 100_000.0,
            "posthog/dags/test_e.py::t6": 42.0,
        }
        selected = [
            "posthog/models/test_a.py",
            "posthog/clickhouse/test_b.py",
            "posthog/temporal/tests/test_c.py",
            "products/warehouse_sources/backend/test_d.py",
            "posthog/dags/test_e.py",
        ]

        # The clickhouse file runs in both the Core and the person-on-events leg, so its
        # seconds count once per leg. Turbo product tests and ignored paths size no Django
        # shard, and an unselected file never contributes.
        self.assertEqual(
            selection.selected_seconds_by_segment(selected, durations),
            {"core": 170, "poe": 70, "temporal": 210},
        )


if __name__ == "__main__":
    unittest.main()
