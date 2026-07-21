"""Seed the engineering analytics warehouse tables from the checked-in GitHub fixture.

Loads ``products/engineering_analytics/fixtures/github_pull_requests.json`` and
``github_workflow_runs.json`` (a real PostHog/posthog snapshot captured with
``fixtures/fetch.py``) into the team's data warehouse behind a connected GitHub
source, exactly as a real sync would: a GitHub ``ExternalDataSource`` with a
``--prefix``, plus ``pull_requests`` / ``workflow_runs`` ``ExternalDataSchema`` rows
pointing at the materialized ``<prefix>github_pull_requests`` /
``<prefix>github_workflow_runs`` tables. The product resolves those names per team
(``logic.sources``), so seeding under a non-default prefix exercises the resolver
rather than the old hardcoded ``github_*`` names.

Timestamps are rebased so the newest fixture row lands at "now" — the queries
window on server-side now(), so an unshifted old snapshot would render empty.
Pass --keep-dates for the faithful snapshot instead.

Re-running replaces this seed source's tables, but a table owned by a different
(real) connected source is never touched. Local/dev only: requires the dev object
storage and ClickHouse from the hogli stack.

Usage:
    python manage.py seed_engineering_analytics --team-id 1
    python manage.py seed_engineering_analytics --team-id 1 --prefix devex_eng_analytics
    python manage.py seed_engineering_analytics --team-id 1 --keep-dates
"""

import csv
import json
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL
from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.storage import object_storage

from products.engineering_analytics.backend.logic.queries._test_spans import CI_SERVICE_NAME
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    TEAM_MEMBERS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
)
from products.engineering_analytics.backend.logic.views.pull_requests import KNOWN_BOT_HANDLES
from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    TEAM_MEMBERS_COLUMNS,
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
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures"

PR_DATE_FIELDS = ("created_at", "updated_at", "merged_at", "closed_at")
RUN_DATE_FIELDS = ("created_at", "run_started_at", "updated_at")

# Marks the GitHub source this command owns, so re-seeding never clobbers a real source.
SEED_SOURCE_ID = "engineering_analytics_seed"
# Matches the fixtures' repository.full_name; without it the UI's repo header/picker fall back to
# placeholders (a real source stores the repo in job_inputs at connect time).
SEED_REPOSITORY = "PostHog/posthog"
# Default prefix is non-trivial on purpose: it proves the product resolves the real
# per-team table name rather than assuming the bare ``github_*`` names.
DEFAULT_PREFIX = "eng_analytics_seed"


def _flatten_pr(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: pr[key] for key in PULL_REQUESTS_COLUMNS if key not in ("user", "head", "base", "labels", "draft")},
        "draft": int(bool(pr["draft"])),
        "user": json.dumps(pr["user"]),
        "head": json.dumps(pr["head"]),
        "base": json.dumps(pr["base"]),
        "labels": json.dumps(pr["labels"]),
    }


def _flatten_run(run: dict[str, Any]) -> dict[str, Any]:
    json_keys = ("repository", "pull_requests", "head_commit")
    scalar_keys = [key for key in WORKFLOW_RUNS_COLUMNS if key not in json_keys]
    return {
        # .get() tolerates a pre-existing fixture captured before run_attempt / pull_requests were added.
        **{key: run.get(key) for key in scalar_keys},
        "repository": json.dumps(run["repository"]),
        "pull_requests": json.dumps(run.get("pull_requests", [])),
        "head_commit": json.dumps(run.get("head_commit", {})),
    }


# Synthesize a few jobs per run so the expandable job breakdown and cost cards are demoable in local
# dev. Tiers vary so the cost model produces a spread; the last job inherits a failing run's conclusion.
_JOB_NAMES = ("build", "test", "lint", "e2e")
_RUNNER_LABELS = (
    '["depot-ubuntu-22.04-16"]',
    '["depot-ubuntu-22.04-8"]',
    '["depot-ubuntu-22.04-4"]',
    '["ubuntu-latest"]',
)


