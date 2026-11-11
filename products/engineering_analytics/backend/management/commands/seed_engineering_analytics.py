"""Seed a team's warehouse with the checked-in GitHub fixture plus synthetic demo rows, behind a
seeded GitHub source. Local dev only.

Timestamps are rebased so the newest row lands at now, because the queries window on the server
clock and an old snapshot would render empty. ``--keep-dates`` skips the rebase. Re-running replaces
the seed source's tables and never touches a table that another source owns.

    python manage.py seed_engineering_analytics --team-id 1 [--prefix <prefix>] [--keep-dates]
"""

import csv
import json
import zlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.logs.logs34 import TABLE_NAME as LOGS_LOCAL_TABLE
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.storage import object_storage

from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME
from products.engineering_analytics.backend.logic.queries._test_spans import PYTEST_CI_SERVICE_NAME
from products.engineering_analytics.backend.logic.sources import (
    DEPLOYMENT_STATUSES_SCHEMA,
    DEPLOYMENTS_SCHEMA,
    ISSUE_EVENTS_SCHEMA,
    PULL_REQUESTS_SCHEMA,
    REVIEWS_SCHEMA,
    TEAM_MEMBERS_SCHEMA,
    TRUNK_QUARANTINED_TESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
)
from products.engineering_analytics.backend.logic.views.pull_requests import KNOWN_BOT_HANDLES
from products.engineering_analytics.backend.logic.views.source_schema import (
    DEPLOYMENT_STATUSES_COLUMNS,
    DEPLOYMENTS_COLUMNS,
    ISSUE_EVENTS_COLUMNS,
    PULL_REQUESTS_COLUMNS,
    REVIEWS_COLUMNS,
    TEAM_MEMBERS_COLUMNS,
    TRUNK_QUARANTINED_TESTS_COLUMNS,
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.warehouse_sources.backend.facade.api import validate_source_prefix
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
    get_or_create_datawarehouse_credential,
)
from products.warehouse_sources.backend.facade.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.facade.types import (
    DataWarehouseTableFormat,
    ExternalDataSourceStatus,
    ExternalDataSourceType,
)

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures"

PR_DATE_FIELDS = ("created_at", "updated_at", "merged_at", "closed_at")
RUN_DATE_FIELDS = ("created_at", "run_started_at", "updated_at")

SEED_SOURCE_ID = "engineering_analytics_seed"
TRUNK_SEED_SOURCE_ID = "engineering_analytics_seed_trunkio"
# Must match the fixtures' repository.full_name.
SEED_REPOSITORY = "PostHog/posthog"
# A non-empty default prefix makes the seed exercise per-team table name resolution.
DEFAULT_PREFIX = "eng_analytics_seed"


def _flatten_pr(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        # An older fixture can lack columns that were added to the snapshot later.
        **{key: pr.get(key) for key in PULL_REQUESTS_COLUMNS if key not in ("user", "head", "base", "labels", "draft")},
        "draft": int(bool(pr["draft"])),
        "user": json.dumps(pr["user"]),
        "head": json.dumps(pr["head"]),
        "base": json.dumps(pr["base"]),
        "labels": json.dumps(pr["labels"]),
    }


def _synthetic_repo_id(full_name: str) -> int:
    return zlib.crc32(full_name.encode())


def _synthetic_event(head_branch: str) -> str:
    pushed = head_branch in ("master", "main") or head_branch.startswith("trunk-merge/")
    return "push" if pushed else "pull_request"


def _flatten_run(run: dict[str, Any]) -> dict[str, Any]:
    json_keys = ("repository", "pull_requests", "head_commit", "actor")
    scalar_keys = [key for key in WORKFLOW_RUNS_COLUMNS if key not in json_keys]
    # A run is attributed to a PR only when the PR's base repo id equals the run's own (see
    # logic/views/workflow_runs). Rows that carry neither id get one synthetic id on both ends,
    # because without it they would attribute nothing.
    repository = {**run["repository"]}
    repository.setdefault("id", _synthetic_repo_id(repository["full_name"]))
    associations = [
        {**pr, "base": {"repo": {"id": pr.get("base", {}).get("repo", {}).get("id", repository["id"])}}}
        for pr in run.get("pull_requests") or []
    ]
    return {
        **{key: run.get(key) for key in scalar_keys},
        "workflow_id": run.get("workflow_id") or zlib.crc32(str(run.get("name") or "").encode()),
        "event": run.get("event") or _synthetic_event(str(run.get("head_branch") or "")),
        "repository": json.dumps(repository),
        "pull_requests": json.dumps(associations),
        "head_commit": json.dumps(run.get("head_commit", {})),
        # A missing actor lands as '{}', which the merge-queue check reads as "not the queue bot".
        "actor": json.dumps(run.get("actor") or {}),
    }


_JOB_NAMES = ("build", "test", "lint", "e2e")
_FAILING_CONCLUSIONS = ("failure", "timed_out")
_RUNNER_LABELS = (
    '["depot-ubuntu-22.04-16"]',
    '["depot-ubuntu-22.04-8"]',
    '["depot-ubuntu-22.04-4"]',
    '["ubuntu-latest"]',
)


_TS_FMT = "%Y-%m-%d %H:%M:%S"

_DEMO_BRANCH = "demo/multi-push-progression"

# Each entry is (job name, wave, shard count).
_DEMO_JOB_SHAPES: dict[str, tuple[tuple[str, int, int], ...]] = {
    "Backend CI": (
        ("Detect changes", 0, 1),
        ("Django tests – Core", 1, 12),
        ("Django tests – Temporal", 1, 4),
        ("Product tests", 1, 6),
        ("Check migrations", 1, 1),
        ("Async migrations", 1, 1),
        ("Django Tests Pass", 2, 1),
    ),
    "Frontend CI": (
        ("Detect changes", 0, 1),
        ("Jest tests", 1, 8),
        ("Typecheck", 1, 1),
        ("Lint", 1, 1),
        ("Frontend Tests Pass", 2, 1),
    ),
    "E2E Tests": (
        ("Build image", 0, 1),
        ("Playwright", 1, 6),
        ("Upload report", 2, 1),
    ),
    "Rust CI": (
        ("Build", 0, 1),
        ("Test", 1, 4),
        ("Clippy", 1, 1),
    ),
    "Storybook": (
        ("Build Storybook", 0, 1),
        ("Visual regression", 1, 10),
        ("Upload snapshots", 2, 1),
    ),
}


_STEP_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
_MAIN_STEP = "Run"
# Step name and its share of the job's wall-clock. The shares must sum to 1.
_STEP_SHAPE: tuple[tuple[str, float], ...] = (
    ("Set up job", 0.04),
    ("Checkout", 0.06),
    ("Restore cache", 0.1),
    (_MAIN_STEP, 0.7),
    ("Post Restore cache", 0.05),
    ("Post Checkout", 0.03),
    ("Complete job", 0.02),
)


def _shaped_steps(job_name: str, job_start: datetime, job_end: datetime, conclusion: str | None) -> str:
    """A job's steps as GitHub's JSON. A failed job fails on its main step, and an unfinished job is still on it."""
    seconds = (job_end - job_start).total_seconds()
    steps: list[dict[str, Any]] = []
    step_start = job_start
    main_reached = False
    for number, (name, share) in enumerate(_STEP_SHAPE, start=1):
        is_main = name == _MAIN_STEP
        step_end = step_start + timedelta(seconds=seconds * share)
        step: dict[str, Any] = {
            "number": number,
            "name": f"Run {job_name}" if is_main else name,
            "status": "completed",
            "conclusion": "success",
            "started_at": step_start.strftime(_STEP_TS_FMT),
            "completed_at": step_end.strftime(_STEP_TS_FMT),
        }
        if conclusion is None and is_main:
            step.update(status="in_progress", conclusion=None, completed_at=None)
        elif conclusion is None and main_reached:
            step.update(status="queued", conclusion=None, started_at=None, completed_at=None)
        elif conclusion in _FAILING_CONCLUSIONS and is_main:
            step["conclusion"] = "failure"
        steps.append(step)
        main_reached = main_reached or is_main
        step_start = step_end
    return json.dumps(steps)


