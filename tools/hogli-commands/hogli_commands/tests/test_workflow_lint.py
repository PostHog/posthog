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

from hogli_commands.workflow_lint.check import CheckResult, WorkflowCheck
from hogli_commands.workflow_lint.checks import CHECKS, _build_lookup, get_check
from hogli_commands.workflow_lint.checks.cache_writes import (
    _can_run_on_branch_ref,
    _is_gated,
    _push_trigger_is_default_only,
    _violation_kind,
    _write_kind,
)
from hogli_commands.workflow_lint.checks.checkout_full_depth import CheckoutFullDepthCheck
from hogli_commands.workflow_lint.checks.dorny_negation import DornyNegationCheck
from hogli_commands.workflow_lint.checks.job_timeouts import JobTimeoutsCheck
from hogli_commands.workflow_lint.checks.pr_concurrency import PrConcurrencyCheck
from hogli_commands.workflow_lint.checks.required_gates import RequiredGateCheck
from hogli_commands.workflow_lint.checks.semgrep_services_coverage import SemgrepServicesCoverageCheck
from hogli_commands.workflow_lint.model import PR_TRIGGERS, Workflow, WorkflowParseError, read_workflows


def _write(dir_: Path, name: str, content: str) -> Path:
    path = dir_ / name
    path.write_text(textwrap.dedent(content).lstrip())
    return path


def _read_all(dir_: Path) -> list[Workflow]:
    return list(read_workflows(dir_))


# ---------------------------------------------------------------------------
# WorkflowReader / model
# ---------------------------------------------------------------------------


class TestReadWorkflows:
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
        wf = next(read_workflows(tmp_path))
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
        wf = next(read_workflows(tmp_path))
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
        wf = next(read_workflows(tmp_path))
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
        wf = next(read_workflows(tmp_path))
        [job] = wf.jobs
        assert job.is_reusable_call
        assert job.uses == "./.github/workflows/other.yml"

    def test_parse_error_raises_typed(self, tmp_path: Path) -> None:
        bad = tmp_path / "wf.yml"
        bad.write_text("name: x\non: [\njobs: {}\n")
        with pytest.raises(WorkflowParseError) as exc:
            list(read_workflows(tmp_path))
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

    def test_string_concurrency_counts_as_present(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "ci-foo.yml",
            """
            name: CI Foo
            on: [pull_request]
            concurrency: "${{ github.workflow }}-${{ github.head_ref || github.ref }}"
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

    def test_fails_with_run_id_fallback(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "ci-foo.yml",
            """
            name: CI Foo
            on: [pull_request]
            concurrency:
              group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}
              cancel-in-progress: true
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
        assert "github.run_id" in issue.message
        assert "github.ref" in issue.message

    def test_passes_with_job_level_concurrency_on_all_jobs(self, tmp_path: Path) -> None:
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
                concurrency:
                  group: build-${{ github.head_ref || github.ref }}
                  cancel-in-progress: true
                steps:
                  - run: echo ok
              test:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                concurrency:
                  group: test-${{ github.head_ref || github.ref }}
                  cancel-in-progress: true
                steps:
                  - run: echo ok
            """,
        )
        assert PrConcurrencyCheck().run(_read_all(tmp_path)).issues == []

    def test_passes_with_partial_job_level_concurrency(self, tmp_path: Path) -> None:
        """Workflows managing concurrency at job-level for some (heavy) jobs pass."""
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
                concurrency:
                  group: build-${{ github.head_ref || github.ref }}
                  cancel-in-progress: true
                steps:
                  - run: echo ok
              lightweight:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: echo ok
            """,
        )
        assert PrConcurrencyCheck().run(_read_all(tmp_path)).issues == []

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
# SemgrepServicesCoverageCheck
# ---------------------------------------------------------------------------


