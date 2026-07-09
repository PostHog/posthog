"""The three v1 CI signal detectors, run over the curated GitHub read layer.

Each detector is a pure function of a ``CuratedGitHubSource`` plus thresholds and returns
``CISignalFinding`` objects — no emission, no Temporal, no Django here, so they're unit-testable
against a seeded warehouse. All three compose ``logic/queries/`` read modules rather than authoring
SQL inline: ``ci_broken_master`` / ``ci_duration_regression`` reuse ``query_workflow_health`` (the
same aggregate the MCP ``workflow_health`` tool returns) and ``ci_flaky_check`` reuses
``query_workflow_flakiness`` — so detection and the read surface can never disagree (SPEC §7).

Thresholds are conservative defaults — tuned to surface real, actionable conditions, not noise — and
are arguments so a team-level config can override them later without touching the queries.
"""

from datetime import UTC, datetime, timedelta

import structlog

from products.engineering_analytics.backend.facade.contracts import WorkflowHealthRunScope
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.workflow_flakiness import query_workflow_flakiness
from products.engineering_analytics.backend.logic.queries.workflow_health import query_workflow_health
from products.engineering_analytics.backend.logic.signals.contracts import (
    SOURCE_TYPE_BROKEN_MASTER,
    SOURCE_TYPE_DURATION_REGRESSION,
    SOURCE_TYPE_FLAKY_CHECK,
    CISignalFinding,
)
from products.signals.backend.contracts import SignalRemediation
from products.signals.backend.enums import ReportPriority

logger = structlog.get_logger(__name__)

# Flaky: a commit whose run failed then passed on re-run. Surface a workflow once it has flapped on at
# least this many distinct commits in the window — below that it's likely a genuine fix, not flake.
FLAKY_WINDOW_DAYS = 7
FLAKY_MIN_COMMITS = 3

# Broken master: the default branch is red. Short window (the branch's *current* state), enough runs to
# be real, success rate at or below the floor with the latest completed run failing.
BROKEN_MASTER_WINDOW_HOURS = 24
BROKEN_MASTER_MIN_RUNS = 3
BROKEN_MASTER_MAX_SUCCESS_RATE = 0.5
DEFAULT_BRANCHES = ("master", "main")

# Duration regression: p95 up meaningfully vs the immediately-preceding window of equal length. Both
# windows need enough runs for a stable percentile; require a relative *and* absolute jump so a 2s→4s
# blip on a fast check doesn't fire.
DURATION_WINDOW_DAYS = 7
DURATION_MIN_RUNS = 20
DURATION_MIN_PCT_INCREASE = 0.5
DURATION_MIN_ABS_INCREASE_SECONDS = 60.0


def detect_flaky_checks(
    curated: CuratedGitHubSource,
    *,
    window_days: int = FLAKY_WINDOW_DAYS,
    min_flaky_commits: int = FLAKY_MIN_COMMITS,
) -> list[CISignalFinding]:
    date_from = datetime.now(UTC) - timedelta(days=window_days)
    findings: list[CISignalFinding] = []
    for row in query_workflow_flakiness(curated=curated, date_from=date_from):
        if row.flaky_count < min_flaky_commits:
            continue
        repo = f"{row.repo_owner}/{row.repo_name}"
        shas = row.sample_head_shas
        findings.append(
            CISignalFinding(
                source_type=SOURCE_TYPE_FLAKY_CHECK,
                source_id=f"{repo}:{row.workflow_name}:flaky",
                description=(
                    f"CI workflow '{row.workflow_name}' is flaky on {repo}: {row.flaky_count} commit(s) in the "
                    f"last {window_days}d failed and then passed on a re-run of the same commit "
                    f"(out of {row.total_commits} commits the workflow ran on). Flaky required checks erode "
                    f"trust in CI and burn re-run minutes."
                ),
                weight=0.7,
                extra={
                    "repo_owner": row.repo_owner,
                    "repo_name": row.repo_name,
                    "workflow_name": row.workflow_name,
                    "flaky_count": row.flaky_count,
                    "total_commits": row.total_commits,
                    "window_days": window_days,
                    "sample_head_shas": shas,
                },
                remediation=SignalRemediation(
                    human=(
                        f"Identify the non-deterministic test(s) in the '{row.workflow_name}' workflow and "
                        f"quarantine or fix them so the check stops failing on unrelated commits."
                    ),
                    agent=(
                        f"Investigate the '{row.workflow_name}' workflow on {repo}. Pull the failing-then-passing "
                        f"logs for the sample commits ({', '.join(shas) or 'recent flaky runs'}), isolate the "
                        f"non-deterministic test(s), and open a PR that quarantines them via the repo's "
                        f".test_quarantine.json (see the hogli quarantine tooling) or fixes the root-cause flake. "
                        f"Do not mask it with a blanket retry."
                    ),
                    priority=ReportPriority.P2,
                ),
            )
        )
    return findings


