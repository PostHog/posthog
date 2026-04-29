"""Tests for the workflow_lint package.

These tests are fully isolated — each rule gets a passing fixture and a
failing fixture written to a tmp_path. Avoids touching the live repo state
except for one smoke test against ``.github/workflows/`` which exercises the
parser end-to-end.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hogli_commands.workflow_lint.check import CheckResult
from hogli_commands.workflow_lint.checks import CHECKS, get_check
from hogli_commands.workflow_lint.checks.dorny_negation import DornyNegationCheck
from hogli_commands.workflow_lint.checks.job_timeouts import JobTimeoutsCheck
from hogli_commands.workflow_lint.checks.pr_concurrency import PrConcurrencyCheck
from hogli_commands.workflow_lint.model import PR_TRIGGERS, Workflow, WorkflowParseError, WorkflowReader


def _write(dir_: Path, name: str, content: str) -> Path:
    path = dir_ / name
    path.write_text(textwrap.dedent(content).lstrip())
    return path


def _read_all(dir_: Path) -> list[Workflow]:
    return list(WorkflowReader(workflows_dir=dir_).read_all())


# ---------------------------------------------------------------------------
# WorkflowReader / model
# ---------------------------------------------------------------------------


class TestWorkflowReader:
    def test_normalizes_on_true_key(self, tmp_path: Path) -> None:
        # PyYAML parses `on:` as the boolean True. The reader must surface it
        # as the original triggers regardless.
        _write(
            tmp_path,
            "wf.yml",
            """
            name: My
            on:
              pull_request:
                branches: [master]
            jobs: {}
            """,
        )
        wf = next(WorkflowReader(workflows_dir=tmp_path).read_all())
        assert wf.is_pr_triggered, f"expected PR-trigger detection, got on={wf.on!r}"

    def test_quoted_on_string_also_works(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: My
            "on": pull_request
            jobs: {}
            """,
        )
        wf = next(WorkflowReader(workflows_dir=tmp_path).read_all())
        assert wf.is_pr_triggered

    def test_non_pr_trigger(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: My
            on: [push]
            jobs: {}
            """,
        )
        wf = next(WorkflowReader(workflows_dir=tmp_path).read_all())
        assert not wf.is_pr_triggered
        assert "push" not in PR_TRIGGERS  # sanity

    def test_reusable_call_job_marked(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: My
            on: [pull_request]
            jobs:
              call:
                uses: ./.github/workflows/other.yml
            """,
        )
        wf = next(WorkflowReader(workflows_dir=tmp_path).read_all())
        [job] = wf.jobs
        assert job.is_reusable_call
        assert job.uses == "./.github/workflows/other.yml"

    def test_parse_error_raises_typed(self, tmp_path: Path) -> None:
        bad = tmp_path / "wf.yml"
        bad.write_text("name: x\non: [\njobs: {}\n")
        with pytest.raises(WorkflowParseError) as exc:
            list(WorkflowReader(workflows_dir=tmp_path).read_all())
        assert exc.value.path == bad


# ---------------------------------------------------------------------------
# JobTimeoutsCheck
# ---------------------------------------------------------------------------


