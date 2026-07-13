"""Run-history tools: read access to past `SignalScoutRun` rows for the team.

These are the agent's window into what previous runs concluded. Used for best-effort
dedupe ("have I seen this hypothesis recently?") and continuity ("what was I
working on yesterday?"). Strictly team-scoped — no cross-team reads.

`SignalScoutRun` is a thin bridge to `tasks.TaskRun`: status, timestamps, and
error all flow from the linked TaskRun via `select_related("task_run")`. The
scout-owned content on the row itself is `summary` — the one-paragraph close-out
the agent emits at end_turn, used as the dedupe key for runs that didn't emit any
findings (and so left no `Signal` row to query against) — plus the
`emitted_count` / `emitted_finding_ids` emit tally bumped post-success by
`emit_finding`. Findings are recoverable as emitted `Signal` rows keyed by
`source_id = run:<run_id>:finding:<finding_id>`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from products.signals.backend.models import SignalScoutRun
from products.tasks.backend.facade import api as tasks_facade

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

# Defensive caps so a runaway agent loop can't pull thousands of rows in one call.
DEFAULT_RUN_SEARCH_LIMIT = 20
MAX_RUN_SEARCH_LIMIT = 100

# The "Scout findings" callout summary tallies findings over a fixed lookback window. The default
# window and the run cap mirror the cloud/desktop frontend (`SCOUT_RUNS_WINDOW_HOURS = 72` /
# `MAX_FLEET_EMITTED_RUNS = 120`) so the callout count matches the set the findings page renders;
# the max window bounds a pathological lookback.
DEFAULT_FINDINGS_WINDOW_HOURS = 72
MAX_FINDINGS_WINDOW_HOURS = 168
FLEET_FINDINGS_SUMMARY_RUN_CAP = 120

# `failure_reason` is the concise, list-safe derived signal; `error` carries the full
# `TaskRun.error_message`. Bound the derived reason so it stays cheap to scan in bulk.
MAX_FAILURE_REASON_LENGTH = 500


@dataclass(frozen=True)
class RunSummary:
    """Lightweight projection of a run row — what's needed to scan and pick one."""

    run_id: str
    skill_name: str
    skill_version: int
    status: str
    # `created_at` is the bridge row's own timestamp — the field `search_recent_runs`
    # filters and orders on, hence the cursor key for walking past the result cap.
    # `started_at` is the linked TaskRun's creation time and can differ slightly.
    created_at: str
    started_at: str
    completed_at: str | None
    summary: str
    emitted_count: int = 0
    emitted_finding_ids: list[str] = field(default_factory=list)
    # Reports authored via the `emit_report` channel — separate from `emitted_count`/`emitted_finding_ids`
    # (which count weak `emit_signal` findings), so a run that only authored a report still reads as
    # having emitted something.
    emitted_report_ids: list[str] = field(default_factory=list)
    # Reports this run *mutated* via the `edit_report` channel (rewrote title/summary and/or appended a
    # note), deduped. Distinct from `emitted_report_ids`: edit can target any inbox report, so these are
    # generally not reports the run authored. Lets "which reports did this run edit?" be a column lookup.
    edited_report_ids: list[str] = field(default_factory=list)
    task_id: str | None = None
    task_run_id: str | None = None
    task_url: str | None = None
    # `error` is the full `TaskRun.error_message`; `failure_reason` is the concise derived
    # one-liner. Both are surfaced only for failed/cancelled runs — null otherwise (incl. success).
    error: str | None = None
    failure_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunDetail:
    """Full run row — call `get_run` to fetch this when a `RunSummary` looks relevant.

    Same fields as `RunSummary` today; kept distinct so future detail-only
    extensions (linked Signal rows, LLMA token-cost join) can land here without
    bloating the list projection.
    """

    run_id: str
    skill_name: str
    skill_version: int
    status: str
    created_at: str
    started_at: str
    completed_at: str | None
    summary: str
    emitted_count: int = 0
    emitted_finding_ids: list[str] = field(default_factory=list)
    # Reports authored via the `emit_report` channel — separate from `emitted_count`/`emitted_finding_ids`
    # (which count weak `emit_signal` findings), so a run that only authored a report still reads as
    # having emitted something.
    emitted_report_ids: list[str] = field(default_factory=list)
    # Reports this run *mutated* via the `edit_report` channel (rewrote title/summary and/or appended a
    # note), deduped. Distinct from `emitted_report_ids`: edit can target any inbox report, so these are
    # generally not reports the run authored. Lets "which reports did this run edit?" be a column lookup.
    edited_report_ids: list[str] = field(default_factory=list)
    task_id: str | None = None
    task_run_id: str | None = None
    task_url: str | None = None
    # `error` is the full `TaskRun.error_message`; `failure_reason` is the concise derived
    # one-liner. Both are surfaced only for failed/cancelled runs — null otherwise (incl. success).
    error: str | None = None
    failure_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_recent_runs(
    *,
    team_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    text: str | None = None,
    emitted: bool | None = None,
    skill_name: str | None = None,
    skill_version: int | None = None,
    limit: int = DEFAULT_RUN_SEARCH_LIMIT,
) -> list[RunSummary]:
    """Return the most recent runs for a team, newest first.

    `date_from` / `date_to` are a half-open time window on `created_at` (the
    bridge-row insert timestamp, which fires right after `MultiTurnSession.start`)
    — `created_at >= date_from` and `created_at < date_to`. Pass `date_to` to walk
    backwards past the result cap on subsequent calls (cursor-style iteration).
    `text` is a case-insensitive substring match on the agent's end-of-run
    `summary` — the primary dedupe path for runs that didn't emit findings.
    `emitted` filters on emit outcome: `True` keeps only runs that emitted at least
    one finding *or* authored a report (`emitted_count > 0` or a non-empty
    `emitted_report_ids`), `False` keeps only runs that emitted nothing on either
    channel; omit it for both. `skill_name` is an exact-match filter that narrows the dump to
    a single scout — the primary scoping path for a specialist deduping against its
    own past work; pair it with `skill_version` to pin a specific version. Results
    are capped at `MAX_RUN_SEARCH_LIMIT`.
    """
    clamped_limit = _clamp_limit(limit)
    qs = SignalScoutRun.objects.filter(team_id=team_id).select_related("task_run").order_by("-created_at")
    if date_from is not None:
        qs = qs.filter(created_at__gte=date_from)
    if date_to is not None:
        qs = qs.filter(created_at__lt=date_to)
    if text:
        qs = qs.filter(summary__icontains=text)
    if emitted is not None:
        # A run "emitted" if it surfaced a weak finding (emitted_count) or authored a report
        # (emitted_report_ids). Treat null/[] report lists as empty for the negative case.
        emitted_a_report = ~Q(emitted_report_ids=[]) & ~Q(emitted_report_ids__isnull=True)
        if emitted:
            qs = qs.filter(Q(emitted_count__gt=0) | emitted_a_report)
        else:
            qs = qs.filter(emitted_count=0).filter(Q(emitted_report_ids=[]) | Q(emitted_report_ids__isnull=True))
    if skill_name:
        qs = qs.filter(skill_name=skill_name)
    if skill_version is not None:
        qs = qs.filter(skill_version=skill_version)
    qs = qs[:clamped_limit]
    return [_to_summary(row, team_id=team_id) for row in qs]


