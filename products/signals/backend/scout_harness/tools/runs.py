"""Run-history tools: read access to past `SignalScoutRun` rows for the team.

These are the agent's window into what previous runs concluded. Used for best-effort
dedupe (\"have I seen this hypothesis recently?\") and continuity (\"what was I
working on yesterday?\"). Strictly team-scoped — no cross-team reads.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from django.db.models import Q

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
    findings_count: int
    # Tasks (Task, TaskRun) IDs the harness span ran inside, plus the deep-link
    # path ready to render in MCP clients. All three are null on rows older than
    # the linkage capture (predates the runner's `_record_task_linkage` write)
    # or on aborted rows that died before `MultiTurnSession.start()` returned.
    task_id: str | None = None
    task_run_id: str | None = None
    task_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunDetail:
    """Full run row — call `get_run` to fetch this when a `RunSummary` looks relevant."""

    run_id: str
    skill_name: str
    skill_version: int
    status: str
    started_at: str
    completed_at: str | None
    summary: str
    findings: list[Any] = field(default_factory=list)
    hypotheses_considered: list[Any] = field(default_factory=list)
    run_metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # See `RunSummary` — same shape, same null cases.
    task_id: str | None = None
    task_run_id: str | None = None
    task_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_recent_runs(
    *,
    team_id: int,
    text: str | None = None,
    since: datetime | None = None,
    limit: int = DEFAULT_RUN_SEARCH_LIMIT,
) -> list[RunSummary]:
    """Return the most recent runs for a team, newest first.

    `text` is matched ILIKE against `summary` — sufficient until traffic grows enough
    to justify a `tsvector` index (tracked under "Postgres schema indexing" in the
    decisions snapshot). `since` filters on `started_at` for windowed lookups.
    Results are capped at `MAX_RUN_SEARCH_LIMIT`.
    """
    clamped_limit = _clamp_limit(limit)
    qs = SignalScoutRun.objects.filter(team_id=team_id).order_by("-started_at")
    if text:
        qs = qs.filter(Q(summary__icontains=text))
    if since is not None:
        qs = qs.filter(started_at__gte=since)
    qs = qs[:clamped_limit]
    return [_to_summary(row, team_id=team_id) for row in qs]


def get_run(*, team_id: int, run_id: str) -> RunDetail | None:
    """Fetch a single run by ID, scoped to the team. Returns None if not found.

    Team scoping is non-negotiable: a run row from another team must not be
    readable, even if the caller knows the UUID.
    """
    row = SignalScoutRun.objects.filter(team_id=team_id, id=run_id).first()
    if row is None:
        return None
    return _to_detail(row, team_id=team_id)


def _to_summary(row: SignalScoutRun, *, team_id: int) -> RunSummary:
    findings = row.findings or []
    metadata = row.metadata or {}
    task_id = metadata.get("task_id")
    task_run_id = metadata.get("task_run_id")
    return RunSummary(
        run_id=str(row.id),
        skill_name=row.skill_name,
        skill_version=row.skill_version,
        status=row.status,
        started_at=row.started_at.isoformat(),
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
        summary=row.summary or "",
        findings_count=len(findings) if isinstance(findings, list) else 0,
        task_id=task_id,
        task_run_id=task_run_id,
        task_url=_build_task_url(team_id=team_id, task_id=task_id, task_run_id=task_run_id),
    )


def _to_detail(row: SignalScoutRun, *, team_id: int) -> RunDetail:
    metadata = dict(row.metadata or {})
    task_id = metadata.get("task_id")
    task_run_id = metadata.get("task_run_id")
    return RunDetail(
        run_id=str(row.id),
        skill_name=row.skill_name,
        skill_version=row.skill_version,
        status=row.status,
        started_at=row.started_at.isoformat(),
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
        summary=row.summary or "",
        findings=list(row.findings or []),
        hypotheses_considered=list(row.hypotheses_considered or []),
        run_metrics=dict(row.run_metrics or {}),
        metadata=metadata,
        task_id=task_id,
        task_run_id=task_run_id,
        task_url=_build_task_url(team_id=team_id, task_id=task_id, task_run_id=task_run_id),
    )


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
