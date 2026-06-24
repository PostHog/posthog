"""Report-authoring harness tools: the second emit channel (`emit_report` / `edit_report`).

Where `emit.py` forwards a weak signal through `emit_signal()` and lets the pipeline decide, these
tools let an opted-in scout author or edit a full `SignalReport` directly. They are thin harness
adapters: input validation + the shared preflight gates + attribution, then calls into the sanctioned
`scout_report/` service (`judge_scout_report` + `create_scout_report` for emit; `update_scout_report` /
`append_report_note` for edit). The tool never touches `SignalReport` or the embeddings pipeline itself
— that boundary lives in the service (see `scout_harness/AGENTS.md`).

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
    create_scout_report,
    update_scout_report,
)
from products.signals.backend.scout_report.judge import ScoutReportJudgement, judge_scout_report

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


def _gate_skip_result(preflight: str) -> EmitReportResult:
    logger.warning("signals_scout.emit_report: skipped %s", preflight, extra={"skipped_reason": preflight})
    return EmitReportResult(
        report_id=None, status=None, emitted=False, skipped_reason=preflight, safety_explanation=None
    )


def _emit_result(persisted_report_id: str, judgement: ScoutReportJudgement) -> EmitReportResult:
    return EmitReportResult(
        report_id=persisted_report_id,
        status=judgement.status,
        emitted=_surfaced(judgement.status),
        skipped_reason=None,
        safety_explanation=judgement.safety.explanation,
    )


def _attribution_for(task_id: str | None) -> ArtefactAttribution:
    return ArtefactAttribution.from_task(task_id) if task_id is not None else ArtefactAttribution.system()


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
    """Author a full report: judge for safety, then persist at the judged status. Async entry (used by
    the in-Temporal runner); routes the sync DB work through `database_sync_to_async`."""
    _assert_team_owns_run(team, run)
    _validate_emit_inputs(title, evidence)
    signals = _build_signals(evidence)
    actionability_assessment = _build_actionability(
        explanation=actionability_explanation, choice=actionability, already_addressed=already_addressed
    )

    preflight = await database_sync_to_async(_preflight_emit_gates, thread_sensitive=False)(team, run)
    if preflight is not None:
        return _gate_skip_result(preflight)

    task_id = await database_sync_to_async(_resolve_task_id, thread_sensitive=False)(run)
    attribution = _attribution_for(task_id)
    judgement = await judge_scout_report(team_id=team.id, signals=signals, actionability=actionability_assessment)
    persisted = await database_sync_to_async(create_scout_report, thread_sensitive=False)(
        team_id=team.id,
        title=title,
        summary=summary,
        signals=signals,
        attribution=attribution,
        status=judgement.status,
        safety=judgement.safety,
        actionability=judgement.actionability,
        run=run,
    )
    return _emit_result(persisted.report_id, judgement)


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
    """Sync entry used by the DRF view path. Mirrors `emit_report` but keeps the sync DB work on the
    calling thread/connection (gates, persist) — only the safety-judge LLM call is bridged via
    `async_to_sync`. Wrapping the whole async function instead would run every DB op on a separate
    connection, which a request's transaction can't see."""
    _assert_team_owns_run(team, run)
    _validate_emit_inputs(title, evidence)
    signals = _build_signals(evidence)
    actionability_assessment = _build_actionability(
        explanation=actionability_explanation, choice=actionability, already_addressed=already_addressed
    )

    preflight = _preflight_emit_gates(team, run)
    if preflight is not None:
        return _gate_skip_result(preflight)

    task_id = _resolve_task_id(run)
    attribution = _attribution_for(task_id)
    judgement = async_to_sync(judge_scout_report)(
        team_id=team.id, signals=signals, actionability=actionability_assessment
    )
    persisted = create_scout_report(
        team_id=team.id,
        title=title,
        summary=summary,
        signals=signals,
        attribution=attribution,
        status=judgement.status,
        safety=judgement.safety,
        actionability=judgement.actionability,
        run=run,
    )
    return _emit_result(persisted.report_id, judgement)


def _do_edit_report(
    *,
    team: Team,
    run: SignalScoutRun,
    report_id: str,
    title: str | None,
    summary: str | None,
    append_note: str | None,
) -> EditReportResult:
    """Fully-sync edit core (no LLM step). The async/sync entrypoints both funnel here — directly in
    the sync path, via `database_sync_to_async` in the async path."""
    preflight = _preflight_emit_gates(team, run)
    if preflight is not None:
        raise InvalidScoutReportError(f"edit_report blocked by preflight gate: {preflight}")

    attribution = _attribution_for(_resolve_task_id(run))
    updated_fields: list[str] = []
    if title is not None or summary is not None:
        updated_fields = update_scout_report(team_id=team.id, report_id=report_id, title=title, summary=summary)
    note_appended = False
    if append_note is not None:
        append_report_note(
            team_id=team.id, report_id=report_id, note=append_note, attribution=attribution, author=run.skill_name
        )
        note_appended = True
    logger.info(
        "signals_scout.edit_report: edited",
        extra={"team_id": team.id, "report_id": report_id, "fields": updated_fields, "note": note_appended},
    )
    return EditReportResult(report_id=report_id, updated_fields=updated_fields, note_appended=note_appended)


def _validate_edit_inputs(team: Team, run: SignalScoutRun, title, summary, append_note) -> None:
    _assert_team_owns_run(team, run)
    if title is None and summary is None and append_note is None:
        raise InvalidScoutReportError("edit_report needs at least one of title, summary, append_note")


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
    fail-closed in the service. Async entry; runs the sync edit core in the thread pool."""
    _validate_edit_inputs(team, run, title, summary, append_note)
    return await database_sync_to_async(_do_edit_report, thread_sensitive=False)(
        team=team, run=run, report_id=report_id, title=title, summary=summary, append_note=append_note
    )


def edit_report_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    report_id: str,
    title: str | None = None,
    summary: str | None = None,
    append_note: str | None = None,
) -> EditReportResult:
    """Sync entry used by the DRF view path. Same behavior as `edit_report`, on the calling thread."""
    _validate_edit_inputs(team, run, title, summary, append_note)
    return _do_edit_report(
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