def _shaped_jobs(
    run: dict[str, Any], shape: tuple[tuple[str, int, int], ...], run_start: datetime, window: float
) -> list[dict[str, Any]]:
    completed = run.get("status") == "completed"
    failing = run.get("conclusion") in _FAILING_CONCLUSIONS
    waves = max(wave for _name, wave, _shards in shape) + 1
    segment = window / waves
    widest_name, _wave, widest_shards = max(shape, key=lambda entry: entry[2])

    jobs: list[dict[str, Any]] = []
    for name, wave, shards in shape:
        for shard in range(shards):
            index = len(jobs)
            # An unfinished run is still on its last wave.
            finished = completed or wave < waves - 1
            conclusion = "success" if finished else None
            if failing and (name, shard) == (widest_name, widest_shards // 2):
                conclusion = run["conclusion"]
            job_start = run_start + timedelta(seconds=wave * segment)
            job_end = job_start + timedelta(seconds=segment * (0.55 + ((index * 37) % 10) / 22))
            started_at = job_start.strftime(_TS_FMT)
            jobs.append(
                {
                    "id": run["id"] * 100 + index,
                    "run_id": run["id"],
                    "run_attempt": run.get("run_attempt", 1),
                    "name": f"{name} ({shard + 1}/{shards})" if shards > 1 else name,
                    "workflow_name": run.get("name"),
                    "status": "completed" if finished else "in_progress",
                    "conclusion": conclusion,
                    "head_sha": run.get("head_sha"),
                    "head_branch": run.get("head_branch"),
                    "labels": _RUNNER_LABELS[index % len(_RUNNER_LABELS)],
                    "runner_name": f"runner-{index + 1}",
                    "runner_group_name": "depot",
                    "created_at": started_at,
                    "started_at": started_at,
                    "completed_at": job_end.strftime(_TS_FMT) if finished else None,
                    "steps": _shaped_steps(name, job_start, job_end, conclusion),
                }
            )
    return jobs


def _synthesize_jobs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for run in runs:
        completed = run.get("status") == "completed"
        run_conclusion = run.get("conclusion")
        count = (run["id"] % 3) + 2

        run_start: datetime | None = None
        run_end: datetime | None = None
        try:
            run_start = datetime.strptime(run["run_started_at"], _TS_FMT)
            run_end = datetime.strptime(run["updated_at"], _TS_FMT)
        except (KeyError, TypeError, ValueError):
            pass
        window = (run_end - run_start).total_seconds() if run_start and run_end and run_end > run_start else 0.0
        segment = window / count if window else 0.0

        shape = _DEMO_JOB_SHAPES.get(run.get("name") or "") if run.get("head_branch") == _DEMO_BRANCH else None
        if shape and run_start and window:
            jobs.extend(_shaped_jobs(run, shape, run_start, window))
            continue

        for idx in range(count):
            is_last = idx == count - 1
            # A failing run fails on its last job.
            conclusion = run_conclusion if (is_last and run_conclusion in _FAILING_CONCLUSIONS) else None
            if completed and conclusion is None:
                conclusion = "success"

            job_start = run_start + timedelta(seconds=idx * segment) if run_start else None
            job_end = run_start + timedelta(seconds=(idx + 1) * segment) if (run_start and completed) else None
            started_at = job_start.strftime(_TS_FMT) if job_start else None
            completed_at = job_end.strftime(_TS_FMT) if job_end else None

            jobs.append(
                {
                    "id": run["id"] * 10 + idx,
                    "run_id": run["id"],
                    "run_attempt": run.get("run_attempt", 1),
                    "name": _JOB_NAMES[idx % len(_JOB_NAMES)],
                    "workflow_name": run.get("name"),
                    "status": run.get("status"),
                    "conclusion": conclusion,
                    "head_sha": run.get("head_sha"),
                    "head_branch": run.get("head_branch"),
                    "labels": _RUNNER_LABELS[idx % len(_RUNNER_LABELS)],
                    "runner_name": f"runner-{idx + 1}",
                    "runner_group_name": "depot",
                    "created_at": started_at,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "steps": (
                        _shaped_steps(
                            _JOB_NAMES[idx % len(_JOB_NAMES)], job_start, job_start + timedelta(seconds=segment), None
                        )
                        if job_start and segment and not completed
                        else "[]"
                    ),
                }
            )
    return jobs


# The fixture has no pull request that re-runs many workflows across pushes, so the seed adds one.
_DEMO_PR_NUMBER = 99001
# Each workflow's conclusion on the 4 pushes, oldest first. None means the run is still in progress.
_DEMO_MATRIX: dict[str, list[str | None]] = {
    "Backend CI": ["failure", "failure", "success", "success"],
    "Frontend CI": ["failure", "success", "success", "success"],
    "Rust CI": ["success", "failure", "success", "success"],
    "E2E Tests": ["failure", "failure", "failure", "success"],
    "Storybook": ["success", "success", "success", "success"],
    "Lint": ["success", "success", "success", "success"],
    "Migrations": ["success", "success", "failure", "success"],
    "MCP CI": ["success", "success", "success", None],
    "Docs": ["success", "success", "success", "success"],
    "Security": ["timed_out", "failure", "success", "success"],
}


def _fixture_anchor(prs: list[dict[str, Any]], runs: list[dict[str, Any]]) -> datetime:
    # The rebase moves the newest row to now, so synthetic rows are dated relative to this anchor.
    newest = max(
        datetime.fromisoformat(row[field])
        for row, fields in [*((pr, PR_DATE_FIELDS) for pr in prs), *((run, RUN_DATE_FIELDS) for run in runs)]
        for field in fields
        if row[field] is not None
    )
    return newest + timedelta(hours=1)


_MERGE_SPREAD_DAYS = 14

_MASTER_WORKFLOWS = ("Backend CI", "Frontend CI", "Rust CI", "E2E Tests", "Lint", "Storybook")
# Same window as the merge spread, because a day with merges and no job cost charts as $0 per merge.
_MASTER_DAYS = _MERGE_SPREAD_DAYS
_MASTER_COMMITS_PER_DAY = 18
# GitHub's association lists every PR in the fork network that shares the run's head SHA, so each
# seeded master push carries a fork's PR that the read layer must not attribute it to (SPEC §6).
_FORK_REPO_ID = 778592526
_FORK_PR_NUMBER = 1379


def _demo_master_commits(anchor: datetime, merged_prs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    def iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    total = _MASTER_DAYS * _MASTER_COMMITS_PER_DAY
    spacing_minutes = _MASTER_DAYS * 24 * 60 // total
    demo_runs: list[dict[str, Any]] = []
    for commit_index in range(total):
        age_minutes = (total - 1 - commit_index) * spacing_minutes + (commit_index * 37) % 90
        commit_time = anchor - timedelta(minutes=age_minutes)
        sha = f"aa57e2{commit_index:04d}" + "e" * 30
        # Cite a seeded PR so that the run's PR link resolves.
        pr = merged_prs[commit_index % len(merged_prs)] if merged_prs else None
        subject = f"feat: seeded master commit {commit_index}"
        if pr is not None:
            # The first commit to cite a PR becomes its merge commit, so that run resolves through
            # the merge_commit_sha join. Later citations resolve through the (#NNNN) message
            # suffix. Some join-backed commits drop the suffix, so only the join can attribute them.
            joins_via_merge_sha = not pr.get("merge_commit_sha")
            if joins_via_merge_sha:
                pr["merge_commit_sha"] = sha
            if not (joins_via_merge_sha and commit_index % 10 == 3):
                subject += f" (#{pr['number']})"
        red_commit = commit_index % 9 == 4
        cancelled_commit = commit_index % 17 == 9
        for wf_index, workflow in enumerate(_MASTER_WORKFLOWS):
            running = commit_index >= total - 2 and wf_index == len(_MASTER_WORKFLOWS) - 1
            if running:
                conclusion = None
            elif cancelled_commit:
                conclusion = "cancelled"
            elif red_commit and wf_index == 2:
                conclusion = "failure"
            else:
                conclusion = "success"
            start = commit_time + timedelta(minutes=wf_index)
            duration = timedelta(minutes=4 + (commit_index * 7 + wf_index * 11) % 48)
            demo_runs.append(
                {
                    "id": 9_800_000_000 + commit_index * 10 + wf_index,
                    "name": workflow,
                    "head_sha": sha,
                    "head_branch": "master",
                    "status": "in_progress" if running else "completed",
                    "conclusion": conclusion,
                    "created_at": iso(start),
                    "run_started_at": iso(start),
                    # The job synthesis reads updated_at as the run's end, so a running run needs one too.
                    "updated_at": iso(start + duration / 2) if running else iso(start + duration),
                    "run_attempt": 1,
                    "repository": {"full_name": "PostHog/posthog"},
                    "pull_requests": [{"number": _FORK_PR_NUMBER, "base": {"repo": {"id": _FORK_REPO_ID}}}],
                    "head_commit": {
                        "message": subject,
                        "author": {"name": "PostHog Bot", "email": "bot@posthog.com"},
                    },
                }
            )
    return demo_runs


# The fixture has no merge-queue gate runs, so the seed adds them. A gate run resolves to its PR
# through the `trunk-merge/pr-<n>/` branch name, and only when the queue's bot is the actor.
_GATE_WORKFLOWS = ("Backend CI", "Frontend CI")
_GATE_LEAD = timedelta(minutes=34)
_GATE_RETRY_EVERY_N = 4


def _gate_runs(prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    runs: list[dict[str, Any]] = []
    merged = [pr for pr in prs if pr.get("merged_at")]
    for index, pr in enumerate(merged):
        merged_at = datetime.fromisoformat(pr["merged_at"])
        attempts = 2 if index % _GATE_RETRY_EVERY_N == 0 else 1
        for attempt in range(attempts):
            start = merged_at - _GATE_LEAD * (attempts - attempt)
            failed = attempt < attempts - 1
            for wf_index, workflow in enumerate(_GATE_WORKFLOWS):
                runs.append(
                    {
                        "id": 9_900_000_000 + index * 100 + attempt * 10 + wf_index,
                        "name": workflow,
                        "head_sha": f"9a7e{index:05d}{attempt}{wf_index}" + "d" * 29,
                        "head_branch": f"trunk-merge/pr-{pr['number']}/{index:08d}-{attempt}",
                        "status": "completed",
                        "conclusion": "failure" if failed and wf_index == 0 else "success",
                        "created_at": iso(start),
                        "run_started_at": iso(start),
                        "updated_at": iso(start + timedelta(minutes=18 + wf_index * 5)),
                        "run_attempt": 1,
                        "repository": {"full_name": "PostHog/posthog"},
                        "pull_requests": [],
                        "actor": {"login": "trunk-io[bot]", "avatar_url": ""},
                        "head_commit": {
                            "message": f"{pr.get('title') or 'change'} (#{pr['number']})",
                            "author": {"name": "Trunk", "email": "bot@trunk.io"},
                        },
                    }
                )
    return runs


def _spread_merges(prs: list[dict[str, Any]], anchor: datetime) -> None:
    # The snapshot's merges cluster on the capture day, which collapses every merge trend into one
    # bucket. created_at is derived backwards from the new merged_at, because clamping merged_at
    # against the snapshot's created_at would leave the merges on the capture day.
    span_hours = _MERGE_SPREAD_DAYS * 24
    merged = [pr for pr in prs if pr.get("merged_at")]
    for index, pr in enumerate(merged):
        merged_at = anchor - timedelta(hours=(index * 11) % span_hours, minutes=(index * 13) % 60)
        open_hours = 3 + (index * 17) % 45
        if index % 9 == 4:
            open_hours += 24 * (2 + index % 5)
        pr["merged_at"] = merged_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        pr["created_at"] = (merged_at - timedelta(hours=open_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


# GitHub caps the issue-events history walk, so a real sync covers a bounded recent window. The seed
# lands events only inside this window, which leaves older merges with no observed transition.
_ISSUE_EVENTS_WINDOW_DAYS = 10


_DEPLOYS_EVERY_N_MERGES = 3
_DEPLOY_LAG = timedelta(minutes=9)
_DEPLOY_DURATION = timedelta(minutes=12)
_PRODUCTION_ENVIRONMENTS = ("prod-us", "prod-eu")


@frozen
class _SeededDeployments:
    deployments: list[dict[str, Any]]
    statuses: list[dict[str, Any]]


def _deployment_rows(prs: list[dict[str, Any]]) -> _SeededDeployments:
    merged = sorted((pr for pr in prs if pr.get("merged_at")), key=lambda pr: pr["merged_at"])
    deployments: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for index, pr in enumerate(merged[::_DEPLOYS_EVERY_N_MERGES]):
        requested = datetime.fromisoformat(pr["merged_at"]) + _DEPLOY_LAG
        for offset, environment in enumerate(_PRODUCTION_ENVIRONMENTS):
            deployment_id = 8_000_000_000 + index * 10 + offset
            stagger = timedelta(minutes=offset)
            deployments.append(
                {
                    "id": deployment_id,
                    "sha": pr.get("merge_commit_sha") or "",
                    "ref": pr.get("merge_commit_sha") or "",
                    "task": "deploy",
                    "environment": environment,
                    "original_environment": environment,
                    "description": None,
                    "creator": None,
                    "payload": None,
                    # False as in real synced rows, so the read must detect production another way.
                    "production_environment": False,
                    "transient_environment": False,
                    "created_at": (requested + stagger).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "updated_at": (requested + stagger).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
            live_at = (requested + _DEPLOY_DURATION + stagger).strftime("%Y-%m-%dT%H:%M:%SZ")
            statuses.append(
                {
                    "id": deployment_id + 5,
                    "deployment_id": deployment_id,
                    "state": "success",
                    "creator": None,
                    "description": None,
                    "environment": environment,
                    "target_url": None,
                    "log_url": None,
                    "environment_url": None,
                    "created_at": live_at,
                    "updated_at": live_at,
                }
            )
    return _SeededDeployments(deployments=deployments, statuses=statuses)


def _issue_event_rows(prs: list[dict[str, Any]], anchor: datetime) -> list[dict[str, Any]]:
    window_start = anchor - timedelta(days=_ISSUE_EVENTS_WINDOW_DAYS)
    rows: list[dict[str, Any]] = []

    def add(event_id: int, event: str, pr: dict[str, Any], at: datetime) -> None:
        if at < window_start:
            return
        rows.append(
            {
                "id": event_id,
                "event": event,
                "actor": json.dumps({"login": (pr.get("user") or {}).get("login") or "", "avatar_url": ""}),
                "issue": json.dumps({"number": pr["number"]}),
                "requested_team": None,
                "created_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    merged = [pr for pr in prs if pr.get("merged_at")]
    if merged:
        # A non-transition event at the window start fixes the left edge of the observed range.
        add(7_000_000_000, "labeled", merged[0], window_start)
    for index, pr in enumerate(merged):
        created = datetime.fromisoformat(pr["created_at"])
        merged_at = datetime.fromisoformat(pr["merged_at"])
        life = merged_at - created
        base_id = 7_000_000_100 + index * 10
        # The never-drafted fallback needs the merge inside the observed window, so every merge lands its event.
        add(base_id, "merged", pr, merged_at)
        if index % 3 == 0:
            # Opening a PR as a draft emits no event.
            add(base_id + 1, "ready_for_review", pr, created + life * 0.4)
        elif index % 3 == 1:
            add(base_id + 1, "convert_to_draft", pr, created + life * 0.3)
            add(base_id + 2, "ready_for_review", pr, created + life * 0.75)
    demo_pr = next((pr for pr in prs if pr.get("number") == _DEMO_PR_NUMBER), None)
    if demo_pr is not None:
        created = datetime.fromisoformat(demo_pr["created_at"])
        add(7_000_000_050, "convert_to_draft", demo_pr, created + timedelta(hours=6))
        add(7_000_000_051, "ready_for_review", demo_pr, created + timedelta(hours=30))
    return rows


_MERGED_REVIEW_PLANS: tuple[tuple[tuple[str, float], ...], ...] = (
    (("CHANGES_REQUESTED", 0.35), ("APPROVED", 0.7)),
    (("APPROVED", 0.5),),
    (("COMMENTED", 0.3), ("APPROVED", 0.85)),
    (("APPROVED", 0.9),),
)
_OPEN_REVIEW_PLANS: tuple[tuple[tuple[str, float], ...], ...] = (
    (("CHANGES_REQUESTED", 0.6),),
    (("COMMENTED", 0.5),),
    (),
)


def _review_rows(prs: list[dict[str, Any]], anchor: datetime) -> list[dict[str, Any]]:
    logins = sorted({(pr.get("user") or {}).get("login") or "" for pr in prs} - {""})
    reviewers = [login for login in logins if not login.endswith("[bot]") and login not in KNOWN_BOT_HANDLES]
    rows: list[dict[str, Any]] = []
    for index, pr in enumerate(prs):
        if not pr.get("created_at") or not reviewers:
            continue
        created = datetime.fromisoformat(pr["created_at"])
        if pr.get("merged_at"):
            end = datetime.fromisoformat(pr["merged_at"])
            plan = _MERGED_REVIEW_PLANS[index % len(_MERGED_REVIEW_PLANS)]
        elif pr.get("state") == "open" and not pr.get("draft"):
            end = anchor
            plan = _OPEN_REVIEW_PLANS[index % len(_OPEN_REVIEW_PLANS)]
        else:
            continue
        author = (pr.get("user") or {}).get("login") or ""
        reviewer = reviewers[index % len(reviewers)]
        if reviewer == author:
            reviewer = reviewers[(index + 1) % len(reviewers)]
        for step, (state, fraction) in enumerate(plan):
            rows.append(
                {
                    "id": 6_000_000_000 + index * 10 + step,
                    "pr_number": pr["number"],
                    "user": json.dumps({"login": reviewer, "avatar_url": ""}),
                    "state": state,
                    "commit_id": "",
                    "submitted_at": (created + (end - created) * fraction).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
    return rows


def _demo_multi_push(
    prs: list[dict[str, Any]], runs: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    anchor = _fixture_anchor(prs, runs)
    push_shas = [f"demo00{k + 1}" + "f" * 33 for k in range(4)]
    workflows = list(_DEMO_MATRIX.keys())

    def iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    demo_runs: list[dict[str, Any]] = []
    for push_index in range(4):
        push_time = anchor - timedelta(days=3 - push_index)
        for wf_index, workflow in enumerate(workflows):
            conclusion = _DEMO_MATRIX[workflow][push_index]
            running = conclusion is None
            start = push_time + timedelta(minutes=2 * wf_index)
            end = start + timedelta(minutes=5 + (wf_index % 6) * 4)
            demo_runs.append(
                {
                    "id": 9_900_000_000 + push_index * 100 + wf_index,
                    "name": workflow,
                    "head_sha": push_shas[push_index],
                    "head_branch": _DEMO_BRANCH,
                    "status": "in_progress" if running else "completed",
                    "conclusion": None if running else conclusion,
                    "created_at": iso(start),
                    "run_started_at": iso(start),
                    "updated_at": iso(start + (end - start) / 2) if running else iso(end),
                    "run_attempt": 1,
                    "repository": {"full_name": "PostHog/posthog"},
                    "pull_requests": [{"number": _DEMO_PR_NUMBER}],
                }
            )

    demo_pr = {
        "id": 9_900_100_001,
        "number": _DEMO_PR_NUMBER,
        "title": "demo: multi-push CI progression (seeded)",
        "state": "open",
        "draft": False,
        "created_at": iso(anchor - timedelta(days=3)),
        "updated_at": iso(anchor),
        "merged_at": None,
        "closed_at": None,
        "user": {"login": "webjunkie", "avatar_url": ""},
        "head": {"sha": push_shas[3]},
        "base": {"repo": {"full_name": "PostHog/posthog", "default_branch": "master"}},
        "labels": ["demo"],
    }
    return demo_pr, demo_runs


# Re-seeding deletes the spans whose trace id carries this prefix, and no others.
_SPAN_TRACE_PREFIX = "engseed"
# A current window and a prior window of equal length.
_SPAN_DAYS = 28

# (owner_team, module_dir, [(TestClass, test_name, prior_daily, current_daily)]).
# prior_daily and current_daily are the spans per day in each half of the window.
# The slugs are the owner slugs in the repository's ownership files as of July 2026.
_SPAN_TEAMS: list[tuple[str, str, list[tuple[str, str, int, int]]]] = [
    (
        "team-replay",
        "posthog/session_recordings/test",
        [
            ("TestSessionRecordings", "test_snapshot_batching", 2, 5),
            ("TestRecordingPlaylists", "test_playlist_counts_converge", 1, 3),
            ("TestRetentionSweeper", "test_ttl_boundary_day", 0, 2),
        ],
    ),
    (
        "batch-exports",
        "products/batch_exports/backend/tests",
        [
            ("TestSnowflakeExport", "test_incremental_primary_key_resume", 4, 4),
            ("TestBigQueryExport", "test_backfill_window_overlap", 3, 3),
            ("TestTemporalWorkflows", "test_teardown_cancellation", 2, 3),
            ("TestS3Export", "test_multipart_retry", 2, 2),
        ],
    ),
    (
        "team-ingestion",
        "posthog/models/test",
        [
            ("TestPersonMerges", "test_concurrent_merge_ordering", 4, 1),
            ("TestKafkaConsumer", "test_rebalance_offset_commit", 3, 1),
        ],
    ),
    (
        "conversations",
        "products/conversations/backend/api/tests",
        [
            ("TestTicketRouting", "test_assignment_race", 0, 4),
        ],
    ),
    (
        "team-experiments",
        "products/experiments/backend/test",
        [
            ("TestExperimentResults", "test_bayesian_interval_rounding", 3, 0),
            ("TestFeatureFlagRollout", "test_variant_bucketing_stability", 2, 0),
        ],
    ),
    (
        "team-error-tracking",
        "products/error_tracking/backend/tests",
        [
            ("TestIssueGrouping", "test_fingerprint_collision", 0, 3),
        ],
    ),
    (
        "team-data-tools",
        "posthog/hogql/test",
        [
            ("TestHogQLParser", "test_lambda_scope_resolution", 2, 3),
            ("TestHogQLPrinter", "test_materialized_column_rewrite", 1, 1),
        ],
    ),
    (
        "team-workflows",
        "products/cdp/backend/test",
        [
            ("TestHogFunctions", "test_retry_backoff_jitter", 2, 3),
            ("TestDestinationFilters", "test_event_property_globs", 1, 1),
        ],
    ),
    (
        "team-product-analytics",
        "posthog/hogql_queries/insights/trends/test",
        [
            ("TestTrendsQueryRunner", "test_interval_boundary_timezone", 3, 2),
            ("TestFunnelCorrelation", "test_person_property_breakdown", 1, 1),
        ],
    ),
    (
        "team-platform-features",
        "products/access_control/backend/tests",
        [
            ("TestAccessControl", "test_role_membership_cache_invalidation", 2, 1),
            ("TestOrgInvites", "test_invite_expiry_race", 1, 1),
        ],
    ),
    (
        "team-ai-observability",
        "products/ai_observability/backend/test",
        [
            ("TestGenerationCosts", "test_cost_property_rollup", 2, 1),
            ("TestTraceIngestion", "test_span_attribute_truncation", 1, 1),
        ],
    ),
    (
        "team-surveys",
        "products/surveys/backend/api/test",
        [
            ("TestSurveyTargeting", "test_adaptive_sampling_rate", 2, 1),
        ],
    ),
    (
        "team-warehouse-sources",
        "products/warehouse_sources/backend/tests",
        [
            ("TestStripeSource", "test_incremental_cursor_persistence", 2, 2),
            ("TestSourceSchemaSync", "test_nullable_json_columns", 1, 1),
        ],
    ),
    (
        "team-analytics-platform",
        "products/dashboards/backend/test",
        [
            ("TestDashboardTiles", "test_tile_refresh_debounce", 2, 2),
            ("TestAlertChecks", "test_threshold_hysteresis", 1, 1),
        ],
    ),
    (
        "team-web-analytics",
        "products/web_analytics/backend/test",
        [
            ("TestWebOverview", "test_preaggregated_table_parity", 2, 2),
            ("TestChannelType", "test_utm_priority_order", 1, 0),
        ],
    ),
    (
        "team-feature-flags",
        "products/feature_flags/backend/test",
        [
            ("TestFlagMatching", "test_local_evaluation_consistency", 2, 2),
            ("TestFlagDependencies", "test_cohort_flag_cycle", 1, 0),
        ],
    ),
    (
        "team-self-driving",
        "products/signals/backend/test",
        [
            ("TestSignalEmission", "test_dedupe_window_replay", 1, 2),
            ("TestInboxRouting", "test_scout_finding_grouping", 0, 1),
        ],
    ),
    (
        "team-agents",
        "products/agent_platform/backend/tests",
        [
            ("TestAgentRuns", "test_tool_call_stream_resume", 1, 2),
        ],
    ),
    (
        "team-managed-warehouse",
        "products/data_warehouse/backend/tests",
        [
            ("TestSavedQueryMaterialization", "test_incremental_refresh_watermark", 1, 2),
        ],
    ),
    (
        "team-posthog-code",
        "products/tasks/backend/tests",
        [
            ("TestTaskSandbox", "test_worktree_cleanup_on_cancel", 1, 2),
        ],
    ),
    (
        "team-devex",
        "products/engineering_analytics/backend/tests",
        [
            ("TestCIViews", "test_workflow_health_window", 1, 1),
        ],
    ),
    (
        "clickhouse",
        "posthog/clickhouse/test",
        [
            ("TestSchemaMigrations", "test_replicated_table_settings", 1, 1),
        ],
    ),
    (
        "logs",
        "products/logs/backend/test",
        [
            ("TestLogsQuery", "test_attribute_map_filter", 1, 1),
        ],
    ),
    (
        "team-billing",
        "ee/billing/test",
        [
            ("TestQuotaLimiting", "test_overage_grace_window", 1, 1),
        ],
    ),
    (
        "team-data-modeling",
        "products/data_modeling/backend/tests",
        [
            ("TestSavedQueryDAG", "test_cyclic_dependency_rejection", 1, 1),
        ],
    ),
    (
        "team-data-stack",
        "posthog/dags/tests",
        [
            ("TestDagsterAssets", "test_partition_backfill_window", 1, 1),
        ],
    ),
    (
        "team-growth",
        "products/growth/backend/tests",
        [
            ("TestOnboardingFunnel", "test_activation_email_dedupe", 1, 1),
        ],
    ),
    (
        "team-ai-gateway",
        "services/llm-gateway/tests",
        [
            ("TestProviderFailover", "test_anthropic_fallback_order", 1, 0),
        ],
    ),
    (
        "team-ai-research",
        "ee/hogai/test",
        [
            ("TestMemoryCompaction", "test_context_window_eviction", 1, 0),
        ],
    ),
    (
        "team-mcp-analytics",
        "products/mcp_analytics/backend/tests",
        [
            ("TestMcpToolEvents", "test_tool_call_attribution", 0, 1),
        ],
    ),
    (
        "",  # Spans with no owner stamp aggregate as the 'unowned' team.
        "posthog/api/test",
        [
            ("TestSharedMiddleware", "test_csrf_exempt_paths", 2, 2),
            ("TestLegacyEndpoints", "test_deprecated_capture_shim", 1, 1),
        ],
    ),
]


# The fixture's merges are too few for the per-team merge-timing chart: a team-day with fewer than
# 3 merges has a median equal to its average, so the chart's two lines coincide.
_DEMO_MERGES_PER_DAY = 40


def _demo_merged_prs(prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logins = sorted({(pr.get("user") or {}).get("login") or "" for pr in prs} - {""})
    authors = [login for login in logins if not login.endswith("[bot]") and login not in KNOWN_BOT_HANDLES]
    template_ts = next(pr["created_at"] for pr in prs if pr.get("created_at"))
    rows: list[dict[str, Any]] = []
    for index in range(_DEMO_MERGES_PER_DAY * _MERGE_SPREAD_DAYS):
        number = 90_000 + index
        rows.append(
            {
                "id": 9_910_000_000 + index,
                "number": number,
                "title": f"seeded: merged PR {number}",
                "state": "closed",
                "draft": False,
                # Placeholders inside the fixture's range, so they do not move the rebase anchor.
                # _spread_merges rewrites created_at and merged_at.
                "created_at": template_ts,
                "updated_at": template_ts,
                "merged_at": template_ts,
                "closed_at": template_ts,
                "user": {"login": authors[index % len(authors)], "avatar_url": ""},
                "head": {"sha": f"seed{index:04d}" + "a" * 32, "ref": f"seed/pr-{number}"},
                "base": {"ref": "master", "repo": {"full_name": SEED_REPOSITORY, "default_branch": "master"}},
                "labels": [],
            }
        )
    return rows


_GITHUB_TEAM_SLUGS = [slug for slug, _, _ in _SPAN_TEAMS if slug]


def _team_membership_rows(prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_counts: dict[str, int] = {}
    for pr in prs:
        login = (pr.get("user") or {}).get("login") or ""
        if login:
            merged_counts[login] = merged_counts.get(login, 0) + (1 if pr.get("merged_at") else 0)
    # Authors are dealt round-robin in merge-volume order so that every team gets active mergers.
    # The extra memberships give each team enough merges per day for a median that differs from
    # the average.
    logins = sorted(merged_counts, key=lambda login: (-merged_counts[login], login))
    team_count = len(_GITHUB_TEAM_SLUGS)
    rows: list[dict[str, Any]] = []
    for member_index, login in enumerate(logins):
        primary = member_index % team_count
        memberships = (primary, (member_index * 7 + 3) % team_count, (member_index * 13 + 11) % team_count)
        for slot, team_index in enumerate(memberships):
            if slot and team_index in memberships[:slot]:
                continue
            slug = _GITHUB_TEAM_SLUGS[team_index]
            rows.append(
                {
                    "id": 900_000 + member_index,
                    "login": login,
                    "role": "maintainer" if slot == 0 and member_index < team_count else "member",
                    "team_id": team_index + 1,
                    "team_slug": slug,
                    "team_name": slug.removeprefix("team-").replace("-", " ").title(),
                }
            )
    return rows


def _selector(module_dir: str, test_class: str, test_name: str) -> str:
    return f"{module_dir}/{test_name}.py::{test_class}::{test_name}"


# (file, test_class, name, parent, age_days). `parent` is what the uploader reports: 'pytest', the
# test file for Jest, the crate for Rust. The board resolves owners from the real repository, so
# the files are real. The ages straddle the TTL.
_QUARANTINED_TESTS: list[tuple[str, str, str, str, int]] = [
    ("products/replay_vision/backend/tests/test_api.py", "TestAPI", "test_tag_listing_pagination", "pytest", 41),
    (
        "products/batch_exports/backend/tests/test_service.py",
        "TestService",
        "test_backfill_window_overlap",
        "pytest",
        30,
    ),
    ("posthog/api/test/test_person.py", "TestPerson", "test_person_merge_ordering", "pytest", 23),
    ("posthog/hogql/test/test_query.py", "TestQuery", "test_property_type_coercion", "pytest", 16),
    # Trunk records a Jest file relative to the directory its suite ran from.
    ("tests/utils.test.ts", "", "parses a malformed header", "tests/utils.test.ts", 9),
    (
        "src/scenes/experiments/utils.test.ts",
        "",
        "rounds a bayesian interval",
        "src/scenes/experiments/utils.test.ts",
        5,
    ),
    ("", "", "remote_resolution_hardening", "cymbal::remote_resolution_hardening", 19),
    ("", "", "flag evaluation stays stable", "feature-flags", 2),
]


def _trunk_quarantined_rows() -> list[dict[str, Any]]:
    anchor = timezone.now().replace(microsecond=0)
    rows: list[dict[str, Any]] = []
    for index, (file, test_class, name, parent, age_days) in enumerate(_QUARANTINED_TESTS):
        quarantined_at = (anchor - timedelta(days=age_days, hours=index)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        module = file[:-3].replace("/", ".") if file.endswith(".py") else ""
        rows.append(
            {
                "id": f"engseed-trunk-{index:03d}",
                "test_collection_id": "engseed",
                "file": file,
                "name": name,
                "labels": "[]",
                "parent_name": parent,
                "class_name": f"{module}.{test_class}" if test_class else "",
                "variant": "",
                "status": "flaky",
                "codeowners": "[]",
                "quarantine_state": "quarantined",
                "quarantined_since": quarantined_at,
                "url": "",
            }
        )
    return rows


def _seed_trace_spans(team: Team) -> int:
    anchor = timezone.now().replace(microsecond=0)
    rows: list[str] = []
    span_index = 0
    for owner_team, module_dir, tests in _SPAN_TEAMS:
        for test_index, (test_class, test_name, prior_daily, current_daily) in enumerate(tests):
            module = test_name
            nodeid = f"{module_dir}/{module}/{test_class}::{test_name}"
            selector = _selector(module_dir, test_class, test_name)
            for day in range(_SPAN_DAYS):
                is_current = day >= _SPAN_DAYS // 2
                daily = current_daily if is_current else prior_daily
                daily = max(0, daily + ((day * 7 + test_index * 3) % 3) - 1)
                for occurrence in range(daily):
                    span_index += 1
                    cycle = (day + occurrence + test_index) % 5
                    if cycle < 2:
                        outcome, pr, branch = "rerun_passed", f"{7000 + (day * 13 + occurrence * 7) % 400}", ""
                    elif cycle < 4:
                        outcome, pr, branch = "failed", f"{7000 + (day * 17 + occurrence * 11) % 400}", ""
                    elif cycle == 4 and test_index % 2 == 0:
                        outcome, pr, branch = "error", "", "master"
                    else:
                        outcome, pr, branch = "xfailed", "", "master"
                    branch = branch or f"feat/{(module_dir.split('/')[1] if '/' in module_dir else 'core')}-{pr}"
                    ts = (anchor - timedelta(days=_SPAN_DAYS - 1 - day, hours=(span_index * 5) % 23)).strftime(_TS_FMT)
                    attr_pairs = [f"'test.outcome__str', '{outcome}'", f"'test.selector__str', '{selector}'"]
                    if owner_team:
                        attr_pairs.append(f"'test.owner_team__str', '{owner_team}'")
                    resource_pairs = [f"'ci.repository', '{SEED_REPOSITORY}'", f"'ci.branch', '{branch}'"]
                    if pr:
                        resource_pairs.append(f"'ci.pr_number', '{pr}'")
                    rows.append(
                        f"('{_SPAN_TRACE_PREFIX}-{span_index:06d}', {team.pk}, "
                        f"'{_SPAN_TRACE_PREFIX}-trace-{span_index}', 'span-{span_index}', 'parent', "
                        f"'{nodeid}', 1, '{ts}', '{ts}', '{ts}', 0, '{PYTEST_CI_SERVICE_NAME}', "
                        f"map({', '.join(attr_pairs)}), map({', '.join(resource_pairs)}))"
                    )

    # Local dev does not provision the traces tables. Both statements are CREATE TABLE IF NOT EXISTS.
    sync_execute(TRACE_SPANS_TABLE_SQL())
    sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

    # The table has projections, which reject a lightweight DELETE.
    sync_execute(
        f"ALTER TABLE trace_spans DELETE WHERE team_id = %(team_id)s AND trace_id LIKE '{_SPAN_TRACE_PREFIX}-%%' "
        "SETTINGS mutations_sync = 1",
        {"team_id": team.pk},
    )
    sync_execute(
        "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
        "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
        "resource_attributes) VALUES " + ",".join(rows)
    )
    return len(rows)


# Re-seeding deletes the log lines whose uuid carries this prefix, and no others.
_LOG_UUID_PREFIX = "engseed-log"
# OTLP severity numbers.
_LOG_SEVERITY = {"INFO": 9, "ERROR": 17}
# The hex ids and digit runs exercise the ci_failures fingerprint, which normalizes them.
_LOG_FAILURE_DETAILS = (
    "AssertionError: expected 200, got 500",
    "TimeoutError: ClickHouse query 8f3aa21b4c9d timed out after 30000 ms",
    "psycopg.OperationalError: connection to server at 127.0.0.1 port 5432 failed",
    "AssertionError: rows mismatch: 1042 != 1041",
)


def _sql_escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _seed_ci_failure_logs(team: Team, jobs: list[dict[str, Any]]) -> int:
    roster = [
        _selector(module_dir, test_class, test_name)
        for _owner, module_dir, tests in _SPAN_TEAMS
        for test_class, test_name, _prior, _current in tests
    ]
    expiry = (timezone.now() + timedelta(days=30)).strftime(_TS_FMT)
    rows: list[str] = []
    for job in jobs:
        if job.get("conclusion") not in _FAILING_CONCLUSIONS:
            continue
        ts = job.get("completed_at") or job.get("started_at")
        if not ts:
            continue
        job_id, run_id = job["id"], job["run_id"]
        selector = roster[job_id % len(roster)]
        detail = _LOG_FAILURE_DETAILS[job_id % len(_LOG_FAILURE_DETAILS)]
        orig_total = 1800 + job_id % 900
        base_line = 1200 + job_id % 300
        # (body, severity_text, orig_line). An omission marker has no orig_line.
        lines: list[tuple[str, str, int | None]] = [
            ("=========================== short test summary info ============================", "INFO", base_line),
            (f"FAILED {selector} - {detail}", "ERROR", base_line + 1),
            (f"... {orig_total - base_line - 3} lines omitted ...", "INFO", None),
            ("##[error]Process completed with exit code 1.", "ERROR", orig_total),
        ]
        # Keep in sync with the attributes the job-logs pipeline emits, because the reads filter on
        # them. The logs table's ``attributes`` alias strips the ``__str`` suffix, so a read of
        # ``attributes['repo']`` needs ``repo__str`` in ``attributes_map_str``.
        base_attrs = (
            f"'job_id__str', '{job_id}', 'run_id__str', '{run_id}', 'repo__str', '{SEED_REPOSITORY}', "
            f"'branch__str', '{_sql_escape(job.get('head_branch') or '')}', "
            f"'conclusion__str', '{_sql_escape(job.get('conclusion'))}', "
            f"'job_name__str', '{_sql_escape(job.get('name'))}', "
            f"'workflow_name__str', '{_sql_escape(job.get('workflow_name') or '')}', "
            f"'run_attempt__str', '{job.get('run_attempt') or 1}', "
            f"'head_sha__str', '{_sql_escape(job.get('head_sha') or '')}', "
            f"'orig_total__str', '{orig_total}'"
        )
        for seq, (body, severity_text, orig_line) in enumerate(lines):
            attrs = f"{base_attrs}, 'seq__str', '{seq}'"
            if orig_line is not None:
                attrs += f", 'orig_line__str', '{orig_line}'"
            rows.append(
                f"('{_LOG_UUID_PREFIX}-{job_id}-{seq}', {team.pk}, '{run_id}', '{job_id}', 0, "
                f"'{_sql_escape(ts)}', '{_sql_escape(ts)}', '{expiry}', '{_sql_escape(body)}', "
                f"'{severity_text}', {_LOG_SEVERITY[severity_text]}, "
                f"'{CI_LOGS_SERVICE_NAME}', map('service.name', '{CI_LOGS_SERVICE_NAME}'), 'engseed@1', '', "
                f"map({attrs}))"
            )

    # HogQL's `logs` reads `logs_distributed`, so the insert writes there. The delete targets the
    # local table because a Distributed engine rejects ALTER.
    sync_execute(
        f"ALTER TABLE {LOGS_LOCAL_TABLE} DELETE WHERE team_id = %(team_id)s AND uuid LIKE '{_LOG_UUID_PREFIX}-%%' "
        "SETTINGS mutations_sync = 1",
        {"team_id": team.pk},
        workload=Workload.LOGS,
    )
    if rows:
        sync_execute(
            "INSERT INTO logs_distributed (uuid, team_id, trace_id, span_id, trace_flags, timestamp, "
            "observed_timestamp, original_expiry_timestamp, body, severity_text, severity_number, service_name, "
            "resource_attributes, instrumentation_scope, event_name, attributes_map_str) VALUES " + ",".join(rows),
            workload=Workload.LOGS,
        )
    return len(rows)


def _warehouse_endpoint() -> str:
    # ClickHouse runs in docker, so it reaches a localhost object-storage endpoint through the docker host.
    endpoint = settings.OBJECT_STORAGE_ENDPOINT.rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return endpoint
    netloc = f"host.docker.internal:{parsed.port}" if parsed.port else "host.docker.internal"
    return urlunparse(parsed._replace(netloc=netloc))


class Command(BaseCommand):
    help = "Seed the engineering analytics warehouse tables behind a connected GitHub source from the fixture."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team to seed the warehouse tables into.")
        parser.add_argument(
            "--fixture-dir", type=Path, default=FIXTURE_DIR, help="Directory holding the fixture JSON files."
        )
        parser.add_argument(
            "--keep-dates",
            action="store_true",
            help="Load the snapshot's original timestamps instead of rebasing them to now.",
        )
        parser.add_argument(
            "--prefix",
            type=str,
            default=DEFAULT_PREFIX,
            help="Source prefix for the seeded GitHub tables (table name is <prefix>github_<endpoint>).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True (local/dev only).")
        if not settings.OBJECT_STORAGE_ENABLED or not settings.OBJECT_STORAGE_ACCESS_KEY_ID:
            raise CommandError("Object storage is not configured — start the dev stack first (hogli start).")
        prefix = options["prefix"]
        prefix_valid, prefix_error = validate_source_prefix(prefix)
        if not prefix_valid:
            raise CommandError(f"Invalid --prefix {prefix!r}: {prefix_error}")
        try:
            team = Team.objects.get(pk=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist.")

        prs = self._load_fixture(options["fixture_dir"], "github_pull_requests.json")
        runs = self._load_fixture(options["fixture_dir"], "github_workflow_runs.json")

        prs.extend(_demo_merged_prs(prs))
        demo_pr, demo_runs = _demo_multi_push(prs, runs)
        prs.append(demo_pr)
        runs.extend(demo_runs)
        _spread_merges(prs, _fixture_anchor(prs, runs))
        # The snapshot's master runs span days, which flattens every other duration on the
        # master-health chart, so the synthetic commits replace them.
        runs = [run for run in runs if run.get("head_branch") != "master"]
        # _demo_master_commits stamps merge_commit_sha on these PR rows, so pass the rows themselves.
        merged_prs = [pr for pr in prs if pr.get("merged_at")]
        runs.extend(_demo_master_commits(_fixture_anchor(prs, runs), merged_prs))
        runs.extend(_gate_runs(prs))
        issue_events = _issue_event_rows(prs, _fixture_anchor(prs, runs))
        reviews = _review_rows(prs, _fixture_anchor(prs, runs))
        deploy_rows = _deployment_rows(prs)

        # _shift_dates also rewrites timestamps into the format ClickHouse parses, so it runs with a zero shift too.
        shift = timedelta(0) if options["keep_dates"] else self._rebase_delta(prs, runs)
        prs = [self._shift_dates(pr, PR_DATE_FIELDS, shift) for pr in prs]
        runs = [self._shift_dates(run, RUN_DATE_FIELDS, shift) for run in runs]
        issue_events = [self._shift_dates(event, ("created_at",), shift) for event in issue_events]
        reviews = [self._shift_dates(review, ("submitted_at",), shift) for review in reviews]
        deployments = [self._shift_dates(row, ("created_at",), shift) for row in deploy_rows.deployments]
        deployment_statuses = [self._shift_dates(row, ("created_at",), shift) for row in deploy_rows.statuses]
        if shift:
            self.stdout.write(f"Rebased timestamps forward by {shift}.")

        with team_scope(team.pk):
            credential = get_or_create_datawarehouse_credential(
                team_id=team.pk,
                access_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                access_secret=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            )
            source = self._get_or_create_seed_source(
                team,
                prefix,
                source_id=SEED_SOURCE_ID,
                source_type=ExternalDataSourceType.GITHUB,
                job_inputs={"repository": SEED_REPOSITORY},
            )
            self._upsert_schema_table(
                team, source, credential, prefix, PULL_REQUESTS_SCHEMA, PULL_REQUESTS_COLUMNS, map(_flatten_pr, prs)
            )
            self._upsert_schema_table(
                team, source, credential, prefix, WORKFLOW_RUNS_SCHEMA, WORKFLOW_RUNS_COLUMNS, map(_flatten_run, runs)
            )
            jobs = _synthesize_jobs(runs)
            self._upsert_schema_table(
                team, source, credential, prefix, WORKFLOW_JOBS_SCHEMA, WORKFLOW_JOBS_COLUMNS, jobs
            )
            self._upsert_schema_table(
                team, source, credential, prefix, TEAM_MEMBERS_SCHEMA, TEAM_MEMBERS_COLUMNS, _team_membership_rows(prs)
            )
            self._upsert_schema_table(
                team, source, credential, prefix, ISSUE_EVENTS_SCHEMA, ISSUE_EVENTS_COLUMNS, issue_events
            )
            self._upsert_schema_table(team, source, credential, prefix, REVIEWS_SCHEMA, REVIEWS_COLUMNS, reviews)
            trunk_source = self._get_or_create_seed_source(
                team,
                prefix,
                source_id=TRUNK_SEED_SOURCE_ID,
                source_type=ExternalDataSourceType.TRUNKIO,
                job_inputs={"org_url_slug": "posthog-inc", "repo_owner": "PostHog", "repo_name": "posthog"},
            )
            self._upsert_schema_table(
                team,
                trunk_source,
                credential,
                prefix,
                TRUNK_QUARANTINED_TESTS_SCHEMA,
                TRUNK_QUARANTINED_TESTS_COLUMNS,
                _trunk_quarantined_rows(),
                source_kind="trunkio",
            )
            self._upsert_schema_table(
                team, source, credential, prefix, DEPLOYMENTS_SCHEMA, DEPLOYMENTS_COLUMNS, deployments
            )
            self._upsert_schema_table(
                team,
                source,
                credential,
                prefix,
                DEPLOYMENT_STATUSES_SCHEMA,
                DEPLOYMENT_STATUSES_COLUMNS,
                deployment_statuses,
            )

        # A dev stack without the traces or logs tables still gets the warehouse seed.
        try:
            span_count = _seed_trace_spans(team)
            self.stdout.write(f"Seeded {span_count} per-test CI spans into trace_spans (flaky/team surfaces).")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Skipped trace_spans seed (traces table unavailable?): {exc}"))

        try:
            log_count = _seed_ci_failure_logs(team, jobs)
            self.stdout.write(f"Seeded {log_count} CI failure log lines into logs (broken tests/failure logs).")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Skipped CI failure logs seed (logs table unavailable?): {exc}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(prs)} pull requests, {len(runs)} workflow runs, and {len(jobs)} jobs into "
                f"team {team.pk} under GitHub source prefix '{prefix}'."
            )
        )
        self.stdout.write(
            f"Multi-push demo PR: /project/{team.pk}/engineering-analytics/repos/{SEED_REPOSITORY}/pull-requests/{_DEMO_PR_NUMBER}"
        )

    def _load_fixture(self, fixture_dir: Path, filename: str) -> list[dict[str, Any]]:
        path = fixture_dir / filename
        if not path.exists():
            raise CommandError(
                f"Fixture {path} not found — run products/engineering_analytics/fixtures/fetch.py first."
            )
        return json.loads(path.read_text())

    def _rebase_delta(self, prs: list[dict[str, Any]], runs: list[dict[str, Any]]) -> timedelta:
        newest = max(
            datetime.fromisoformat(row[field])
            for row, fields in [*((pr, PR_DATE_FIELDS) for pr in prs), *((run, RUN_DATE_FIELDS) for run in runs)]
            for field in fields
            if row[field] is not None
        )
        return max(timedelta(0), timezone.now() - newest)

    def _shift_dates(self, row: dict[str, Any], fields: tuple[str, ...], shift: timedelta) -> dict[str, Any]:
        shifted = dict(row)
        for field in fields:
            if shifted[field] is not None:
                moved = datetime.fromisoformat(shifted[field]) + shift
                shifted[field] = moved.strftime("%Y-%m-%d %H:%M:%S")
        return shifted

    def _get_or_create_seed_source(
        self,
        team: Team,
        prefix: str,
        *,
        source_id: str,
        source_type: ExternalDataSourceType,
        job_inputs: dict[str, str],
    ) -> ExternalDataSource:
        source = ExternalDataSource.objects.filter(team=team, source_id=source_id, source_type=source_type).first()
        if source is None:
            return SourceInputsStore.create(
                team=team,
                source_id=source_id,
                connection_id=source_id,
                status=ExternalDataSourceStatus.COMPLETED,
                source_type=source_type,
                prefix=prefix,
                inputs=dict(job_inputs),
            )
        update_fields = []
        if source.prefix != prefix:
            source.prefix = prefix
            update_fields.append("prefix")
        inputs = SourceInputsStore.load(source)
        if any(inputs.get(key) != value for key, value in job_inputs.items()):
            SourceInputsStore.assign(source, {**inputs, **job_inputs})
            update_fields.extend(SourceInputsStore.update_fields)
        if update_fields:
            source.save(update_fields=[*update_fields, "updated_at"])
        return source

    def _upsert_schema_table(
        self,
        team: Team,
        source: ExternalDataSource,
        credential: Any,
        prefix: str,
        schema_name: str,
        columns: dict[str, dict[str, str]],
        rows: Any,
        source_kind: str = "github",
    ) -> None:
        records = list(rows)
        # A real sync names its table <prefix><kind>_<endpoint>.
        table_name = f"{prefix}{source_kind}_{schema_name.lower() if source_kind != 'github' else schema_name}"
        headers = list(columns.keys())
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows([record[header] for header in headers] for record in records)

        s3_prefix = f"data-warehouse/engineering_analytics_{table_name}/team_{team.pk}"
        object_storage.write(f"{s3_prefix}/{table_name}.csv", output.getvalue())
        url_pattern = f"{_warehouse_endpoint()}/{settings.OBJECT_STORAGE_BUCKET}/{s3_prefix}/*.csv"

        existing = DataWarehouseTable.objects.filter(team=team, name=table_name).first()
        if existing is not None and existing.external_data_source_id not in (None, source.id):
            raise CommandError(
                f"Table {table_name} belongs to another warehouse source — refusing to overwrite it. "
                "Use a different --prefix (or another team) to seed fixture data."
            )
        if existing is not None:
            existing.format = DataWarehouseTableFormat.CSVWithNames
            existing.url_pattern = url_pattern
            existing.credential = credential
            existing.external_data_source = source
            existing.columns = columns
            existing.options = {**(existing.options or {}), "csv_allow_double_quotes": True}
            existing.deleted = False
            existing.deleted_at = None
            # url_pattern is computed here, not taken from request input. The save guard reads the
            # row's stored state, so a stale row with no credential would trip it without this flag.
            existing.save(internally_computed_url_pattern=True)
            table = existing
        else:
            table = DataWarehouseTable.objects.create(
                team=team,
                name=table_name,
                format=DataWarehouseTableFormat.CSVWithNames,
                url_pattern=url_pattern,
                credential=credential,
                external_data_source=source,
                columns=columns,
                options={"csv_allow_double_quotes": True},
            )

        schema = ExternalDataSchema.objects.filter(team=team, source=source, name=schema_name).first()
        if schema is None:
            ExternalDataSchema.objects.create(team=team, source=source, name=schema_name, table=table, should_sync=True)
        elif schema.table_id != table.id or not schema.should_sync or schema.deleted:
            schema.table = table
            schema.should_sync = True
            schema.deleted = False
            schema.deleted_at = None
            schema.save()
        self.stdout.write(f"Seeded warehouse table {table_name} ({len(records)} rows) as schema '{schema_name}'.")
