from __future__ import annotations

import sys
import json
import tempfile
import importlib.util
from pathlib import Path
from types import ModuleType

import unittest

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
    junit_dir.mkdir(parents=True, exist_ok=True)
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
            failures, total, seen = verdict.parse_junit_failures(Path(root) / "missing")
            self.assertEqual(failures, [])
            self.assertEqual(total, 0)
            self.assertEqual(seen, 0)

    def test_extracts_failures_with_classname_mapping(self) -> None:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            junit_dir = Path(root)
            _write_junit(junit_dir, "junit-core.xml", JUNIT_FAILURE)
            failures, total, seen = verdict.parse_junit_failures(junit_dir)
            self.assertEqual(failures, ["posthog/api/test/test_foo.py"])
            self.assertEqual(total, 2)
            self.assertEqual(seen, 1)

    def test_finds_testcases_in_nested_testsuites(self) -> None:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            junit_dir = Path(root)
            _write_junit(junit_dir, "junit.xml", JUNIT_NESTED_FAILURE)
            failures, total, _seen = verdict.parse_junit_failures(junit_dir)
            self.assertEqual(failures, ["posthog/api/test/test_nested.py"])
            self.assertEqual(total, 1)

    def test_skips_malformed_xml(self) -> None:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            junit_dir = Path(root)
            _write_junit(junit_dir, "good.xml", JUNIT_ALL_PASS)
            _write_junit(junit_dir, "bad.xml", "<not valid xml")
            failures, total, seen = verdict.parse_junit_failures(junit_dir)
            self.assertEqual(failures, [])
            self.assertEqual(total, 1)
            self.assertEqual(seen, 2)


class TestComputeVerdict(unittest.TestCase):
    def _run(
        self,
        *,
        combined_tests: list[str],
        full_run_reasons: list[str] | None = None,
        junit_files: list[tuple[str, str]] | None = None,
    ) -> dict[str, object]:
        verdict = _load_verdict_module()
        with tempfile.TemporaryDirectory() as root:
            tmp_path = Path(root)
            selection_path = tmp_path / "selection.json"
            _write_selection(selection_path, combined_tests=combined_tests, full_run_reasons=full_run_reasons)

            junit_dir = tmp_path / "junit"
            for name, content in junit_files or []:
                _write_junit(junit_dir, name, content)

            return verdict.compute_verdict(selection_path, junit_dir)

    def test_unknown_when_no_junit_xmls_found(self) -> None:
        result = self._run(combined_tests=["posthog/api/test/test_foo.py"])
        self.assertEqual(result["backend_conclusion"], "unknown")
        self.assertIsNone(result["recall"])
        self.assertEqual(result["caught"], [])
        self.assertEqual(result["missed"], [])
        self.assertEqual(result["junit_xml_files_seen"], 0)

    def test_success_when_all_pass(self) -> None:
        result = self._run(
            combined_tests=["posthog/api/test/test_bar.py"],
            junit_files=[("junit.xml", JUNIT_ALL_PASS)],
        )
        self.assertEqual(result["backend_conclusion"], "success")
        self.assertIsNone(result["recall"])
        self.assertEqual(result["failure_count"], 0)

    def test_failure_caught_when_in_selection(self) -> None:
        result = self._run(
            combined_tests=["posthog/api/test/test_foo.py", "posthog/api/test/test_other.py"],
            junit_files=[("junit.xml", JUNIT_FAILURE)],
        )
        self.assertEqual(result["backend_conclusion"], "failure")
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["caught"], ["posthog/api/test/test_foo.py"])
        self.assertEqual(result["missed"], [])

    def test_failure_missed_when_not_in_selection(self) -> None:
        result = self._run(
            combined_tests=["posthog/api/test/test_unrelated.py"],
            junit_files=[("junit.xml", JUNIT_FAILURE)],
        )
        self.assertEqual(result["backend_conclusion"], "failure")
        self.assertEqual(result["recall"], 0.0)
        self.assertEqual(result["caught"], [])
        self.assertEqual(result["missed"], ["posthog/api/test/test_foo.py"])

    def test_full_run_treats_failures_as_caught(self) -> None:
        # Selection's combined.tests does NOT include the failing file, but
        # full_run_reasons indicates the selector opted into running everything.
        result = self._run(
            combined_tests=["posthog/api/test/test_unrelated.py"],
            full_run_reasons=["conftest.py matches full-run pattern"],
            junit_files=[("junit.xml", JUNIT_FAILURE)],
        )
        self.assertEqual(result["backend_conclusion"], "failure")
        self.assertTrue(result["full_run_triggered"])
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["caught"], ["posthog/api/test/test_foo.py"])
        self.assertEqual(result["missed"], [])


if __name__ == "__main__":
    unittest.main()