class TestSemgrepServicesCoverageCheck:
    def test_passes_when_all_services_are_covered(self, tmp_path: Path) -> None:
        repo_root = tmp_path
        (repo_root / "services" / "api").mkdir(parents=True)
        (repo_root / "services" / "worker").mkdir()
        workflows_dir = repo_root / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        _write(
            workflows_dir,
            "ci-security.yaml",
            """
            name: Security
            on: [pull_request]
            jobs:
              semgrep-python:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: |
                      semgrep scan services/api/
                      semgrep scan services/worker/
              semgrep-js:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: echo ok
            """,
        )
        assert SemgrepServicesCoverageCheck(repo_root=repo_root).run(_read_all(workflows_dir)).issues == []

    def test_fails_when_a_service_is_missing(self, tmp_path: Path) -> None:
        repo_root = tmp_path
        (repo_root / "services" / "api").mkdir(parents=True)
        (repo_root / "services" / "worker").mkdir()
        workflows_dir = repo_root / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        _write(
            workflows_dir,
            "ci-security.yaml",
            """
            name: Security
            on: [pull_request]
            jobs:
              semgrep-python:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: semgrep scan services/api/
              semgrep-js:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: echo ok
            """,
        )
        [issue] = SemgrepServicesCoverageCheck(repo_root=repo_root).run(_read_all(workflows_dir)).issues
        assert issue.workflow == "ci-security.yaml"
        assert "services/worker/" in issue.message


# ---------------------------------------------------------------------------
# CheckoutFullDepthCheck
# ---------------------------------------------------------------------------