class TestJobTimeoutsCheck:
    def test_passes_when_all_jobs_have_timeout(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: My
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 10
                steps:
                  - run: echo ok
            """,
        )
        result = JobTimeoutsCheck().run(_read_all(tmp_path))
        assert result.issues == []

    def test_fails_when_timeout_missing(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: My
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - run: echo ok
            """,
        )
        result = JobTimeoutsCheck().run(_read_all(tmp_path))
        [issue] = result.issues
        assert issue.workflow == "wf.yml"
        assert issue.job == "build"
        assert "timeout-minutes" in issue.message

    def test_skips_reusable_call_jobs(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: My
            on: [pull_request]
            jobs:
              call:
                uses: ./.github/workflows/other.yml
            """,
        )
        result = JobTimeoutsCheck().run(_read_all(tmp_path))
        assert result.issues == []


# ---------------------------------------------------------------------------
# PrConcurrencyCheck
# ---------------------------------------------------------------------------


class TestPrConcurrencyCheck:
    def test_passes_with_concurrency(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "ci-foo.yml",
            """
            name: CI Foo
            on: [pull_request]
            concurrency:
              group: x
              cancel-in-progress: true
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: echo ok
            """,
        )
        assert PrConcurrencyCheck().run(_read_all(tmp_path)).issues == []

    def test_fails_without_concurrency(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "ci-foo.yml",
            """
            name: CI Foo
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: echo ok
            """,
        )
        [issue] = PrConcurrencyCheck().run(_read_all(tmp_path)).issues
        assert issue.workflow == "ci-foo.yml"
        assert "concurrency" in issue.message

    def test_skips_non_ci_prefix(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "shellcheck.yml",
            """
            name: Shell
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: echo ok
            """,
        )
        assert PrConcurrencyCheck().run(_read_all(tmp_path)).issues == []

    def test_skips_non_pr_trigger(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "ci-foo.yml",
            """
            name: CI Foo
            on: [push]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: echo ok
            """,
        )
        assert PrConcurrencyCheck().run(_read_all(tmp_path)).issues == []

    def test_skips_listed_filenames(self, tmp_path: Path) -> None:
        skip_name = next(iter(PrConcurrencyCheck.SKIP))
        _write(
            tmp_path,
            skip_name,
            """
            name: Skipped
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: echo ok
            """,
        )
        assert PrConcurrencyCheck().run(_read_all(tmp_path)).issues == []


# ---------------------------------------------------------------------------
# DornyNegationCheck
# ---------------------------------------------------------------------------


_DORNY_USES = "dorny/paths-filter@v3"


class TestDornyNegationCheck:
    def test_passes_without_dorny(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [pull_request]
            jobs:
              j:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: echo ok
            """,
        )
        assert DornyNegationCheck().run(_read_all(tmp_path)).issues == []

    def test_passes_with_positive_filters_only(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            f"""
            name: x
            on: [pull_request]
            jobs:
              j:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: {_DORNY_USES}
                    with:
                      filters: |
                        backend:
                          - posthog/**
            """,
        )
        assert DornyNegationCheck().run(_read_all(tmp_path)).issues == []

    def test_fails_on_negation_without_quantifier(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            f"""
            name: x
            on: [pull_request]
            jobs:
              j:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: {_DORNY_USES}
                    with:
                      filters: |
                        backend:
                          - posthog/**
                          - "!docs/**"
            """,
        )
        [issue] = DornyNegationCheck().run(_read_all(tmp_path)).issues
        assert "negation" in issue.message
        assert "predicate-quantifier" in issue.message

    def test_passes_with_every_quantifier(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            f"""
            name: x
            on: [pull_request]
            jobs:
              j:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: {_DORNY_USES}
                    with:
                      predicate-quantifier: 'every'
                      filters: |
                        backend:
                          - posthog/**
                          - "!docs/**"
            """,
        )
        assert DornyNegationCheck().run(_read_all(tmp_path)).issues == []


# ---------------------------------------------------------------------------
# Registry / smoke
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_check_ids_are_unique(self) -> None:
        ids = [c.id for c in CHECKS]
        assert len(ids) == len(set(ids)), f"duplicate check ids: {ids}"

    def test_get_check_finds_each(self) -> None:
        for c in CHECKS:
            assert get_check(c.id) is c

    def test_get_check_unknown_returns_none(self) -> None:
        assert get_check("not-a-real-id") is None

    def test_run_returns_check_result(self, tmp_path: Path) -> None:
        # A near-empty workflow set should not crash any check.
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [push]
            jobs: {}
            """,
        )
        wfs = _read_all(tmp_path)
        for check in CHECKS:
            result = check.run(wfs)
            assert isinstance(result, CheckResult)


class TestLiveTreeSmoke:
    """Smoke test against the live ``.github/workflows/`` tree.

    Asserts only that parsing does not raise — does NOT assert pass/fail of
    individual rules. This keeps the test stable as workflows evolve.
    """

    def test_live_tree_parses(self) -> None:
        from hogli.manifest import REPO_ROOT

        workflows_dir = REPO_ROOT / ".github" / "workflows"
        if not workflows_dir.exists():
            pytest.skip("no .github/workflows directory in this checkout")
        list(WorkflowReader(workflows_dir=workflows_dir).read_all())
