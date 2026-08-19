from __future__ import annotations

import sys
import json
import tempfile
import importlib.util
from pathlib import Path
from types import ModuleType

import unittest

SCRIPT_PATH = Path(__file__).with_name("dagster_test_selection.py")


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dagster_test_selection", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestDagsterTestSelection(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.module = _load_module()
        self.module.REPO_ROOT = root
        self.module.DURATIONS_PATH = root / ".test_durations"
        self.root = root

        self._write("posthog/dags/deletes.py")
        self._write("posthog/dags/tests/conftest.py")
        self._write("posthog/dags/tests/test_deletes.py")
        self._write("posthog/dags/tests/test_backups.py")
        self._write("products/web_analytics/dags/cache_warming.py")
        self._write("products/web_analytics/dags/tests/test_cache_warming.py")

    def _write(self, path: str, content: str = "") -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def _select(self, changed: list[str], snob: dict[str, list[str]] | None = None):
        snob_map = snob or {}

        def fake_snob(files: list[str]) -> set[str]:
            return {test for changed_file in files for test in snob_map.get(changed_file, [])}

        return self.module.build_selection(changed, snob_fn=fake_snob)

    def test_infrastructure_changes_force_full_mode(self) -> None:
        for changed in (
            "uv.lock",
            "pytest.ini",
            "pyproject.toml",
            ".github/workflows/ci-dagster.yml",
            "posthog/conftest.py",
            "conftest.py",
            "posthog/test/base.py",
        ):
            with self.subTest(changed=changed):
                selection = self._select([changed, "posthog/dags/deletes.py"])
                self.assertEqual(selection.mode, "full")
                self.assertTrue(selection.reasons)

    def test_a_conftest_outside_dags_trees_does_not_force_full_mode(self) -> None:
        selection = self._select(["products/web_analytics/backend/conftest.py"])
        self.assertEqual(selection.mode, "none")

    def test_too_many_changed_files_force_full_mode(self) -> None:
        changed = [f"posthog/dags/file_{i}.py" for i in range(self.module.MAX_CHANGED_FILES + 1)]
        selection = self._select(changed)
        self.assertEqual(selection.mode, "full")

    def test_changed_test_file_selects_itself(self) -> None:
        selection = self._select(["posthog/dags/tests/test_deletes.py"])
        self.assertEqual(selection.mode, "selected")
        self.assertEqual(selection.tests, ["posthog/dags/tests/test_deletes.py"])

    def test_changed_dag_module_selects_its_importing_tests(self) -> None:
        selection = self._select(
            ["posthog/dags/deletes.py"],
            snob={"posthog/dags/deletes.py": ["posthog/dags/tests/test_deletes.py"]},
        )
        self.assertEqual(selection.mode, "selected")
        self.assertEqual(selection.tests, ["posthog/dags/tests/test_deletes.py"])

    def test_blind_spot_changes_fall_back_to_the_whole_tree(self) -> None:
        for changed in (
            "posthog/dags/tests/conftest.py",
            "posthog/dags/tests/__snapshots__/test_deletes.ambr",
            "posthog/dags/deleted_module.py",
        ):
            with self.subTest(changed=changed):
                selection = self._select([changed])
                self.assertEqual(selection.mode, "selected")
                self.assertEqual(
                    selection.tests,
                    ["posthog/dags/tests/test_backups.py", "posthog/dags/tests/test_deletes.py"],
                )
                self.assertEqual(selection.fallback_trees, ["posthog/dags"])

    def test_tree_fallback_stays_within_the_changed_tree(self) -> None:
        selection = self._select(["products/web_analytics/dags/tests/conftest.py"])
        self.assertEqual(selection.tests, ["products/web_analytics/dags/tests/test_cache_warming.py"])

    def test_markdown_changes_in_a_dags_tree_select_nothing(self) -> None:
        selection = self._select(["posthog/dags/README.md"])
        self.assertEqual(selection.mode, "none")

    def test_changes_outside_dags_trees_keep_only_dag_tests_from_snob(self) -> None:
        selection = self._select(
            ["posthog/models/team.py"],
            snob={
                "posthog/models/team.py": [
                    "posthog/dags/tests/test_deletes.py",
                    "posthog/api/test/test_team.py",
                ]
            },
        )
        self.assertEqual(selection.mode, "selected")
        self.assertEqual(selection.tests, ["posthog/dags/tests/test_deletes.py"])

    def test_changes_outside_dags_trees_with_no_dag_impact_select_nothing(self) -> None:
        selection = self._select(["posthog/models/team.py"], snob={"posthog/models/team.py": []})
        self.assertEqual(selection.mode, "none")

    def test_deleted_test_files_are_dropped_from_the_selection(self) -> None:
        selection = self._select(
            ["posthog/dags/deletes.py"],
            snob={"posthog/dags/deletes.py": ["posthog/dags/tests/test_deletes.py", "posthog/dags/tests/test_gone.py"]},
        )
        self.assertEqual(selection.tests, ["posthog/dags/tests/test_deletes.py"])

    def test_selection_covering_most_of_the_suite_falls_back_to_full_mode(self) -> None:
        self._write(
            ".test_durations",
            json.dumps(
                {
                    "posthog/dags/tests/test_deletes.py::test_a": 900.0,
                    "posthog/dags/tests/test_backups.py::test_b": 100.0,
                }
            ),
        )
        selection = self._select(
            ["posthog/dags/deletes.py"],
            snob={"posthog/dags/deletes.py": ["posthog/dags/tests/test_deletes.py"]},
        )
        self.assertEqual(selection.mode, "full")

    def test_shard_count_grows_with_selected_duration_but_never_exceeds_test_files(self) -> None:
        for seconds, files, expected in (
            (0, 5, 1),
            (899, 5, 1),
            (901, 5, 2),
            (99999, 5, self.module.MAX_SHARDS),
            (99999, 1, 1),
            (901, 1, 1),
        ):
            with self.subTest(seconds=seconds, files=files):
                self.assertEqual(self.module.shard_count(seconds, files), expected)

    def test_selected_mode_reports_shards_from_durations(self) -> None:
        self._write(
            ".test_durations",
            json.dumps(
                {
                    "posthog/dags/tests/test_deletes.py::test_a": 1000.0,
                    "posthog/dags/tests/test_backups.py::test_b": 1000.0,
                    "products/web_analytics/dags/tests/test_cache_warming.py::test_c": 8000.0,
                }
            ),
        )
        selection = self._select(
            ["posthog/dags/deletes.py"],
            snob={
                "posthog/dags/deletes.py": [
                    "posthog/dags/tests/test_deletes.py",
                    "posthog/dags/tests/test_backups.py",
                ]
            },
        )
        self.assertEqual(selection.mode, "selected")
        self.assertEqual(selection.shards, 2)


if __name__ == "__main__":
    unittest.main()
