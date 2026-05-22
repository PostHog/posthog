"""Run-history tools: read access to past `SignalScoutRun` rows for the team.

These are the agent's window into what previous runs concluded. Used for best-effort
dedupe ("have I seen this hypothesis recently?") and continuity ("what was I
working on yesterday?"). Strictly team-scoped — no cross-team reads.

`SignalScoutRun` is a thin bridge to `tasks.TaskRun`: status, timestamps, and
error all flow from the linked TaskRun via `select_related("task_run")`. The
only scout-owned content on the row itself is `summary` — the one-paragraph
close-out the agent emits at end_turn, used as the dedupe key for runs that
didn't emit any findings (and so left no `Signal` row to query against).
Findings are recoverable as emitted `Signal` rows keyed by
`source_id = run:<run_id>:finding:<finding_id>`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from products.signals.backend.models import SignalScoutRun

# Defensive caps so a runaway agent loop can't pull thousands of rows in one call.
DEFAULT_RUN_SEARCH_LIMIT = 20
MAX_RUN_SEARCH_LIMIT = 100


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
    task_id: str | None = None
    task_run_id: str | None = None
    task_url: str | None = None

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
    task_id: str | None = None
    task_run_id: str | None = None
    task_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_recent_runs(
    *,
    team_id: int,
    since: datetime | None = None,
    text: str | None = None,
    limit: int = DEFAULT_RUN_SEARCH_LIMIT,
) -> list[RunSummary]:
    """Return the most recent runs for a team, newest first.

    `since` filters on `created_at` (the bridge-row insert timestamp, which fires
    right after `MultiTurnSession.start`). `text` is a case-insensitive substring
    match on the agent's end-of-run `summary` — the primary dedupe path for runs
    that didn't emit findings. Results are capped at `MAX_RUN_SEARCH_LIMIT`.
    """
    clamped_limit = _clamp_limit(limit)
    qs = SignalScoutRun.objects.filter(team_id=team_id).select_related("task_run").order_by("-created_at")
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    if text:
        qs = qs.filter(summary__icontains=text)
    qs = qs[:clamped_limit]
    return [_to_summary(row, team_id=team_id) for row in qs]


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
    return RunSummary(
        run_id=str(row.id),
        skill_name=row.skill_name,
        skill_version=row.skill_version,
        status=task_run.status if task_run is not None else "",
        started_at=task_run.created_at.isoformat() if task_run is not None else row.created_at.isoformat(),
        completed_at=task_run.completed_at.isoformat() if task_run is not None and task_run.completed_at else None,
        summary=row.summary,
        task_id=task_id,
        task_run_id=task_run_id,
        task_url=_build_task_url(team_id=team_id, task_id=task_id, task_run_id=task_run_id),
    )


def _to_detail(row: SignalScoutRun, *, team_id: int) -> RunDetail:
    summary = _to_summary(row, team_id=team_id)
    return RunDetail(**asdict(summary))


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
