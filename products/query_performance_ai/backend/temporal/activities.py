"""Activities for the weekly query-performance autoresearch workflow.

Everything here runs *outside* a sandbox — they're DB + ClickHouse + Slack
operations with trusted service credentials. The sandbox-facing work is in
``products/tasks/backend/temporal/process_task/activities/run_autoresearch_campaign.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from temporalio import activity

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.query_performance_ai.backend.prompts import render_code_handoff_prompt
from products.query_performance_ai.backend.slow_queries import (
    DEFAULT_LIMIT,
    DEFAULT_MIN_DURATION_MS,
    DEFAULT_MIN_EXECUTIONS,
    DEFAULT_WINDOW_DAYS,
    SlowQueryCandidate,
    fetch_slow_query_candidates,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------ fetch step --

@dataclass
class FetchCandidatesInput:
    cluster: str = "posthog"
    window_days: int = DEFAULT_WINDOW_DAYS
    min_duration_ms: int = DEFAULT_MIN_DURATION_MS
    min_executions: int = DEFAULT_MIN_EXECUTIONS
    limit: int = DEFAULT_LIMIT


@dataclass
class FetchCandidatesOutput:
    candidates: list[SlowQueryCandidate] = field(default_factory=list)


@activity.defn
async def fetch_slow_query_candidates_activity(
    input: FetchCandidatesInput,
) -> FetchCandidatesOutput:
    """Run the ``system.query_log`` aggregation off the main thread."""
    candidates = await sync_to_async(fetch_slow_query_candidates)(
        cluster=input.cluster,
        window_days=input.window_days,
        min_duration_ms=input.min_duration_ms,
        min_executions=input.min_executions,
        limit=input.limit,
    )
    return FetchCandidatesOutput(candidates=candidates)


# -------------------------------------------- create autoresearch task --

@dataclass
class CreateAutoresearchTaskInput:
    """Creates one ``mode=autoresearch_campaign`` Task per candidate.

    The description is JSON-encoded so the campaign activity can parse it
    back into ``{sql, query_id}`` — see ``_parse_task_description`` in the
    activity.
    """

    posthog_team_id: int
    repository: str
    candidate: SlowQueryCandidate
    branch: str | None = None


@dataclass
class CreateAutoresearchTaskOutput:
    task_id: str
    run_id: str


@activity.defn
async def create_autoresearch_task(input: CreateAutoresearchTaskInput) -> CreateAutoresearchTaskOutput:
    # Import inline to avoid model imports at workflow-class load time.
    from products.tasks.backend.models import Task

    team, user = await sync_to_async(_resolve_team_and_owner)(input.posthog_team_id)

    description = json.dumps(
        {
            "sql": input.candidate.sample_sql,
            "query_id": input.candidate.normalized_query_hash,
            "team_id": input.candidate.team_id,
            "baseline": {
                "p95_duration_ms": input.candidate.p95_duration_ms,
                "executions": input.candidate.executions,
                "total_read_bytes": input.candidate.total_read_bytes,
                "sample_query_id": input.candidate.sample_query_id,
            },
        }
    )

    title = f"Autoresearch: {input.candidate.normalized_query_hash[:12]} (team {input.candidate.team_id})"

    def _create() -> Task:
        return Task.create_and_run(
            team=team,
            title=title,
            description=description,
            origin_product=Task.OriginProduct.QUERY_PERFORMANCE,
            user_id=user.id,
            repository=input.repository,
            create_pr=False,
            mode="autoresearch_campaign",
            posthog_mcp_scopes=["clickhouse_perf:test_read"],
            branch=input.branch,
        )

    task = await sync_to_async(_create)()

    # Task.create_and_run creates the first TaskRun synchronously; grab it.
    run = await sync_to_async(_latest_run_id)(task.id)
    return CreateAutoresearchTaskOutput(task_id=str(task.id), run_id=str(run))


# -------------------------------------------- create PR-writing task --

@dataclass
class CreatePrWritingTaskInput:
    """Kick off the PR-writing Task that turns autoresearch results into PRs.

    The prompt embeds every artifact the campaign produced, including
    operator hunches the campaign couldn't action. The agent sandbox gets
    **both** test and prod proxy scopes so it can verify fixes against real
    data — the autoresearch sandbox only had test scope, so this is the
    only place in the pipeline with prod reach.
    """

    posthog_team_id: int
    repository: str
    query_id: str
    original_sql: str
    best_sql: str
    baseline_metrics_json: str
    best_metrics_json: str
    last_run_json: str
    operator_hunches: str
    suggestions: str
    lanes: list[tuple[str, str]]
    hypotheses: list[tuple[str, str]]
    reviews: list[tuple[str, str]]
    slow_query_team_id: int
    branch: str | None = None


@dataclass
class CreatePrWritingTaskOutput:
    task_id: str
    run_id: str


@activity.defn
async def create_pr_writing_task(input: CreatePrWritingTaskInput) -> CreatePrWritingTaskOutput:
    from products.tasks.backend.models import Task

    team, user = await sync_to_async(_resolve_team_and_owner)(input.posthog_team_id)

    prompt = render_code_handoff_prompt(
        query_id=input.query_id,
        team_id=input.slow_query_team_id,
        original_sql=input.original_sql,
        best_sql=input.best_sql,
        baseline_metrics_json=input.baseline_metrics_json,
        best_metrics_json=input.best_metrics_json,
        last_run_json=input.last_run_json,
        operator_hunches=input.operator_hunches,
        suggestions=input.suggestions,
        lanes=input.lanes,
        hypotheses=input.hypotheses,
        reviews=input.reviews,
    )

    title = f"Query-perf PRs: {input.query_id[:12]} (team {input.slow_query_team_id})"

    def _create() -> Task:
        return Task.create_and_run(
            team=team,
            title=title,
            description=prompt,
            origin_product=Task.OriginProduct.QUERY_PERFORMANCE,
            user_id=user.id,
            repository=input.repository,
            create_pr=True,
            mode="background",
            posthog_mcp_scopes=[
                "clickhouse_perf:test_read",
                "clickhouse_perf:prod_read",
                "query:read",
                "insight:read",
                "llm_gateway:read",
            ],
            branch=input.branch,
        )

    task = await sync_to_async(_create)()
    run = await sync_to_async(_latest_run_id)(task.id)
    return CreatePrWritingTaskOutput(task_id=str(task.id), run_id=str(run))


# ------------------------------------------------------------- wait step --

@dataclass
class WaitForTaskInput:
    task_id: str
    run_id: str
    poll_interval_s: int = 30


@dataclass
class WaitForTaskOutput:
    status: str
    error_message: str | None = None
    output: dict[str, Any] | None = None


_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@activity.defn
async def wait_for_autoresearch_task(input: WaitForTaskInput) -> WaitForTaskOutput:
    """Poll the TaskRun until it hits a terminal state.

    Heartbeats every poll so Temporal keeps the activity alive for the full
    campaign duration (up to the activity's start-to-close timeout).
    """
    from products.tasks.backend.models import TaskRun

    while True:
        activity.heartbeat()
        row = await sync_to_async(_fetch_run_state)(input.run_id)
        if row is None:
            return WaitForTaskOutput(status="missing", error_message=f"TaskRun {input.run_id} not found")
        status, error_message, output = row
        if status in _TERMINAL_STATUSES:
            return WaitForTaskOutput(status=status, error_message=error_message, output=output)
        await asyncio.sleep(input.poll_interval_s)


# ------------------------------------------------------------ slack step --

@dataclass
class _PrLink:
    url: str
    kind: str = ""
    improvement_pct: float | None = None


@dataclass
class _SkippedHunch:
    hunch: str
    reason: str


@dataclass
class _ResultSummary:
    query_hash: str
    team_id: int
    p95_duration_ms: float
    status: str
    best_sql_excerpt: str = ""
    improvement_pct: float | None = None
    error: str | None = None
    pr_task_status: str | None = None
    prs: list[_PrLink] = field(default_factory=list)
    skipped_hunches: list[_SkippedHunch] = field(default_factory=list)


@dataclass
class PostSlackSummaryInput:
    channel: str
    analyzed: int
    results: list[_ResultSummary] = field(default_factory=list)


@activity.defn
async def post_slack_summary(input: PostSlackSummaryInput) -> None:
    """Post the weekly summary to the configured Slack channel.

    Uses PostHog's own internal team's SlackIntegration — the team id lives
    in ``settings.POSTHOG_INTERNAL_TEAM_ID``. If it's unset or the integration
    is missing, we log + silently skip: the weekly run's artifacts are still
    available in the Task records.
    """
    internal_team_id = getattr(settings, "POSTHOG_INTERNAL_TEAM_ID", None)
    if not internal_team_id:
        logger.warning("POSTHOG_INTERNAL_TEAM_ID unset; skipping slack summary")
        return

    blocks = _build_summary_blocks(input)

    await sync_to_async(_post_blocks_to_slack)(internal_team_id, input.channel, blocks)


# ----------------------------------------------------------------- helpers --

def _resolve_team_and_owner(team_id: int) -> tuple[Team, Any]:
    team = Team.objects.select_related("organization").get(id=team_id)
    membership = OrganizationMembership.objects.filter(organization=team.organization).order_by("id").first()
    if not membership:
        raise RuntimeError(f"No users on organization {team.organization_id}; cannot create task")
    return team, membership.user


def _latest_run_id(task_id: str) -> str:
    from products.tasks.backend.models import TaskRun

    run = TaskRun.objects.filter(task_id=task_id).order_by("-created_at").values_list("id", flat=True).first()
    if not run:
        raise RuntimeError(f"No TaskRun created for task {task_id}")
    return str(run)


def _fetch_run_state(run_id: str) -> tuple[str, str | None, dict | None] | None:
    from products.tasks.backend.models import TaskRun

    try:
        run = TaskRun.objects.get(id=run_id)
    except TaskRun.DoesNotExist:
        return None
    return run.status, run.error_message, run.output


def _build_summary_blocks(summary: PostSlackSummaryInput) -> list[dict]:
    succeeded = sum(1 for r in summary.results if r.status == "completed")
    failed = summary.analyzed - succeeded
    header = f"*Weekly query-perf autoresearch*  —  analyzed {summary.analyzed}, succeeded {succeeded}, failed {failed}"

    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": header}}]

    for result in summary.results:
        bits = [
            f"*Query* `{result.query_hash[:12]}` (team `{result.team_id}`)",
            f"baseline p95: `{result.p95_duration_ms:.0f}ms`",
            f"autoresearch: `{result.status}`",
        ]
        if result.pr_task_status:
            bits.append(f"PR pass: `{result.pr_task_status}`")
        if result.improvement_pct is not None:
            bits.append(f"best improvement: `{result.improvement_pct:.1f}%`")
        if result.error:
            bits.append(f"error: `{result.error[:200]}`")
        if result.prs:
            pr_lines = []
            for pr in result.prs:
                suffix = f" (+{pr.improvement_pct:.0f}%)" if pr.improvement_pct is not None else ""
                kind = f" [{pr.kind}]" if pr.kind else ""
                pr_lines.append(f"• <{pr.url}|{pr.url}>{kind}{suffix}")
            bits.append("PRs:\n" + "\n".join(pr_lines))
        if result.skipped_hunches:
            skipped_lines = [f"• {h.hunch} — {h.reason}" for h in result.skipped_hunches]
            bits.append("Hunches not actioned:\n" + "\n".join(skipped_lines))
        if result.best_sql_excerpt:
            bits.append(f"best sql excerpt: ```{result.best_sql_excerpt[:400]}```")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(bits)}})

    return blocks


def _post_blocks_to_slack(team_id: int, channel: str, blocks: list[dict]) -> None:
    # Import inline so this module is importable in environments that don't
    # have slack_sdk installed (e.g., during tests of the non-slack path).
    from ee.tasks.subscriptions.slack_subscriptions import get_slack_integration_for_team

    integration = get_slack_integration_for_team(team_id)
    if not integration:
        logger.warning("No SlackIntegration for team %s; skipping slack post", team_id)
        return
    integration.client.chat_postMessage(channel=channel, blocks=blocks, text="Weekly query-perf autoresearch summary")