_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _synthesize_jobs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for run in runs:
        completed = run.get("status") == "completed"
        run_conclusion = run.get("conclusion")
        count = (run["id"] % 3) + 2  # 2–4 jobs, deterministic per run

        # Stagger jobs sequentially across the run's window so the job Gantt reads as a real timeline
        # (build → test → …) instead of identical full-width bars.
        run_start: datetime | None = None
        run_end: datetime | None = None
        try:
            run_start = datetime.strptime(run["run_started_at"], _TS_FMT)
            run_end = datetime.strptime(run["updated_at"], _TS_FMT)
        except (KeyError, TypeError, ValueError):
            pass
        window = (run_end - run_start).total_seconds() if run_start and run_end and run_end > run_start else 0.0
        segment = window / count if window else 0.0

        for idx in range(count):
            is_last = idx == count - 1
            # Healthy jobs pass; a failing run's failure surfaces on its last job.
            conclusion = run_conclusion if (is_last and run_conclusion in ("failure", "timed_out")) else None
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
                    "steps": "[]",
                }
            )
    return jobs


# A synthetic multi-push PR so the per-push sparkline and multi-run expansion are demoable — captured
# real PRs rarely re-run many workflows across pushes, so nothing in the fixture shows the progression.
# Local-seed only; clearly numbered 99001 and labelled "demo".
_DEMO_PR_NUMBER = 99001
# Per-workflow conclusion across the 4 pushes (oldest → newest) — a mix of red→green progressions,
# steady-green, a late blip, and one still running on the latest push.
_DEMO_MATRIX: dict[str, list[str | None]] = {
    "Backend CI": ["failure", "failure", "success", "success"],
    "Frontend CI": ["failure", "success", "success", "success"],
    "Rust CI": ["success", "failure", "success", "success"],
    "E2E Tests": ["failure", "failure", "failure", "success"],
    "Storybook": ["success", "success", "success", "success"],
    "Lint": ["success", "success", "success", "success"],
    "Migrations": ["success", "success", "failure", "success"],
    "MCP CI": ["success", "success", "success", None],  # None → still running on the latest push
    "Docs": ["success", "success", "success", "success"],
    "Security": ["timed_out", "failure", "success", "success"],
}


def _fixture_anchor(prs: list[dict[str, Any]], runs: list[dict[str, Any]]) -> datetime:
    # Just after the fixture's newest row, so the rebase lands synthesized data at "now".
    newest = max(
        datetime.fromisoformat(row[field])
        for row, fields in [*((pr, PR_DATE_FIELDS) for pr in prs), *((run, RUN_DATE_FIELDS) for run in runs)]
        for field in fields
        if row[field] is not None
    )
    return newest + timedelta(hours=1)


# Merged PRs re-spread across two weeks so the 14d merge-trend and cost-per-merge charts have a
# point in every bucket.
_MERGE_SPREAD_DAYS = 14

# Synthetic default-branch commit stream: the captured snapshot holds only ~a dozen master SHAs, which
# draws the master-health scatter as a near-empty chart. Deterministic (index arithmetic, no random),
# local-seed only; SHAs are prefixed "aa57e2" so they read as seeded in the UI.
_MASTER_WORKFLOWS = ("Backend CI", "Frontend CI", "Rust CI", "E2E Tests", "Lint", "Storybook")
# Co-windowed with the merge spread: a day with merges but no seeded job cost would chart as $0/merge.
_MASTER_DAYS = _MERGE_SPREAD_DAYS
_MASTER_COMMITS_PER_DAY = 18


