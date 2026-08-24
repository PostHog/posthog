from __future__ import annotations

import os
import sys
import json
import tempfile
import importlib.util
from pathlib import Path
from types import ModuleType

import unittest
from unittest.mock import patch

from parameterized import parameterized

SCRIPT_PATH = Path(__file__).with_name("test_selection_verdict.py")


def _load_verdict_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_selection_verdict", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_junit(junit_dir: Path, name: str, content: str) -> None:
    (junit_dir / name).parent.mkdir(parents=True, exist_ok=True)
    (junit_dir / name).write_text(content)


def _write_selection(path: Path, *, combined_tests: list[str], full_run_reasons: list[str] | None = None) -> None:
    selection = {
        "combined": {"tests": combined_tests, "count": len(combined_tests)},
        "ast": {"tests": combined_tests, "full_run_reasons": full_run_reasons or []},
        "snob": {"tests": [], "count": 0, "status": "ok"},
    }
    path.write_text(json.dumps(selection))


JUNIT_FAILURE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite name="pytest" tests="2" failures="1" errors="0">
        <testcase classname="posthog.api.test.test_foo.TestFoo" name="test_pass" time="0.1"/>
        <testcase classname="posthog.api.test.test_foo.TestFoo" name="test_fail" time="0.2">
            <failure message="assert False">Traceback...</failure>
        </testcase>
    </testsuite>
</testsuites>
"""

JUNIT_NESTED_FAILURE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite name="outer" tests="1" failures="1">
        <testsuite name="inner" tests="1" failures="1">
            <testcase classname="posthog.api.test.test_nested.TestNested" name="test_x">
                <error message="boom">Traceback...</error>
            </testcase>
        </testsuite>
    </testsuite>
</testsuites>
"""

JUNIT_ALL_PASS = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite name="pytest" tests="1" failures="0">
        <testcase classname="posthog.api.test.test_bar.TestBar" name="test_ok"/>
    </testsuite>
</testsuites>
"""

JUNIT_PRODUCT_FAILURE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite name="pytest" tests="1" failures="1">
        <testcase classname="products.error_tracking.backend.tests.test_issues.TestIssues" name="test_fail">
            <failure message="assert False">Traceback...</failure>
        </testcase>
    </testsuite>
</testsuites>
"""

DJANGO_XML = "junit-results-backend-core-1/junit-core.xml"
PRODUCT_XML = "product-junit-results-0/junit-product-error_tracking.xml"


class TestClassnameToFilepath(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "standard_django_class",
                "posthog.api.test.test_web_experiment.TestWebExperiment",
                "posthog/api/test/test_web_experiment.py",
            ),
            (
                "function_test_no_class",
                "posthog.api.test.test_module",
                "posthog/api/test/test_module.py",
            ),
            (
                "ee_path",
                "ee.clickhouse.queries.test.test_cohort.TestCohort",
                "ee/clickhouse/queries/test/test_cohort.py",
            ),
            (
                "products_path",
                "products.feature_flags.backend.test.test_api.TestFlags",
                "products/feature_flags/backend/test/test_api.py",
            ),
        ]
    )
    def test_maps_classname(self, _name: str, classname: str, expected: str) -> None:
        verdict = _load_verdict_module()
        self.assertEqual(verdict.classname_to_filepath(classname), expected)