@dataclass(frozen=True)
class FleetFindingsSummary:
    """Cheap fleet-wide tally of recently emitted findings — what the "Scout findings" callout reads."""

    count: int
    scout_count: int
    latest_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def fleet_findings_summary(*, team_id: int, window_hours: int = DEFAULT_FINDINGS_WINDOW_HOURS) -> FleetFindingsSummary:
    """Summarise the findings the fleet emitted in the recent window, in a single query.

    Replaces the client-side tally that walked the whole paginated runs window just to count
    findings for the callout. Counts only emitted runs (`emitted_count > 0`) whose `created_at`
    falls in the last `window_hours`, capped to the most recent `FLEET_FINDINGS_SUMMARY_RUN_CAP`
    runs by completion time (falling back to creation) — the same set the findings page renders,
    so the callout can't over-advertise. Returns the finding total (sum of `emitted_count`), the
    distinct scout count, and the most recent emission time.
    """
    window_hours = max(1, min(window_hours, MAX_FINDINGS_WINDOW_HOURS))
    window_start = timezone.now() - timedelta(hours=window_hours)
    # Order by completion (fall back to creation) so the cap keeps the *most recently emitted* runs,
    # matching the frontend's `completed_at ?? created_at` sort; `-id` tie-breaks on the time-ordered PK.
    rows = (
        SignalScoutRun.objects.filter(team_id=team_id, created_at__gte=window_start, emitted_count__gt=0)
        .annotate(_emitted_at=Coalesce("task_run__completed_at", "created_at"))
        .order_by("-_emitted_at", "-id")
        .values_list("emitted_count", "skill_name", "_emitted_at")[:FLEET_FINDINGS_SUMMARY_RUN_CAP]
    )
    count = 0
    scouts: set[str] = set()
    latest_at: datetime | None = None
    for emitted_count, skill_name, emitted_at in rows:
        count += emitted_count or 0
        scouts.add(skill_name)
        if emitted_at is not None and (latest_at is None or emitted_at > latest_at):
            latest_at = emitted_at
    return FleetFindingsSummary(
        count=count,
        scout_count=len(scouts),
        latest_at=latest_at.isoformat() if latest_at is not None else None,
    )


