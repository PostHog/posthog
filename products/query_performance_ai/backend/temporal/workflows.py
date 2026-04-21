"""Weekly + child Temporal workflows for query-performance autoresearch.

``WeeklyAutoresearchWorkflow`` is the entry point for the scheduled weekly
job: it fetches candidate slow queries and fans out to one
``AnalyzeAndFixSlowQueryWorkflow`` per candidate. The child workflow creates
the autoresearch Task, polls for completion, and returns a compact summary
suitable for the Slack post.

The PR-writing phase (spawning a second Task that opens branches + PRs from
the autoresearch artifacts) is intentionally **not** wired here yet — keep
this layer small enough to ship independently of the PR-writing path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import (
    CreateAutoresearchTaskInput,
    CreateAutoresearchTaskOutput,
    CreatePrWritingTaskInput,
    CreatePrWritingTaskOutput,
    FetchCandidatesInput,
    FetchCandidatesOutput,
    PostSlackSummaryInput,
    WaitForTaskInput,
    WaitForTaskOutput,
    _PrLink,
    _ResultSummary,
    _SkippedHunch,
    create_autoresearch_task,
    create_pr_writing_task,
    fetch_slow_query_candidates_activity,
    post_slack_summary,
    wait_for_autoresearch_task,
)

# Match the proxy endpoint's time budget, plus headroom for pi install,
# baseline capture, and the LLM loop. The per-candidate child workflow sets
# its own activity timeout; this is just the overall cap.
DEFAULT_CHILD_WORKFLOW_TIMEOUT = timedelta(hours=2)


# ========================================================== child workflow ==

@dataclass
class AnalyzeAndFixSlowQueryInput:
    posthog_team_id: int
    repository: str
    candidate_json: str  # SlowQueryCandidate JSON-encoded for workflow input safety
    branch: str | None = None


@dataclass
class PrEntry:
    url: str
    kind: str = ""
    improvement_pct: float | None = None


@dataclass
class SkippedHunch:
    hunch: str
    reason: str


@dataclass
class AnalyzeAndFixSlowQueryOutput:
    query_hash: str
    team_id: int
    p95_duration_ms: float
    status: str
    error: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    best_sql: str = ""
    pr_task_id: str | None = None
    pr_run_id: str | None = None
    pr_task_status: str | None = None
    pr_task_error: str | None = None
    prs: list[PrEntry] = field(default_factory=list)
    skipped_hunches: list[SkippedHunch] = field(default_factory=list)


@workflow.defn(name="analyze-and-fix-slow-query")
class AnalyzeAndFixSlowQueryWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> AnalyzeAndFixSlowQueryInput:
        data = json.loads(inputs[0])
        return AnalyzeAndFixSlowQueryInput(
            posthog_team_id=data["posthog_team_id"],
            repository=data["repository"],
            candidate_json=data["candidate_json"],
            branch=data.get("branch"),
        )

    @workflow.run
    async def run(self, input: AnalyzeAndFixSlowQueryInput) -> AnalyzeAndFixSlowQueryOutput:
        from products.query_performance_ai.backend.slow_queries import SlowQueryCandidate

        candidate_data = json.loads(input.candidate_json)
        candidate = SlowQueryCandidate(**candidate_data)

        create_output: CreateAutoresearchTaskOutput = await workflow.execute_activity(
            create_autoresearch_task,
            CreateAutoresearchTaskInput(
                posthog_team_id=input.posthog_team_id,
                repository=input.repository,
                candidate=candidate,
                branch=input.branch,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        wait_output: WaitForTaskOutput = await workflow.execute_activity(
            wait_for_autoresearch_task,
            WaitForTaskInput(task_id=create_output.task_id, run_id=create_output.run_id),
            start_to_close_timeout=DEFAULT_CHILD_WORKFLOW_TIMEOUT,
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        result = AnalyzeAndFixSlowQueryOutput(
            query_hash=candidate.normalized_query_hash,
            team_id=candidate.team_id,
            p95_duration_ms=candidate.p95_duration_ms,
            status=wait_output.status,
            error=wait_output.error_message,
            task_id=create_output.task_id,
            run_id=create_output.run_id,
            best_sql=_extract_best_sql(wait_output.output),
        )

        # Only hand off to PR-writing if the autoresearch run actually
        # completed. A failed campaign gives us nothing useful to ship.
        if wait_output.status == "completed" and isinstance(wait_output.output, dict):
            pr_create, pr_wait = await _run_pr_writing_phase(
                posthog_team_id=input.posthog_team_id,
                repository=input.repository,
                branch=input.branch,
                candidate_team_id=candidate.team_id,
                autoresearch_output=wait_output.output,
            )
            result.pr_task_id = pr_create.task_id
            result.pr_run_id = pr_create.run_id
            result.pr_task_status = pr_wait.status
            result.pr_task_error = pr_wait.error_message
            result.prs, result.skipped_hunches = _parse_pr_report(pr_wait.output)

        return result


# ========================================================= weekly workflow ==

@dataclass
class WeeklyAutoresearchInput:
    posthog_team_id: int
    repository: str = "PostHog/posthog"
    branch: str | None = None
    slack_channel: str = "#team-query-performance"
    window_days: int = 7
    min_duration_ms: int = 5_000
    min_executions: int = 5
    candidate_limit: int = 20


@dataclass
class WeeklyAutoresearchOutput:
    analyzed: int
    succeeded: int
    failed: int
    results: list[AnalyzeAndFixSlowQueryOutput] = field(default_factory=list)


@workflow.defn(name="weekly-autoresearch")
class WeeklyAutoresearchWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> WeeklyAutoresearchInput:
        data = json.loads(inputs[0])
        return WeeklyAutoresearchInput(
            posthog_team_id=data["posthog_team_id"],
            repository=data.get("repository", "PostHog/posthog"),
            branch=data.get("branch"),
            slack_channel=data.get("slack_channel", "#team-query-performance"),
            window_days=data.get("window_days", 7),
            min_duration_ms=data.get("min_duration_ms", 5_000),
            min_executions=data.get("min_executions", 5),
            candidate_limit=data.get("candidate_limit", 20),
        )

    @workflow.run
    async def run(self, input: WeeklyAutoresearchInput) -> WeeklyAutoresearchOutput:
        fetch_output: FetchCandidatesOutput = await workflow.execute_activity(
            fetch_slow_query_candidates_activity,
            FetchCandidatesInput(
                window_days=input.window_days,
                min_duration_ms=input.min_duration_ms,
                min_executions=input.min_executions,
                limit=input.candidate_limit,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        candidates = fetch_output.candidates
        workflow.logger.info(f"Weekly autoresearch: {len(candidates)} candidates")

        # Sequential dispatch for now. Parallel fan-out via asyncio.gather is
        # a drop-in once the sandbox provider can handle the concurrency.
        results: list[AnalyzeAndFixSlowQueryOutput] = []
        for candidate in candidates:
            child_input = AnalyzeAndFixSlowQueryInput(
                posthog_team_id=input.posthog_team_id,
                repository=input.repository,
                candidate_json=json.dumps(candidate.__dict__),
                branch=input.branch,
            )
            try:
                result = await workflow.execute_child_workflow(
                    AnalyzeAndFixSlowQueryWorkflow.run,
                    child_input,
                    id=f"analyze-and-fix-{workflow.info().workflow_id}-{candidate.normalized_query_hash[:12]}",
                    execution_timeout=DEFAULT_CHILD_WORKFLOW_TIMEOUT,
                )
            except Exception as e:
                workflow.logger.warning(
                    f"Child workflow failed for {candidate.normalized_query_hash}: {e}"
                )
                result = AnalyzeAndFixSlowQueryOutput(
                    query_hash=candidate.normalized_query_hash,
                    team_id=candidate.team_id,
                    p95_duration_ms=candidate.p95_duration_ms,
                    status="child_workflow_failed",
                    error=str(e)[:500],
                )
            results.append(result)

        summaries = [
            _ResultSummary(
                query_hash=r.query_hash,
                team_id=r.team_id,
                p95_duration_ms=r.p95_duration_ms,
                status=r.status,
                best_sql_excerpt=r.best_sql[:400] if r.best_sql else "",
                improvement_pct=_best_improvement_pct(r.prs),
                error=r.error,
                pr_task_status=r.pr_task_status,
                prs=[_PrLink(url=pr.url, kind=pr.kind, improvement_pct=pr.improvement_pct) for pr in r.prs],
                skipped_hunches=[_SkippedHunch(hunch=h.hunch, reason=h.reason) for h in r.skipped_hunches],
            )
            for r in results
        ]

        await workflow.execute_activity(
            post_slack_summary,
            PostSlackSummaryInput(
                channel=input.slack_channel,
                analyzed=len(candidates),
                results=summaries,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        succeeded = sum(1 for r in results if r.status == "completed")
        return WeeklyAutoresearchOutput(
            analyzed=len(candidates),
            succeeded=succeeded,
            failed=len(candidates) - succeeded,
            results=results,
        )


# ----------------------------------------------------------------- helpers --

def _best_improvement_pct(prs: list[PrEntry]) -> float | None:
    """Return the largest improvement across all PRs, or None if unknown."""
    known = [pr.improvement_pct for pr in prs if pr.improvement_pct is not None]
    return max(known) if known else None


def _extract_best_sql(output: dict | None) -> str:
    """Pull ``best_sql`` out of a ``TaskRun.output`` blob.

    ``RunAutoresearchCampaignOutput`` is a dataclass serialized via Temporal
    (so JSON-ish); at the Task layer it lands in ``output`` as a dict when
    we persist via ``emit_task_result``. Defensive parsing since that layer
    may evolve.
    """
    if not output or not isinstance(output, dict):
        return ""
    best = output.get("best_sql")
    return best if isinstance(best, str) else ""


async def _run_pr_writing_phase(
    *,
    posthog_team_id: int,
    repository: str,
    branch: str | None,
    candidate_team_id: int,
    autoresearch_output: dict,
) -> tuple[CreatePrWritingTaskOutput, WaitForTaskOutput]:
    pr_input = CreatePrWritingTaskInput(
        posthog_team_id=posthog_team_id,
        repository=repository,
        query_id=autoresearch_output.get("query_id") or "",
        original_sql=autoresearch_output.get("original_sql") or "",
        best_sql=autoresearch_output.get("best_sql") or "",
        baseline_metrics_json=autoresearch_output.get("baseline_metrics_json") or "",
        best_metrics_json=autoresearch_output.get("best_metrics_json") or "",
        last_run_json=autoresearch_output.get("last_run_json") or "",
        operator_hunches=autoresearch_output.get("operator_hunches") or "",
        suggestions=autoresearch_output.get("suggestions") or "",
        lanes=_as_named_list(autoresearch_output.get("lanes")),
        hypotheses=_as_named_list(autoresearch_output.get("hypotheses")),
        reviews=_as_named_list(autoresearch_output.get("reviews")),
        slow_query_team_id=candidate_team_id,
        branch=branch,
    )
    create_output: CreatePrWritingTaskOutput = await workflow.execute_activity(
        create_pr_writing_task,
        pr_input,
        start_to_close_timeout=timedelta(minutes=2),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )

    wait_output: WaitForTaskOutput = await workflow.execute_activity(
        wait_for_autoresearch_task,
        WaitForTaskInput(task_id=create_output.task_id, run_id=create_output.run_id),
        start_to_close_timeout=DEFAULT_CHILD_WORKFLOW_TIMEOUT,
        heartbeat_timeout=timedelta(minutes=2),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    return create_output, wait_output


def _as_named_list(raw: object) -> list[tuple[str, str]]:
    """Coerce a Temporal-deserialized ``list[tuple[str, str]]`` back to tuples.

    Depending on the codec, a serialized list-of-tuples can come back as
    ``list[list[str, str]]`` — normalize so downstream code doesn't care.
    """
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, list | tuple) and len(item) == 2:
            name, contents = item
            if isinstance(name, str) and isinstance(contents, str):
                out.append((name, contents))
    return out


# The agent wraps its final report in a ```json ... ``` block (per the
# template). Pull the last such block out and parse it defensively — the
# PR URLs and skipped-hunch list are the only things we feed into Slack.
_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_pr_report(output: dict | None) -> tuple[list[PrEntry], list[SkippedHunch]]:
    if not isinstance(output, dict):
        return [], []

    # We expect the agent to land the report in a known field; if it ended
    # up embedded in the agent's last message, fall back to regex.
    raw_report = output.get("pr_report") if isinstance(output.get("pr_report"), dict) else None
    if raw_report is None:
        for field_name in ("last_message", "final_message", "summary"):
            text = output.get(field_name)
            if isinstance(text, str):
                matches = _JSON_BLOCK_RE.findall(text)
                if matches:
                    try:
                        raw_report = json.loads(matches[-1])
                    except json.JSONDecodeError:
                        raw_report = None
                    if isinstance(raw_report, dict):
                        break

    if not isinstance(raw_report, dict):
        return [], []

    prs: list[PrEntry] = []
    for entry in raw_report.get("prs") or []:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if not isinstance(url, str) or not url:
            continue
        kind = entry.get("kind") if isinstance(entry.get("kind"), str) else ""
        pct = entry.get("improvement_pct")
        pct = float(pct) if isinstance(pct, int | float) else None
        prs.append(PrEntry(url=url, kind=kind, improvement_pct=pct))

    skipped: list[SkippedHunch] = []
    for entry in raw_report.get("skipped_hunches") or []:
        if not isinstance(entry, dict):
            continue
        hunch = entry.get("hunch")
        reason = entry.get("reason")
        if isinstance(hunch, str) and isinstance(reason, str):
            skipped.append(SkippedHunch(hunch=hunch, reason=reason))

    return prs, skipped
