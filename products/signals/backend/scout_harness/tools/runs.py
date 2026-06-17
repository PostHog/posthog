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
from datetime import datetime
from typing import Any

from products.signals.backend.models import SignalScoutRun
from products.tasks.backend.models import TaskRun

# Defensive caps so a runaway agent loop can't pull thousands of rows in one call.
DEFAULT_RUN_SEARCH_LIMIT = 20
MAX_RUN_SEARCH_LIMIT = 100

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
    started_at: str
    completed_at: str | None
    summary: str
    emitted_count: int = 0
    emitted_finding_ids: list[str] = field(default_factory=list)
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
    started_at: str
    completed_at: str | None
    summary: str
    emitted_count: int = 0
    emitted_finding_ids: list[str] = field(default_factory=list)
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
    keys_only: bool = False,
    content_max_chars: int | None = None,
) -> list[RunSummary]:
    """Return the most recent runs for a team, newest first.

    `date_from` / `date_to` are a half-open time window on `created_at` (the
    bridge-row insert timestamp, which fires right after `MultiTurnSession.start`)
    — `created_at >= date_from` and `created_at < date_to`. Pass `date_to` to walk
    backwards past the result cap on subsequent calls (cursor-style iteration).
    `text` is a case-insensitive substring match on the agent's end-of-run
    `summary` — the primary dedupe path for runs that didn't emit findings.
    `emitted` filters on emit outcome: `True` keeps only runs that emitted at least
    one finding (`emitted_count > 0`), `False` keeps only runs that emitted nothing;
    omit it for both. `skill_name` is an exact-match filter that narrows the dump to
    a single scout — the primary scoping path for a specialist deduping against its
    own past work; pair it with `skill_version` to pin a specific version. Results
    are capped at `MAX_RUN_SEARCH_LIMIT`.

    Result-scoping projections keep a bulk health-assessment scan from pulling every
    run's full `summary` — an unbounded one-paragraph close-out, so a wide scan can
    return up to `summary length × limit` characters of prose the caller doesn't need
    yet:
    - `keys_only=True` blanks each `summary` — return just the lightweight fields
      (`run_id`, `skill_name`, `status`, `failure_reason`, `emitted_count`, …) to scan
      what ran, then re-query the ones worth a full read.
    - `content_max_chars=N` truncates each `summary` to the first `N` characters (a
      preview). Ignored when `keys_only=True`, which already drops the body.
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
        qs = qs.filter(emitted_count__gt=0) if emitted else qs.filter(emitted_count=0)
    if skill_name:
        qs = qs.filter(skill_name=skill_name)
    if skill_version is not None:
        qs = qs.filter(skill_version=skill_version)
    qs = qs[:clamped_limit]
    return [_to_summary(row, team_id=team_id, keys_only=keys_only, content_max_chars=content_max_chars) for row in qs]


def get_run(*, team_id: int, run_id: str) -> RunDetail | None:
    """Fetch a single run by ID, scoped to the team. Returns None if not found.

    Team scoping is non-negotiable: a run row from another team must not be
    readable, even if the caller knows the UUID.
    """
    row = SignalScoutRun.objects.select_related("task_run").filter(team_id=team_id, id=run_id).first()
    if row is None:
        return None
    return _to_detail(row, team_id=team_id)


def _to_summary(
    row: SignalScoutRun, *, team_id: int, keys_only: bool = False, content_max_chars: int | None = None
) -> RunSummary:
    task_run = row.task_run
    task_id = str(task_run.task_id) if task_run is not None else None
    task_run_id = str(task_run.id) if task_run is not None else None
    error, failure_reason = _derive_failure(task_run)
    return RunSummary(
        run_id=str(row.id),
        skill_name=row.skill_name,
        skill_version=row.skill_version,
        status=task_run.status if task_run is not None else "",
        started_at=task_run.created_at.isoformat() if task_run is not None else row.created_at.isoformat(),
        completed_at=task_run.completed_at.isoformat() if task_run is not None and task_run.completed_at else None,
        summary=_project_summary(row.summary, keys_only=keys_only, content_max_chars=content_max_chars),
        emitted_count=row.emitted_count or 0,
        emitted_finding_ids=list(row.emitted_finding_ids or []),
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
    if task_run is None or task_run.status not in (TaskRun.Status.FAILED, TaskRun.Status.CANCELLED):
        return None, None
    error = task_run.error_message or None
    message = (task_run.error_message or "").strip()
    if message:
        return error, message.splitlines()[0][:MAX_FAILURE_REASON_LENGTH]
    fallback = "cancelled" if task_run.status == TaskRun.Status.CANCELLED else "failed (no error message recorded)"
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


def _project_summary(summary: str, *, keys_only: bool, content_max_chars: int | None) -> str:
    """Apply the search projection to a run's `summary`: blank it for `keys_only`,
    or truncate to a preview for `content_max_chars`. A negative max clamps to 0."""
    if keys_only:
        return ""
    if content_max_chars is None:
        return summary
    return summary[: max(content_max_chars, 0)]


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_RUN_SEARCH_LIMIT:
        return MAX_RUN_SEARCH_LIMIT
    return limit