class TestParseJunitFailures(unittest.TestCase):
    def test_returns_zero_when_dir_missing(self) -> None:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            results = verdict.parse_junit_failures(Path(root) / "missing")
            self.assertEqual(results.failed_test_files, [])
            self.assertEqual(results.total_tests_run, 0)
            self.assertEqual(results.xml_files_seen, 0)

    def test_extracts_failures_with_classname_mapping(self) -> None:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            junit_dir = Path(root)
            _write_junit(junit_dir, "junit-core.xml", JUNIT_FAILURE)
            results = verdict.parse_junit_failures(junit_dir)
            self.assertEqual(results.failed_test_files, ["posthog/api/test/test_foo.py"])
            self.assertEqual(results.total_tests_run, 2)
            self.assertEqual(results.xml_files_seen, 1)

    def test_finds_testcases_in_nested_testsuites(self) -> None:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            junit_dir = Path(root)
            _write_junit(junit_dir, "junit.xml", JUNIT_NESTED_FAILURE)
            results = verdict.parse_junit_failures(junit_dir)
            self.assertEqual(results.failed_test_files, ["posthog/api/test/test_nested.py"])
            self.assertEqual(results.total_tests_run, 1)

    def test_skips_malformed_xml(self) -> None:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            junit_dir = Path(root)
            _write_junit(junit_dir, "good.xml", JUNIT_ALL_PASS)
            _write_junit(junit_dir, "bad.xml", "<not valid xml")
            results = verdict.parse_junit_failures(junit_dir)
            self.assertEqual(results.failed_test_files, [])
            self.assertEqual(results.total_tests_run, 1)
            self.assertEqual(results.xml_files_seen, 2)


class TestJunitSide(unittest.TestCase):
    @parameterized.expand(
        [
            ("django_artifact", DJANGO_XML, "django"),
            ("product_artifact", PRODUCT_XML, "products"),
            ("product_file_without_artifact_dir", "junit-product-error_tracking.xml", "products"),
            ("django_file_without_artifact_dir", "junit-core.xml", "django"),
        ]
    )
    def test_side_from_artifact_layout(self, _name: str, relative: str, expected: str) -> None:
        verdict = _load_verdict_module()
        junit_dir = Path("/tmp/junit-results")
        self.assertEqual(verdict.junit_side(junit_dir / relative, junit_dir), expected)

    def test_side_filter_hides_other_matrix(self) -> None:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            junit_dir = Path(root)
            _write_junit(junit_dir, DJANGO_XML, JUNIT_FAILURE)
            _write_junit(junit_dir, PRODUCT_XML, JUNIT_PRODUCT_FAILURE)
            results = verdict.parse_junit_failures(junit_dir, side="products")
            self.assertEqual(results.failed_test_files, ["products/error_tracking/backend/tests/test_issues.py"])
            self.assertEqual(results.total_tests_run, 1)
            self.assertEqual(results.xml_files_seen, 1)


