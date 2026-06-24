"""Report-authoring harness tools: the second emit channel (`emit_report` / `edit_report`).

Where `emit.py` forwards a weak signal through `emit_signal()` and lets the pipeline decide, these
tools let an opted-in scout author or edit a full `SignalReport` directly. They are thin harness
adapters: input validation + the shared preflight gates + attribution, then a call into the sanctioned
`scout_report/` service (`author_scout_report` / `update_scout_report` / `append_report_note`). The
tool never touches `SignalReport` or the embeddings pipeline itself — that boundary lives in the
service (see `scout_harness/AGENTS.md`).

Opt-in is by `allowed_tools`: a scout gets these only if its skill lists `emit_report` / `edit_report`,
intersected with what `tools/__init__.py` re-exports.

Like `emit_finding`, these are NOT idempotent — a retried `emit_report` authors a second report. The
dedup story is `search_scout_reports` (find "the report I made last time") plus a `report:<domain>:<entity>`
scratchpad key the scout maintains; callers must not retry an authoring call that may have succeeded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from asgiref.sync import async_to_sync

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.artefact_schemas import ActionabilityAssessment, ActionabilityChoice
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalScoutRun
from products.signals.backend.scout_harness.tools.emit import (
    SCOUT_SIGNAL_WEIGHT,
    # Shared harness gates/attribution — the report channel applies the same preflight as emit.
    _assert_team_owns_run,
    _preflight_emit_gates,
    _resolve_task_id,
)
from products.signals.backend.scout_report import (
    InvalidScoutReportError,
    ScoutReportSignal,
    append_report_note,
    update_scout_report,
)
from products.signals.backend.scout_report.judge import author_scout_report

logger = logging.getLogger(__name__)

# Defensive caps at the tool boundary (the service caps signals too; these bound caller input early).
MAX_REPORT_TITLE_LENGTH = 300
DEFAULT_REPORT_SEARCH_LIMIT = 20
MAX_REPORT_SEARCH_LIMIT = 100


@dataclass(frozen=True)
class ReportEvidence:
    """One observation backing an authored report — becomes a bound `document_embeddings` signal row."""

    description: str
    source_id: str
    weight: float = SCOUT_SIGNAL_WEIGHT


@dataclass(frozen=True)
class EmitReportResult:
    """Outcome of an `emit_report` call.

    The report is always persisted when not gate-skipped (so the agent can edit/dedup against
    `report_id` even when it was suppressed). `emitted` means it actually surfaced in the inbox
    (status READY or PENDING_INPUT); a safety-suppressed or not-actionable report has emitted=False.
    `skipped_reason` is set only when a preflight gate stopped the call before any report was created.
    """

    report_id: str | None
    status: str | None
    emitted: bool
    skipped_reason: str | None
    safety_explanation: str | None


@dataclass(frozen=True)
class EditReportResult:
    report_id: str
    updated_fields: list[str]
    note_appended: bool


@dataclass(frozen=True)
class ReportSummary:
    """A row from `search_scout_reports` — enough for a scout to recognize and dedup against."""

    report_id: str
    title: str | None
    status: str
    signal_count: int
    created_at: str
    updated_at: str


def _surfaced(status: SignalReport.Status) -> bool:
    return status in (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)


def _build_signals(evidence: list[ReportEvidence]) -> list[ScoutReportSignal]:
    return [ScoutReportSignal(description=e.description, source_id=e.source_id, weight=e.weight) for e in evidence]


def _build_actionability(*, explanation: str, choice: str, already_addressed: bool) -> ActionabilityAssessment:
    try:
        actionability_choice = ActionabilityChoice(choice)
    except ValueError:
        valid = ", ".join(c.value for c in ActionabilityChoice)
        raise InvalidScoutReportError(f"actionability must be one of [{valid}], got {choice!r}")
    return ActionabilityAssessment(
        explanation=explanation, actionability=actionability_choice, already_addressed=already_addressed
    )


def _validate_emit_inputs(title: str, evidence: list[ReportEvidence]) -> None:
    if not title or not title.strip():
        raise InvalidScoutReportError("title must not be empty")
    if len(title) > MAX_REPORT_TITLE_LENGTH:
        raise InvalidScoutReportError(f"title exceeds {MAX_REPORT_TITLE_LENGTH} chars ({len(title)})")
    if not evidence:
        raise InvalidScoutReportError("emit_report needs at least one piece of evidence")


async def emit_report(
    *,
    team: Team,
    run: SignalScoutRun,
    title: str,
    summary: str,
    evidence: list[ReportEvidence],
    actionability_explanation: str,
    actionability: str,
    already_addressed: bool = False,
) -> EmitReportResult:
    """Author a full report: judge for safety, then persist at the judged status. Async entry (the
    safety judge is an LLM call); routes the sync DB gates through `database_sync_to_async`."""
    _assert_team_owns_run(team, run)
    _validate_emit_inputs(title, evidence)
    signals = _build_signals(evidence)
    actionability_assessment = _build_actionability(
        explanation=actionability_explanation, choice=actionability, already_addressed=already_addressed
    )

    preflight = await database_sync_to_async(_preflight_emit_gates, thread_sensitive=False)(team, run)
    if preflight is not None:
        logger.warning("signals_scout.emit_report: skipped %s", preflight, extra={"skipped_reason": preflight})
        return EmitReportResult(
            report_id=None, status=None, emitted=False, skipped_reason=preflight, safety_explanation=None
        )

    task_id = await database_sync_to_async(_resolve_task_id, thread_sensitive=False)(run)
    attribution = ArtefactAttribution.from_task(task_id) if task_id is not None else ArtefactAttribution.system()
    persisted, judgement = await author_scout_report(
        team_id=team.id,
        title=title,
        summary=summary,
        signals=signals,
        actionability=actionability_assessment,
        attribution=attribution,
        run=run,
    )
    logger.info(
        "signals_scout.emit_report: authored",
        extra={"team_id": team.id, "report_id": persisted.report_id, "status": judgement.status},
    )
    return EmitReportResult(
        report_id=persisted.report_id,
        status=judgement.status,
        emitted=_surfaced(judgement.status),
        skipped_reason=None,
        safety_explanation=judgement.safety.explanation,
    )


def emit_report_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    title: str,
    summary: str,
    evidence: list[ReportEvidence],
    actionability_explanation: str,
    actionability: str,
    already_addressed: bool = False,
) -> EmitReportResult:
    """Sync entry used by the DRF view path. Same behavior as `emit_report`."""
    return async_to_sync(emit_report)(
        team=team,
        run=run,
        title=title,
        summary=summary,
        evidence=evidence,
        actionability_explanation=actionability_explanation,
        actionability=actionability,
        already_addressed=already_addressed,
    )


async def edit_report(
    *,
    team: Team,
    run: SignalScoutRun,
    report_id: str,
    title: str | None = None,
    summary: str | None = None,
    append_note: str | None = None,
) -> EditReportResult:
    """Edit an existing inbox report: rewrite title/summary and/or append a note. Team-scoped
    fail-closed in the service. Async entry; routes the sync service calls through the thread pool."""
    _assert_team_owns_run(team, run)
    if title is None and summary is None and append_note is None:
        raise InvalidScoutReportError("edit_report needs at least one of title, summary, append_note")

    preflight = await database_sync_to_async(_preflight_emit_gates, thread_sensitive=False)(team, run)
    if preflight is not None:
        raise InvalidScoutReportError(f"edit_report blocked by preflight gate: {preflight}")

    task_id = await database_sync_to_async(_resolve_task_id, thread_sensitive=False)(run)
    attribution = ArtefactAttribution.from_task(task_id) if task_id is not None else ArtefactAttribution.system()

    updated_fields: list[str] = []
    if title is not None or summary is not None:
        updated_fields = await database_sync_to_async(update_scout_report, thread_sensitive=False)(
            team_id=team.id, report_id=report_id, title=title, summary=summary
        )
    note_appended = False
    if append_note is not None:
        await database_sync_to_async(append_report_note, thread_sensitive=False)(
            team_id=team.id, report_id=report_id, note=append_note, attribution=attribution, author=run.skill_name
        )
        note_appended = True

    logger.info(
        "signals_scout.edit_report: edited",
        extra={"team_id": team.id, "report_id": report_id, "fields": updated_fields, "note": note_appended},
    )
    return EditReportResult(report_id=report_id, updated_fields=updated_fields, note_appended=note_appended)


def edit_report_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    report_id: str,
    title: str | None = None,
    summary: str | None = None,
    append_note: str | None = None,
) -> EditReportResult:
    """Sync entry used by the DRF view path. Same behavior as `edit_report`."""
    return async_to_sync(edit_report)(
        team=team, run=run, report_id=report_id, title=title, summary=summary, append_note=append_note
    )


def search_scout_reports(
    *,
    team: Team,
    query: str | None = None,
    statuses: list[str] | None = None,
    limit: int = DEFAULT_REPORT_SEARCH_LIMIT,
) -> list[ReportSummary]:
    """Read tool: list the team's existing reports so a scout can find "the report I made last time"
    and reconcile against it instead of authoring a duplicate (the dedup half of the feature).

    Read-only and team-scoped (the canonical parent team). `query` is a case-insensitive title
    substring; `statuses` filters to specific lifecycle states. Newest-updated first.
    """
    limit = max(1, min(limit, MAX_REPORT_SEARCH_LIMIT))
    qs = SignalReport.objects.filter(team_id=team.id)
    if query:
        qs = qs.filter(title__icontains=query)
    if statuses:
        qs = qs.filter(status__in=statuses)
    qs = qs.order_by("-updated_at")[:limit]
    return [
        ReportSummary(
            report_id=str(report.id),
            title=report.title,
            status=report.status,
            signal_count=report.signal_count,
            created_at=report.created_at.isoformat(),
            updated_at=report.updated_at.isoformat(),
        )
        for report in qs
    ]


async def search_scout_reports_async(
    *,
    team: Team,
    query: str | None = None,
    statuses: list[str] | None = None,
    limit: int = DEFAULT_REPORT_SEARCH_LIMIT,
) -> list[ReportSummary]:
    """Async wrapper for the runner inside Temporal (don't block the event loop on the DB read)."""
    return await database_sync_to_async(search_scout_reports, thread_sensitive=False)(
        team=team, query=query, statuses=statuses, limit=limit
    )