def _demo_master_commits(anchor: datetime) -> list[dict[str, Any]]:
    def iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    total = _MASTER_DAYS * _MASTER_COMMITS_PER_DAY
    spacing_minutes = _MASTER_DAYS * 24 * 60 // total
    demo_runs: list[dict[str, Any]] = []
    for commit_index in range(total):
        # Even spacing with a per-commit wobble so the X axis doesn't read as a metronome.
        age_minutes = (total - 1 - commit_index) * spacing_minutes + (commit_index * 37) % 90
        commit_time = anchor - timedelta(minutes=age_minutes)
        sha = f"aa57e2{commit_index:04d}" + "e" * 30
        red_commit = commit_index % 9 == 4  # an occasional broken master push
        cancelled_commit = commit_index % 17 == 9  # a rare all-cancelled push (neutral dot)
        for wf_index, workflow in enumerate(_MASTER_WORKFLOWS):
            # Newest two commits keep one workflow running so the in-flight band has live data.
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
                    "updated_at": iso(start) if running else iso(start + duration),
                    "run_attempt": 1,
                    "repository": {"full_name": "PostHog/posthog"},
                    "pull_requests": [],
                }
            )
    return demo_runs


def _spread_merges(prs: list[dict[str, Any]], anchor: datetime) -> None:
    # The snapshot captured recently-updated PRs, so their merge times all cluster on the capture day
    # and the cost-per-merge and time-to-merge trends collapse into a single bucket. Re-spread merged
    # PRs evenly across the seeded window and derive created_at backwards from a realistic duration mix
    # (mostly hours-to-two-days, an occasional week-long tail); clamping merged_at forward against the
    # snapshot's created_at instead would pile every merge on the capture day at a constant duration.
    span_hours = _MERGE_SPREAD_DAYS * 24
    merged = [pr for pr in prs if pr.get("merged_at")]
    for index, pr in enumerate(merged):
        merged_at = anchor - timedelta(hours=(index * 11) % span_hours, minutes=(index * 13) % 60)
        open_hours = 3 + (index * 17) % 45  # 3h–2d for most PRs...
        if index % 9 == 4:
            open_hours += 24 * (2 + index % 5)  # ...with a 2–6 day review tail on some
        pr["merged_at"] = merged_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        pr["created_at"] = (merged_at - timedelta(hours=open_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _demo_multi_push(
    prs: list[dict[str, Any]], runs: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    # Anchor the demo just after the fixture's newest row so the rebase lands its last push at "now".
    anchor = _fixture_anchor(prs, runs)
    push_shas = [f"demo00{k + 1}" + "f" * 33 for k in range(4)]  # 40 chars, distinct first 7 (demo001…demo004)
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
            end = start + timedelta(minutes=5 + (wf_index % 6) * 4)  # 5–25 min spread for p50/p95
            demo_runs.append(
                {
                    "id": 9_900_000_000 + push_index * 100 + wf_index,
                    "name": workflow,
                    "head_sha": push_shas[push_index],
                    "head_branch": "demo/multi-push-progression",
                    "status": "in_progress" if running else "completed",
                    "conclusion": None if running else conclusion,
                    "created_at": iso(start),
                    "run_started_at": iso(start),
                    "updated_at": iso(start) if running else iso(end),
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
        "base": {"repo": {"full_name": "PostHog/posthog"}},
        "labels": ["demo"],
    }
    return demo_pr, demo_runs


# Synthetic per-test CI spans for the flaky-test and team CI health surfaces (they read
# posthog.trace_spans, not the warehouse). Each team gets a distinct trend shape so the
# roster deltas, daily trend, and before/after slope all have something honest to show.
# Deterministic (index arithmetic, no random); trace ids are prefixed 'engseed-' so
# re-seeding can delete exactly its own rows.
_SPAN_TRACE_PREFIX = "engseed"
_SPAN_DAYS = 28  # 14-day current window + its equal-length prior twin

# (owner_team, module_dir, [(TestClass, test_name, prior_daily, current_daily)]).
# prior/current_daily are signal spans per day in each half of the window; 0 = quiet.
# The roster is every distinct owner slug in the repo's ownership files (owners.yaml +
# products/*/product.yaml, the same map the CI emitter stamps from) as of July 2026, so
# the team surfaces demo against the real org. Module dirs are real test directories.
_SPAN_TEAMS: list[tuple[str, str, list[tuple[str, str, int, int]]]] = [
    (
        "team-replay",  # worsening: signal doubles in the current window
        "posthog/session_recordings/test",
        [
            ("TestSessionRecordings", "test_snapshot_batching", 2, 5),
            ("TestRecordingPlaylists", "test_playlist_counts_converge", 1, 3),
            ("TestRetentionSweeper", "test_ttl_boundary_day", 0, 2),
        ],
    ),
    (
        "batch-exports",  # high and flat: the standing offender
        "products/batch_exports/backend/tests",
        [
            ("TestSnowflakeExport", "test_incremental_primary_key_resume", 4, 4),
            ("TestBigQueryExport", "test_backfill_window_overlap", 3, 3),
            ("TestTemporalWorkflows", "test_teardown_cancellation", 2, 3),
            ("TestS3Export", "test_multipart_retry", 2, 2),
        ],
    ),
    (
        "team-ingestion",  # improving: signal halves in the current window
        "posthog/models/test",
        [
            ("TestPersonMerges", "test_concurrent_merge_ordering", 4, 1),
            ("TestKafkaConsumer", "test_rebalance_offset_commit", 3, 1),
        ],
    ),
    (
        "conversations",  # spiky: quiet prior, a current-window burst
        "products/conversations/backend/api/tests",
        [
            ("TestTicketRouting", "test_assignment_race", 0, 4),
        ],
    ),
    (
        "team-experiments",  # recovered: prior signal only, lands at zero current
        "products/experiments/backend/test",
        [
            ("TestExperimentResults", "test_bayesian_interval_rounding", 3, 0),
            ("TestFeatureFlagRollout", "test_variant_bucketing_stability", 2, 0),
        ],
    ),
    (
        "team-error-tracking",  # brand new flake: current window only
        "products/error_tracking/backend/tests",
        [
            ("TestIssueGrouping", "test_fingerprint_collision", 0, 3),
        ],
    ),
    (
        "team-data-tools",  # mildly worsening
        "posthog/hogql/test",
        [
            ("TestHogQLParser", "test_lambda_scope_resolution", 2, 3),
            ("TestHogQLPrinter", "test_materialized_column_rewrite", 1, 1),
        ],
    ),
    (
        "team-workflows",  # mildly worsening
        "products/cdp/backend/test",
        [
            ("TestHogFunctions", "test_retry_backoff_jitter", 2, 3),
            ("TestDestinationFilters", "test_event_property_globs", 1, 1),
        ],
    ),
    (
        "team-product-analytics",  # mildly improving
        "posthog/hogql_queries/insights/test",
        [
            ("TestTrendsQueryRunner", "test_interval_boundary_timezone", 3, 2),
            ("TestFunnelCorrelation", "test_person_property_breakdown", 1, 1),
        ],
    ),
    (
        "team-platform-features",  # mildly improving
        "products/access_control/backend/tests",
        [
            ("TestAccessControl", "test_role_membership_cache_invalidation", 2, 1),
            ("TestOrgInvites", "test_invite_expiry_race", 1, 1),
        ],
    ),
    (
        "team-ai-observability",  # mildly improving
        "products/ai_observability/backend/test",
        [
            ("TestGenerationCosts", "test_cost_property_rollup", 2, 1),
            ("TestTraceIngestion", "test_span_attribute_truncation", 1, 1),
        ],
    ),
    (
        "team-surveys",  # mildly improving
        "products/surveys/backend/api/test",
        [
            ("TestSurveyTargeting", "test_adaptive_sampling_rate", 2, 1),
        ],
    ),
    (
        "team-warehouse-sources",  # flat
        "products/warehouse_sources/backend/tests",
        [
            ("TestStripeSource", "test_incremental_cursor_persistence", 2, 2),
            ("TestSourceSchemaSync", "test_nullable_json_columns", 1, 1),
        ],
    ),
    (
        "team-analytics-platform",  # flat
        "products/dashboards/backend/test",
        [
            ("TestDashboardTiles", "test_tile_refresh_debounce", 2, 2),
            ("TestAlertChecks", "test_threshold_hysteresis", 1, 1),
        ],
    ),
    (
        "team-web-analytics",  # one flake fixed, one steady
        "products/web_analytics/backend/test",
        [
            ("TestWebOverview", "test_preaggregated_table_parity", 2, 2),
            ("TestChannelType", "test_utm_priority_order", 1, 0),
        ],
    ),
    (
        "team-feature-flags",  # one flake fixed, one steady
        "products/feature_flags/backend/test",
        [
            ("TestFlagMatching", "test_local_evaluation_consistency", 2, 2),
            ("TestFlagDependencies", "test_cohort_flag_cycle", 1, 0),
        ],
    ),
    (
        "team-self-driving",  # creeping up
        "products/signals/backend/test",
        [
            ("TestSignalEmission", "test_dedupe_window_replay", 1, 2),
            ("TestInboxRouting", "test_scout_finding_grouping", 0, 1),
        ],
    ),
    (
        "team-agents",  # creeping up
        "products/agent_platform/backend/tests",
        [
            ("TestAgentRuns", "test_tool_call_stream_resume", 1, 2),
        ],
    ),
    (
        "team-managed-warehouse",  # creeping up
        "products/data_warehouse/backend/tests",
        [
            ("TestSavedQueryMaterialization", "test_incremental_refresh_watermark", 1, 2),
        ],
    ),
    (
        "team-posthog-code",  # creeping up
        "products/tasks/backend/tests",
        [
            ("TestTaskSandbox", "test_worktree_cleanup_on_cancel", 1, 2),
        ],
    ),
    (
        "team-devex",  # low and flat
        "products/engineering_analytics/backend/tests",
        [
            ("TestCIViews", "test_workflow_health_window", 1, 1),
        ],
    ),
    (
        "clickhouse",  # low and flat
        "posthog/clickhouse/test",
        [
            ("TestSchemaMigrations", "test_replicated_table_settings", 1, 1),
        ],
    ),
    (
        "logs",  # low and flat
        "products/logs/backend/test",
        [
            ("TestLogsQuery", "test_attribute_map_filter", 1, 1),
        ],
    ),
    (
        "team-billing",  # low and flat
        "ee/billing/test",
        [
            ("TestQuotaLimiting", "test_overage_grace_window", 1, 1),
        ],
    ),
    (
        "team-data-modeling",  # low and flat
        "products/data_modeling/backend/tests",
        [
            ("TestSavedQueryDAG", "test_cyclic_dependency_rejection", 1, 1),
        ],
    ),
    (
        "team-data-stack",  # low and flat
        "posthog/dags/tests",
        [
            ("TestDagsterAssets", "test_partition_backfill_window", 1, 1),
        ],
    ),
    (
        "team-growth",  # low and flat
        "products/growth/backend/tests",
        [
            ("TestOnboardingFunnel", "test_activation_email_dedupe", 1, 1),
        ],
    ),
    (
        "team-ai-gateway",  # recovered small
        "services/llm-gateway/tests",
        [
            ("TestProviderFailover", "test_anthropic_fallback_order", 1, 0),
        ],
    ),
    (
        "team-ai-research",  # recovered small
        "ee/hogai/test",
        [
            ("TestMemoryCompaction", "test_context_window_eviction", 1, 0),
        ],
    ),
    (
        "team-mcp-analytics",  # brand new, small
        "products/mcp_analytics/backend/tests",
        [
            ("TestMcpToolEvents", "test_tool_call_attribution", 0, 1),
        ],
    ),
    (
        "",  # unstamped spans: the honest 'unowned' bucket
        "posthog/api/test",
        [
            ("TestSharedMiddleware", "test_csrf_exempt_paths", 2, 2),
            ("TestLegacyEndpoints", "test_deprecated_capture_shim", 1, 1),
        ],
    ),
]


# Synthetic merged-PR stream: the captured snapshot holds only ~115 merges, which spreads to
# well under one merge per team-day across the 30-team roster, too thin for the per-team
# merge-timing chart (a day with fewer than 3 merges has median == average by definition, so
# the two lines would always coincide). Real PostHog/posthog merges ~40 PRs a day, so the
# stream also makes repo-wide merge volume honest. Deterministic; numbered from 90000 and
# titled "seeded:" so rows read as seeded in the UI. Timing/durations come from _spread_merges,
# which rewrites every merged PR's merged_at/created_at anyway.
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
                # Placeholder timestamps inside the fixture's range (so the rebase anchor is
                # unchanged); _spread_merges rewrites created_at/merged_at deterministically.
                "created_at": template_ts,
                "updated_at": template_ts,
                "merged_at": template_ts,
                "closed_at": template_ts,
                "user": {"login": authors[index % len(authors)], "avatar_url": ""},
                "head": {"sha": f"seed{index:04d}" + "a" * 32, "ref": f"seed/pr-{number}"},
                "base": {"ref": "master", "repo": {"full_name": SEED_REPOSITORY}},
                "labels": [],
            }
        )
    return rows


# GitHub org team membership for the merge-trend join (PR author login → team slug). Fixture
# authors are assigned deterministically across the roster teams (no random, stable between
# runs); local-seed only, so the mapping is synthetic: it exists to light up the per-team
# time-to-merge chart against real PR merge data.
_GITHUB_TEAM_SLUGS = [slug for slug, _, _ in _SPAN_TEAMS if slug]


def _team_membership_rows(prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_counts: dict[str, int] = {}
    for pr in prs:
        login = (pr.get("user") or {}).get("login") or ""
        if login:
            merged_counts[login] = merged_counts.get(login, 0) + (1 if pr.get("merged_at") else 0)
    # Deal authors across teams round-robin in merge-volume order, so every team gets a share of
    # active mergers instead of hash luck leaving some team lines empty. Scattered extra
    # memberships mirror how org teams really overlap and thicken each team's series enough that
    # days see 3+ merges; below that, a day's median and average are mathematically identical
    # and the trend's two lines would always coincide.
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
                    "team_id": team_index + 1,
                    "team_slug": slug,
                    "team_name": slug.removeprefix("team-").replace("-", " ").title(),
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
            selector = f"{module_dir}/{module}.py::{test_class}::{test_name}"
            for day in range(_SPAN_DAYS):
                is_current = day >= _SPAN_DAYS // 2
                daily = current_daily if is_current else prior_daily
                # ±1 wobble so trends read organic, never below zero.
                daily = max(0, daily + ((day * 7 + test_index * 3) % 3) - 1)
                for occurrence in range(daily):
                    span_index += 1
                    # Mix of outcomes: retries dominate, with failures (PR-attributed and
                    # master) and the occasional quarantined-but-failing xfail.
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
                        f"'{nodeid}', 1, '{ts}', '{ts}', '{ts}', 0, '{CI_SERVICE_NAME}', "
                        f"map({', '.join(attr_pairs)}), map({', '.join(resource_pairs)}))"
                    )

    # Local dev has no traces provisioning (prod creates these on the LOGS cluster via HCL);
    # both DDLs are CREATE TABLE IF NOT EXISTS, so this is a no-op on a stack that has them.
    sync_execute(TRACE_SPANS_TABLE_SQL())
    sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

    # Replace only this seed's spans; a real traces table on the same dev stack is untouched.
    # ALTER DELETE (not lightweight DELETE): the table has projections, which reject the latter.
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


def _warehouse_endpoint() -> str:
    # ClickHouse runs in docker, so a localhost object-storage endpoint must be
    # rewritten to the docker host (same approach as the demo data generator).
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

        # Synthetic merged-PR stream so per-team merge timing has realistic daily volume.
        prs.extend(_demo_merged_prs(prs))
        # Append a synthetic multi-push PR (the fixture has none rich enough to show the progression).
        demo_pr, demo_runs = _demo_multi_push(prs, runs)
        prs.append(demo_pr)
        runs.extend(demo_runs)
        # Spread merge times across the window so the cost-per-merge trend has a divisor per bucket.
        _spread_merges(prs, _fixture_anchor(prs, runs))
        # The synthetic stream owns master: the snapshot's own master rows are a dozen SHAs whose
        # scheduled/re-triggered runs span days, which pins the scatter's Y axis at 100h+ and crushes
        # every real duration to the baseline. PR-branch rows stay untouched.
        runs = [run for run in runs if run.get("head_branch") != "master"]
        runs.extend(_demo_master_commits(_fixture_anchor(prs, runs)))

        # Always normalize timestamps to a ClickHouse-friendly format; rebasing is optional.
        shift = timedelta(0) if options["keep_dates"] else self._rebase_delta(prs, runs)
        prs = [self._shift_dates(pr, PR_DATE_FIELDS, shift) for pr in prs]
        runs = [self._shift_dates(run, RUN_DATE_FIELDS, shift) for run in runs]
        if shift:
            self.stdout.write(f"Rebased timestamps forward by {shift}.")

        with team_scope(team.pk):
            credential = get_or_create_datawarehouse_credential(
                team_id=team.pk,
                access_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                access_secret=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            )
            source = self._get_or_create_seed_source(team, prefix)
            self._upsert_schema_table(
                team, source, credential, prefix, PULL_REQUESTS_SCHEMA, PULL_REQUESTS_COLUMNS, map(_flatten_pr, prs)
            )
            self._upsert_schema_table(
                team, source, credential, prefix, WORKFLOW_RUNS_SCHEMA, WORKFLOW_RUNS_COLUMNS, map(_flatten_run, runs)
            )
            # Synthesized demo jobs for the job-level breakdown (see _synthesize_jobs).
            jobs = _synthesize_jobs(runs)
            self._upsert_schema_table(
                team, source, credential, prefix, WORKFLOW_JOBS_SCHEMA, WORKFLOW_JOBS_COLUMNS, jobs
            )
            # Synthetic author→team membership backing the per-team time-to-merge trend.
            self._upsert_schema_table(
                team, source, credential, prefix, TEAM_MEMBERS_SCHEMA, TEAM_MEMBERS_COLUMNS, _team_membership_rows(prs)
            )

        # Per-test CI spans back the flaky-test leaderboard and the team CI health surfaces.
        # Best-effort: a dev stack without the traces table still gets the warehouse seed.
        try:
            span_count = _seed_trace_spans(team)
            self.stdout.write(f"Seeded {span_count} per-test CI spans into trace_spans (flaky/team surfaces).")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Skipped trace_spans seed (traces table unavailable?): {exc}"))

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

    def _get_or_create_seed_source(self, team: Team, prefix: str) -> ExternalDataSource:
        source = ExternalDataSource.objects.filter(
            team=team, source_id=SEED_SOURCE_ID, source_type=ExternalDataSourceType.GITHUB
        ).first()
        if source is None:
            return ExternalDataSource.objects.create(
                team=team,
                source_id=SEED_SOURCE_ID,
                connection_id=SEED_SOURCE_ID,
                status=ExternalDataSource.Status.COMPLETED,
                source_type=ExternalDataSourceType.GITHUB,
                prefix=prefix,
                job_inputs={"repository": SEED_REPOSITORY},
            )
        update_fields = []
        if source.prefix != prefix:
            source.prefix = prefix
            update_fields.append("prefix")
        if (source.job_inputs or {}).get("repository") != SEED_REPOSITORY:
            source.job_inputs = {**(source.job_inputs or {}), "repository": SEED_REPOSITORY}
            update_fields.append("job_inputs")
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
    ) -> None:
        records = list(rows)
        # The materialized table name is exactly what a real sync produces: <prefix>github_<endpoint>.
        table_name = f"{prefix}github_{schema_name}"
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
            existing.format = DataWarehouseTable.TableFormat.CSVWithNames
            existing.url_pattern = url_pattern
            existing.credential = credential
            existing.external_data_source = source
            existing.columns = columns
            existing.options = {**(existing.options or {}), "csv_allow_double_quotes": True}
            existing.deleted = False
            existing.deleted_at = None
            existing.save()
            table = existing
        else:
            table = DataWarehouseTable.objects.create(
                team=team,
                name=table_name,
                format=DataWarehouseTable.TableFormat.CSVWithNames,
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