class TestCheckoutFullDepthCheck:
    def test_passes_default_checkout(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: actions/checkout@v6
            """,
        )
        assert CheckoutFullDepthCheck().run(_read_all(tmp_path)).issues == []

    def test_passes_blobless_full_depth_checkout(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: actions/checkout@v6
                    with:
                      fetch-depth: 0
                      filter: blob:none
            """,
        )
        assert CheckoutFullDepthCheck().run(_read_all(tmp_path)).issues == []

    def test_passes_sparse_full_depth_checkout(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: actions/checkout@v6
                    with:
                      fetch-depth: 0
                      sparse-checkout: |
                        rust/
                        proto/
            """,
        )
        assert CheckoutFullDepthCheck().run(_read_all(tmp_path)).issues == []

    def test_passes_explicit_allow_marker_with_reason(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [push]
            jobs:
              mirror:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  # hogli-lint: allow-full-depth-checkout -- mirror needs full blobs
                  - name: Checkout mirror
                    uses: "actions/checkout@v6"
                    with:
                      fetch-depth: 0
            """,
        )
        assert CheckoutFullDepthCheck().run(_read_all(tmp_path)).issues == []

    def test_fails_full_depth_without_optimization(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: actions/checkout@v6
                    with:
                      fetch-depth: "0"
            """,
        )
        [issue] = CheckoutFullDepthCheck().run(_read_all(tmp_path)).issues
        assert issue.workflow == "wf.yml"
        assert issue.job == "build"
        assert "fetch-depth: 0" in issue.message

    def test_allow_marker_requires_reason(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [push]
            jobs:
              mirror:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  # hogli-lint: allow-full-depth-checkout
                  - uses: actions/checkout@v6
                    with:
                      fetch-depth: 0
            """,
        )
        [issue] = CheckoutFullDepthCheck().run(_read_all(tmp_path)).issues
        assert "allow-full-depth-checkout" in issue.message

    def test_allow_marker_does_not_apply_to_previous_checkout(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [push]
            jobs:
              mirror:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: "actions/checkout@v6"
                    with:
                      fetch-depth: 0

                  # hogli-lint: allow-full-depth-checkout -- mirror needs full blobs
                  - uses: actions/checkout@v6
                    with:
                      fetch-depth: 0
            """,
        )
        [issue] = CheckoutFullDepthCheck().run(_read_all(tmp_path)).issues
        assert issue.step == "step[0]"
        assert "fetch-depth: 0" in issue.message

    def test_passes_filter_combined_with_sparse_checkout(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "wf.yml",
            """
            name: x
            on: [pull_request]
            jobs:
              build:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: actions/checkout@v6
                    with:
                      fetch-depth: 0
                      filter: blob:none
                      sparse-checkout: |
                        rust/
            """,
        )
        assert CheckoutFullDepthCheck().run(_read_all(tmp_path)).issues == []


# ---------------------------------------------------------------------------
# CacheWriteGateCheck
# ---------------------------------------------------------------------------


def _cache_step(if_cond: str | None = None, key: str | None = None) -> dict:
    step: dict = {"uses": "actions/cache@v4"}
    if if_cond is not None:
        step["if"] = if_cond
    if key is not None:
        step["with"] = {"key": key}
    return step


class TestCacheWriteGateCheck:
    @pytest.mark.parametrize(
        "uses, with_, expected",
        [
            ("actions/cache@v4", None, "cache (combined)"),
            ("actions/cache/save@v4", None, "cache/save"),
            ("actions/cache/restore@v4", None, None),
            ("actions/setup-node@v4", {"cache": "pnpm"}, "setup auto-cache"),
            ("actions/setup-node@v4", {}, None),
            ("actions/checkout@v4", None, None),
        ],
    )
    def test_write_kind(self, uses: str, with_: dict | None, expected: str | None) -> None:
        step: dict = {"uses": uses}
        if with_ is not None:
            step["with"] = with_
        assert _write_kind(step) == expected

    @pytest.mark.parametrize(
        "if_cond, gated",
        [
            ("github.ref == 'refs/heads/master'", True),
            ("github.ref == 'refs/heads/main'", True),
            ("github.ref_name == 'master'", True),
            # AND only narrows — still pinned to master
            ("github.ref == 'refs/heads/master' && github.event_name == 'push'", True),
            # both OR alternatives pin to a default branch
            ("github.ref == 'refs/heads/master' || github.ref == 'refs/heads/main'", True),
            # the nit: negation runs on branches, not master
            ("github.ref != 'refs/heads/master'", False),
            # the nit: OR re-opens the write to PRs
            ("github.ref == 'refs/heads/master' || github.event_name == 'pull_request'", False),
            ("", False),
        ],
    )
    def test_is_gated(self, if_cond: str, gated: bool) -> None:
        assert _is_gated({"if": if_cond}, push_is_default_only=True) is gated

    @pytest.mark.parametrize("push_is_default_only, gated", [(True, True), (False, False)])
    def test_event_name_push_gate_depends_on_push_scope(self, push_is_default_only: bool, gated: bool) -> None:
        # `event_name == 'push'` only pins to master when push can't fire on a branch
        assert _is_gated({"if": "github.event_name == 'push'"}, push_is_default_only) is gated

    @pytest.mark.parametrize(
        "step, expected",
        [
            (_cache_step(), "cache (combined)"),
            (_cache_step(if_cond="github.ref == 'refs/heads/master'"), None),
            (_cache_step(key="pnpm-${{ github.event.pull_request.number }}"), None),
            # the nit: previously these slipped through as gated
            (_cache_step(if_cond="github.ref != 'refs/heads/master'"), "cache (combined)"),
            (
                _cache_step(if_cond="github.ref == 'refs/heads/master' || github.event_name == 'pull_request'"),
                "cache (combined)",
            ),
        ],
    )
    def test_violation_kind(self, step: dict, expected: str | None) -> None:
        assert _violation_kind(step, push_is_default_only=True) == expected

    def test_setup_autocache_cannot_be_gated(self) -> None:
        # gating the whole setup step would skip the toolchain on PRs, so the
        # auto-save is always a violation regardless of `if:`
        step = {"uses": "actions/setup-node@v4", "if": "github.ref == 'refs/heads/master'", "with": {"cache": "pnpm"}}
        assert _violation_kind(step, push_is_default_only=True) == "setup auto-cache"

    @pytest.mark.parametrize(
        "on, can_run_on_branch",
        [
            ("pull_request", True),
            (["pull_request", "push"], True),
            ({"push": None}, True),  # bare push fires on every branch
            ({"push": {"branches": ["master"]}}, False),
            ({"push": {"tags": ["*"]}}, False),  # release pushes
            ("workflow_dispatch", False),
            ("schedule", False),
        ],
    )
    def test_can_run_on_branch_ref(self, on: object, can_run_on_branch: bool) -> None:
        assert _can_run_on_branch_ref(on) is can_run_on_branch

    @pytest.mark.parametrize(
        "on, default_only",
        [
            ("pull_request", True),  # no push trigger
            ({"push": {"branches": ["master"]}}, True),
            ({"push": None}, False),  # bare push leaks to branches
            ({"push": {"branches": ["master", "feature"]}}, False),
        ],
    )
    def test_push_trigger_is_default_only(self, on: object, default_only: bool) -> None:
        assert _push_trigger_is_default_only(on) is default_only


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

    def test_get_check_accepts_prefix(self) -> None:
        for c in CHECKS:
            prefix = c.id.split("-", 1)[0]
            assert get_check(prefix) is c
            assert get_check(prefix.lower()) is c

    def test_get_check_unknown_returns_none(self) -> None:
        assert get_check("not-a-real-id") is None
        assert get_check("WF999") is None

    def test_build_lookup_rejects_duplicate_prefix(self) -> None:
        class _A(WorkflowCheck):
            id = "WF001-alpha"
            label = "a"
            description = "a"

            def run(self, workflows: list[Workflow]) -> CheckResult:
                return CheckResult()

        class _B(WorkflowCheck):
            id = "WF001-beta"
            label = "b"
            description = "b"

            def run(self, workflows: list[Workflow]) -> CheckResult:
                return CheckResult()

        with pytest.raises(ValueError, match="WF001"):
            _build_lookup([_A(), _B()])

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


# The shape these fixtures guard against: a `changes` detector cleared with a bare
# `== "failure"`, then its outputs read to decide "nothing to test". Those outputs
# are empty on a cancelled job, so the gate exits 0 green with no tests run.
def _gate(body: str, condition: str = "always()") -> str:
    return f"""
    name: ci-thing
    on: pull_request
    jobs:
      changes:
        timeout-minutes: 5
        steps:
          - run: echo detect
      build:
        timeout-minutes: 5
        steps:
          - run: echo build
      thing_tests:
        name: Thing Tests Pass
        needs: [changes, build]
        timeout-minutes: 5
        if: {condition}
        steps:
          - run: |
{textwrap.indent(textwrap.dedent(body).strip(), " " * 14)}
"""


SAFE_BODY = """
    if [[ "${{ needs.changes.result }}" != "success" && "${{ needs.changes.result }}" != "skipped" ]]; then
      exit 1
    fi
    if [[ "${{ needs.changes.outputs.thing }}" != "true" ]]; then
      exit 0
    fi
    if [[ "${{ needs.build.result }}" != "success" && "${{ needs.build.result }}" != "skipped" ]]; then
      exit 1
    fi
"""

# One dependency allowlisted, one denylisted — the shape a global scan for
# result words calls clean.
MIXED_BODY = SAFE_BODY.replace(
    """if [[ "${{ needs.changes.result }}" != "success" && "${{ needs.changes.result }}" != "skipped" ]]; then""",
    """if [[ "${{ needs.changes.result }}" == "failure" ]]; then""",
)

# Two dependencies denylisted while the rest are allowlisted.
TWO_BAD_BODY = MIXED_BODY.replace(
    """if [[ "${{ needs.changes.outputs.thing }}" != "true" ]]; then""",
    """if [[ "${{ needs.affected.result }}" == "failure" ]]; then
      exit 1
    fi
    if [[ "${{ needs.changes.outputs.thing }}" != "true" ]]; then""",
)

# ci-backend.yml / ci-mcp.yml route every result through one shell function, so
# no literal sits next to `needs.<dep>.result`.
HELPER_BODY = """
    check() {
      if [[ "$2" != "success" && "$2" != "skipped" ]]; then
        exit 1
      fi
    }
    check "Changes" "${{ needs.changes.result }}"
    check "Build" "${{ needs.build.result }}"
"""

UNSAFE_HELPER_BODY = HELPER_BODY.replace(
    """if [[ "$2" != "success" && "$2" != "skipped" ]]; then""",
    """if [[ "$2" == "failure" ]]; then""",
)

# ci-agents.yml maps results into env and loops over the variable names.
ENV_LOOP_GATE = """
    name: ci-thing
    on: pull_request
    jobs:
      build:
        timeout-minutes: 5
        steps:
          - run: echo build
      thing_tests:
        name: Thing Tests Pass
        needs: [build]
        timeout-minutes: 5
        if: always()
        steps:
          - name: Check outcomes
            env:
              BUILD: ${{ needs.build.result }}
            run: |
              for var in BUILD; do
                val="${!var}"
                if [[ "$val" != "success" && "$val" != "skipped" ]]; then
                  exit 1
                fi
              done
"""


# A gate whose display name doesn't end in "Pass", so only structural detection finds it.
def _off_convention_gate(marker: str = "") -> str:
    yaml_ = _gate(MIXED_BODY).replace("Thing Tests Pass", "Thing decision")
    if marker:
        yaml_ = yaml_.replace("      thing_tests:", f"      # {marker}\n      thing_tests:")
    return yaml_


class TestRequiredGateCheck:
    @pytest.mark.parametrize(
        "content",
        [_gate(SAFE_BODY), _gate(HELPER_BODY), ENV_LOOP_GATE],
        ids=["inline-allowlist", "shared-helper", "env-block-loop"],
    )
    def test_passes_when_every_dependency_is_allowlisted(self, tmp_path: Path, content: str) -> None:
        _write(tmp_path, "ci-thing.yml", content)
        assert RequiredGateCheck().run(_read_all(tmp_path)).issues == []

    @pytest.mark.parametrize(
        "body,expected_deps",
        [(MIXED_BODY, ["changes"]), (TWO_BAD_BODY, ["affected", "changes"])],
        ids=["one-denylisted-among-allowlisted", "two-denylisted-among-allowlisted"],
    )
    def test_flags_exactly_the_denylisted_dependencies(
        self, tmp_path: Path, body: str, expected_deps: list[str]
    ) -> None:
        _write(tmp_path, "ci-thing.yml", _gate(body))
        issues = RequiredGateCheck().run(_read_all(tmp_path)).issues
        assert sorted(i.message.split("'")[1] for i in issues) == expected_deps

    @pytest.mark.parametrize(
        "content,expected",
        [
            (_gate(SAFE_BODY, condition="${{ !cancelled() }}"), "always()"),
            (_gate(UNSAFE_HELPER_BODY), "never tests a result"),
        ],
        ids=["gate-must-always-run", "indirect-gate-without-allowlist"],
    )
    def test_flags_unsafe_gate(self, tmp_path: Path, content: str, expected: str) -> None:
        _write(tmp_path, "ci-thing.yml", content)
        issues = RequiredGateCheck().run(_read_all(tmp_path)).issues
        assert len(issues) == 1
        assert expected in issues[0].message

    def test_ignores_non_gate_jobs(self, tmp_path: Path) -> None:
        # Worker jobs *should* use !cancelled() so they stop when superseded;
        # only the collate gate is held to always().
        _write(
            tmp_path,
            "ci-thing.yml",
            """
            name: ci-thing
            on: pull_request
            jobs:
              shards:
                timeout-minutes: 5
                if: ${{ !cancelled() }}
                steps:
                  - run: echo test
            """,
        )
        assert RequiredGateCheck().run(_read_all(tmp_path)).issues == []

    # A gate named off-convention is still a gate, so detection can't key on the
    # name alone.
    def test_finds_gate_not_named_pass(self, tmp_path: Path) -> None:
        _write(tmp_path, "ci-thing.yml", _off_convention_gate())
        issues = RequiredGateCheck().run(_read_all(tmp_path)).issues
        assert [i.message.split("'")[1] for i in issues] == ["changes"]

    @pytest.mark.parametrize(
        "marker,exempted",
        [
            ("hogli-lint: not-a-required-gate", False),
            ("hogli-lint: not-a-required-gate — decides a side effect, emits no check", True),
        ],
        ids=["without-reason", "with-reason"],
    )
    def test_allow_marker_needs_a_reason_to_exempt(self, tmp_path: Path, marker: str, exempted: bool) -> None:
        _write(tmp_path, "ci-thing.yml", _off_convention_gate(marker))
        assert (RequiredGateCheck().run(_read_all(tmp_path)).issues == []) is exempted


class TestLiveTreeSmoke:
    """Smoke test against the live ``.github/workflows/`` tree.

    Asserts that parsing and every check execute without raising — does NOT
    assert pass/fail of individual rules. This keeps the test stable as
    workflows evolve while still catching crashes that fixtures miss.
    """

    def test_live_tree_parses_and_checks_run(self) -> None:
        from hogli.manifest import REPO_ROOT

        workflows_dir = REPO_ROOT / ".github" / "workflows"
        if not workflows_dir.exists():
            pytest.skip("no .github/workflows directory in this checkout")
        workflows = list(read_workflows(workflows_dir))
        for check in CHECKS:
            assert isinstance(check.run(workflows), CheckResult)