class TestComputeVerdict(unittest.TestCase):
    def _run(
        self,
        *,
        combined_tests: list[str],
        full_run_reasons: list[str] | None = None,
        junit_files: list[tuple[str, str]] | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            tmp_path = Path(root)
            selection_path = tmp_path / "selection.json"
            _write_selection(selection_path, combined_tests=combined_tests, full_run_reasons=full_run_reasons)

            junit_dir = tmp_path / "junit"
            for name, content in junit_files or []:
                _write_junit(junit_dir, name, content)

            with patch.dict(os.environ, env or {}, clear=False):
                return verdict.compute_verdict(selection_path, junit_dir)

    def test_unknown_when_no_junit_xmls_found(self) -> None:
        result = self._run(combined_tests=["posthog/api/test/test_foo.py"])
        for side in ("django", "products"):
            self.assertEqual(result[side]["conclusion"], "unknown")
            self.assertIsNone(result[side]["recall"])
            self.assertEqual(result[side]["caught"], [])
            self.assertEqual(result[side]["missed"], [])
            self.assertEqual(result[side]["junit_xml_files_seen"], 0)

    def test_success_when_all_pass(self) -> None:
        result = self._run(
            combined_tests=["posthog/api/test/test_bar.py"],
            junit_files=[(DJANGO_XML, JUNIT_ALL_PASS)],
        )
        self.assertEqual(result["django"]["conclusion"], "success")
        self.assertIsNone(result["django"]["recall"])
        self.assertEqual(result["django"]["failure_count"], 0)
        self.assertEqual(result["products"]["conclusion"], "unknown")

    @parameterized.expand(
        [
            (
                "caught",
                ["posthog/api/test/test_foo.py", "posthog/api/test/test_other.py"],
                1.0,
                ["posthog/api/test/test_foo.py"],
                [],
            ),
            ("missed", ["posthog/api/test/test_unrelated.py"], 0.0, [], ["posthog/api/test/test_foo.py"]),
        ]
    )
    def test_django_failure_scored_against_selection(
        self, _name: str, combined_tests: list[str], recall: float, caught: list[str], missed: list[str]
    ) -> None:
        result = self._run(combined_tests=combined_tests, junit_files=[(DJANGO_XML, JUNIT_FAILURE)])
        self.assertEqual(result["django"]["conclusion"], "failure")
        self.assertEqual(result["django"]["recall"], recall)
        self.assertEqual(result["django"]["caught"], caught)
        self.assertEqual(result["django"]["missed"], missed)

    def test_full_run_treats_failures_as_caught(self) -> None:
        # Selection's combined.tests does NOT include the failing files, but
        # full_run_reasons indicates the selector opted into running everything.
        result = self._run(
            combined_tests=["posthog/api/test/test_unrelated.py"],
            full_run_reasons=["conftest.py matches full-run pattern"],
            junit_files=[(DJANGO_XML, JUNIT_FAILURE), (PRODUCT_XML, JUNIT_PRODUCT_FAILURE)],
        )
        self.assertTrue(result["full_run_triggered"])
        self.assertEqual(result["django"]["recall"], 1.0)
        self.assertEqual(result["django"]["missed"], [])
        self.assertEqual(result["products"]["recall"], 1.0)
        self.assertEqual(result["products"]["product_recall"], 1.0)
        self.assertEqual(result["products"]["missed_products"], [])

    @parameterized.expand(
        [
            ("file_selected", ["products/error_tracking/backend/tests/test_issues.py"], 1.0, 1.0, []),
            ("other_file_same_product", ["products/error_tracking/backend/tests/test_other.py"], 0.0, 1.0, []),
            ("other_product", ["products/tasks/backend/tests/test_other.py"], 0.0, 0.0, ["error_tracking"]),
        ]
    )
    def test_product_failure_scored_by_file_and_by_product(
        self, _name: str, combined_tests: list[str], recall: float, product_recall: float, missed_products: list[str]
    ) -> None:
        result = self._run(combined_tests=combined_tests, junit_files=[(PRODUCT_XML, JUNIT_PRODUCT_FAILURE)])
        products = result["products"]
        self.assertEqual(products["conclusion"], "failure")
        self.assertEqual(products["recall"], recall)
        self.assertEqual(products["product_recall"], product_recall)
        self.assertEqual(products["failed_products"], ["error_tracking"])
        self.assertEqual(products["missed_products"], missed_products)

    def test_product_failure_does_not_count_against_django_side(self) -> None:
        result = self._run(
            combined_tests=["posthog/api/test/test_bar.py"],
            junit_files=[(DJANGO_XML, JUNIT_ALL_PASS), (PRODUCT_XML, JUNIT_PRODUCT_FAILURE)],
        )
        self.assertEqual(result["django"]["conclusion"], "success")
        self.assertEqual(result["products"]["conclusion"], "failure")

    def test_records_selection_context_from_env(self) -> None:
        result = self._run(
            combined_tests=[],
            env={
                "SELECTION_MODE": "full",
                "SELECTION_SKIP_REASON": "untrusted",
                "RUN_LEGACY_REASON": "contract_cascade",
            },
        )
        self.assertEqual(result["selection_mode"], "full")
        self.assertEqual(result["selection_skip_reason"], "untrusted")
        self.assertEqual(result["run_legacy_reason"], "contract_cascade")


if __name__ == "__main__":
    unittest.main()