def detect_broken_master(
    curated: CuratedGitHubSource,
    *,
    window_hours: int = BROKEN_MASTER_WINDOW_HOURS,
    min_runs: int = BROKEN_MASTER_MIN_RUNS,
    max_success_rate: float = BROKEN_MASTER_MAX_SUCCESS_RATE,
    default_branches: tuple[str, ...] = DEFAULT_BRANCHES,
) -> list[CISignalFinding]:
    now = datetime.now(UTC)
    date_from = now - timedelta(hours=window_hours)
    findings: list[CISignalFinding] = []
    for branch in default_branches:
        # A repo uses one default branch; the other query returns nothing rather than erroring.
        for item in query_workflow_health(
            curated=curated, date_from=date_from, date_to=now, branch=branch, run_scope=WorkflowHealthRunScope.ALL
        ):
            if item.run_count < min_runs or item.success_rate is None or not item.latest_run_failed:
                continue
            if item.success_rate > max_success_rate:
                continue
            repo = f"{item.repo.owner}/{item.repo.name}"
            latest_conclusion = item.latest_run_conclusion or "failure"
            findings.append(
                CISignalFinding(
                    source_type=SOURCE_TYPE_BROKEN_MASTER,
                    source_id=f"{repo}:{branch}:{item.workflow_name}:broken",
                    description=(
                        f"CI workflow '{item.workflow_name}' is failing on {branch} for {repo}: "
                        f"{item.success_rate:.0%} success over the last {window_hours}h ({item.run_count} runs), "
                        f"latest completed run '{latest_conclusion}'. The default branch is red — every PR "
                        f"branched from it inherits the failure."
                    ),
                    weight=0.85,
                    extra={
                        "repo_owner": item.repo.owner,
                        "repo_name": item.repo.name,
                        "workflow_name": item.workflow_name,
                        "branch": branch,
                        "success_rate": float(item.success_rate),
                        "run_count": int(item.run_count),
                        "latest_conclusion": latest_conclusion,
                        "window_hours": window_hours,
                    },
                    remediation=SignalRemediation(
                        human=(
                            f"Find the change that broke '{item.workflow_name}' on {branch} and revert it or land "
                            f"a fix."
                        ),
                        agent=(
                            f"The '{item.workflow_name}' workflow is failing on {branch} of {repo}. Pull the latest "
                            f"failing run's logs, bisect the recent merges to {branch} to find the breaking change, "
                            f"and open a revert or a targeted fix PR. Prioritize unblocking the branch."
                        ),
                        priority=ReportPriority.P1,
                    ),
                )
            )
    return findings


def detect_ci_duration_regressions(
    curated: CuratedGitHubSource,
    *,
    window_days: int = DURATION_WINDOW_DAYS,
    min_runs: int = DURATION_MIN_RUNS,
    min_pct_increase: float = DURATION_MIN_PCT_INCREASE,
    min_abs_increase_seconds: float = DURATION_MIN_ABS_INCREASE_SECONDS,
) -> list[CISignalFinding]:
    now = datetime.now(UTC)
    window = timedelta(days=window_days)
    current = {
        (i.repo.owner, i.repo.name, i.workflow_name): i
        for i in query_workflow_health(
            curated=curated, date_from=now - window, date_to=now, branch=None, run_scope=WorkflowHealthRunScope.ALL
        )
    }
    baseline = {
        (i.repo.owner, i.repo.name, i.workflow_name): i
        for i in query_workflow_health(
            curated=curated,
            date_from=now - 2 * window,
            date_to=now - window,
            branch=None,
            run_scope=WorkflowHealthRunScope.ALL,
        )
    }
    findings: list[CISignalFinding] = []
    for key, cur in current.items():
        base = baseline.get(key)
        if base is None or cur.run_count < min_runs or base.run_count < min_runs:
            continue
        if cur.p95_seconds is None or base.p95_seconds is None or base.p95_seconds <= 0:
            continue
        increase = cur.p95_seconds - base.p95_seconds
        pct_increase = increase / base.p95_seconds
        if pct_increase < min_pct_increase or increase < min_abs_increase_seconds:
            continue
        owner, repo_name, workflow_name = key
        repo = f"{owner}/{repo_name}"
        findings.append(
            CISignalFinding(
                source_type=SOURCE_TYPE_DURATION_REGRESSION,
                source_id=f"{repo}:{workflow_name}:duration",
                description=(
                    f"CI workflow '{workflow_name}' got slower on {repo}: p95 run time rose {pct_increase:.0%} "
                    f"({base.p95_seconds:.0f}s → {cur.p95_seconds:.0f}s) vs the prior {window_days}d. A slower "
                    f"check stretches every PR's time-to-green."
                ),
                weight=0.6,
                extra={
                    "repo_owner": owner,
                    "repo_name": repo_name,
                    "workflow_name": workflow_name,
                    "current_p95_seconds": float(cur.p95_seconds),
                    "baseline_p95_seconds": float(base.p95_seconds),
                    "pct_increase": float(pct_increase),
                    "current_p50_seconds": float(cur.p50_seconds) if cur.p50_seconds is not None else 0.0,
                    "baseline_p50_seconds": float(base.p50_seconds) if base.p50_seconds is not None else 0.0,
                    "window_days": window_days,
                },
                remediation=SignalRemediation(
                    human=(
                        f"Profile the '{workflow_name}' workflow and bring its p95 back toward the "
                        f"{base.p95_seconds:.0f}s baseline."
                    ),
                    agent=(
                        f"The '{workflow_name}' workflow's p95 duration regressed from {base.p95_seconds:.0f}s to "
                        f"{cur.p95_seconds:.0f}s over the last {window_days}d on {repo}. Compare a recent slow run "
                        f"against a baseline-window run, find what got slower (a new/slow test, a heavier job, lost "
                        f"caching), and propose the optimization."
                    ),
                    priority=ReportPriority.P3,
                ),
            )
        )
    return findings


def detect_all(curated: CuratedGitHubSource) -> list[CISignalFinding]:
    """Run every detector with default thresholds, isolating failures so one bad detector (or a
    transient query error) doesn't suppress the others' findings."""
    findings: list[CISignalFinding] = []
    for detector in (detect_flaky_checks, detect_broken_master, detect_ci_duration_regressions):
        try:
            findings.extend(detector(curated))
        except Exception:
            logger.exception("ci_signal_detector_failed", detector=detector.__name__)
    return findings