def get_run(*, team_id: int, run_id: str) -> RunDetail | None:
    """Fetch a single run by ID, scoped to the team. Returns None if not found.

    Team scoping is non-negotiable: a run row from another team must not be
    readable, even if the caller knows the UUID.
    """
    row = SignalScoutRun.objects.select_related("task_run").filter(team_id=team_id, id=run_id).first()
    if row is None:
        return None
    return _to_detail(row, team_id=team_id)


def _to_summary(row: SignalScoutRun, *, team_id: int) -> RunSummary:
    task_run = row.task_run
    task_id = str(task_run.task_id) if task_run is not None else None
    task_run_id = str(task_run.id) if task_run is not None else None
    error, failure_reason = _derive_failure(task_run)
    return RunSummary(
        run_id=str(row.id),
        skill_name=row.skill_name,
        skill_version=row.skill_version,
        status=task_run.status if task_run is not None else "",
        created_at=row.created_at.isoformat(),
        started_at=task_run.created_at.isoformat() if task_run is not None else row.created_at.isoformat(),
        completed_at=task_run.completed_at.isoformat() if task_run is not None and task_run.completed_at else None,
        summary=row.summary,
        emitted_count=row.emitted_count or 0,
        emitted_finding_ids=list(row.emitted_finding_ids or []),
        emitted_report_ids=list(row.emitted_report_ids or []),
        edited_report_ids=list(row.edited_report_ids or []),
        task_id=task_id,
        task_run_id=task_run_id,
        task_url=_build_task_url(team_id=team_id, task_id=task_id, task_run_id=task_run_id),
        error=error,
        failure_reason=failure_reason,
    )


def _to_detail(row: SignalScoutRun, *, team_id: int) -> RunDetail:
    summary = _to_summary(row, team_id=team_id)
    return RunDetail(**asdict(summary))


def _derive_failure(task_run: TaskRun | None) -> tuple[str | None, str | None]:
    """Return `(error, failure_reason)` for a run — both None unless it failed/cancelled.

    Gating both on terminal-failure status keeps a non-null `error` a genuine failure signal:
    a stray `error_message` left on a run that reached COMPLETED is not surfaced, so the
    "both null on success" contract holds. `error` is the full `TaskRun.error_message`;
    `failure_reason` is the concise list-safe derived one-liner — the first line of the message
    bounded to `MAX_FAILURE_REASON_LENGTH`, or a status-derived fallback when none was recorded.
    `failure_reason` is what a bulk run scan reads to see *why* a run emitted nothing without
    pulling every stack trace.
    """
    if task_run is None or task_run.status not in (
        tasks_facade.TaskRunStatus.FAILED,
        tasks_facade.TaskRunStatus.CANCELLED,
    ):
        return None, None
    error = task_run.error_message or None
    message = (task_run.error_message or "").strip()
    if message:
        return error, message.splitlines()[0][:MAX_FAILURE_REASON_LENGTH]
    fallback = (
        "cancelled" if task_run.status == tasks_facade.TaskRunStatus.CANCELLED else "failed (no error message recorded)"
    )
    return error, fallback


def _build_task_url(*, team_id: int, task_id: str | None, task_run_id: str | None) -> str | None:
    """Build the relative Tasks UI deep-link, or None if the linkage isn't captured.

    Path shape follows the project URL convention (no host, includes `/project/{id}/`
    for the front-end router; MCP clients render it against their own host). Both
    IDs must be present — a task without a run id can't be opened on the right tab.
    """
    if not task_id or not task_run_id:
        return None
    return f"/project/{team_id}/tasks/{task_id}?runId={task_run_id}"


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_RUN_SEARCH_LIMIT:
        return MAX_RUN_SEARCH_LIMIT
    return limit
