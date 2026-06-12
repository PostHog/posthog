"""Report adapter: scout-authored reports -> `SignalReport` rows, bypassing the signal pipeline.

`emit_finding` (emit.py) pushes findings into the standard emitter -> buffer -> grouping
pipeline, where an LLM matcher decides which report a finding belongs to. The functions here
are the direct path: the scout *is* the matcher. `create_report_sync` mints a READY report
in one transaction (mirroring `custom_agent/persistence.py`), and `update_report_sync` edits
an existing report — title/summary rewrites, state transitions via `transition_to()`, and
appended judgment artefacts (priority / actionability / suggested reviewers).

Reports created this way have no backing signal rows in ClickHouse, so they are invisible
to the `source_product` list filter, return nothing from the report signals endpoint, and
can never be matched into or re-opened by future pipeline signals. That is an accepted v1
trade-off; the follow-up is writing a backing signal with a pre-assigned report_id.

Two guard layers run before any write:

- The same preflight gates as emit (`_preflight_emit_gates`): per-scout `emit` flag
  (dry-run scouts write nothing, reports included), org AI-processing approval, and the
  `signals_scout` source config. Gated calls return `persisted=False` with a
  `skipped_reason`, never an exception — a dry-run scout is not an error.
- The signal safety filter (`safety_filter`) runs synchronously over any scout-authored
  `title`/`summary` before it lands on a user-facing report. Scouts summarize
  customer-derived data; the pipeline's buffer-level filter never sees this path, so the
  check happens here. Unsafe content returns `skipped_reason="unsafe_content"` and fires
  the same `signal_blocked_by_safety_filter` telemetry as a pipeline drop.

Judgment payloads are validated against the same pydantic schemas the summary workflow
writes (`PriorityAssessment`, `ActionabilityAssessment` in `report_generation/research.py`)
so `_load_previous_research` and the latest-wins serializer reads parse them unchanged.
Artefacts are append-only — a scout "changing" priority appends a newer judgment, which is
what every read path resolves; prior judgments persist as the audit trail.
"""

from __future__ import annotations

import json
import uuid
import logging
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from asgiref.sync import async_to_sync
from pydantic import ValidationError

from posthog.models import Team

from products.signals.backend.models import (
    SIGNAL_REPORT_MAX_SNOOZE_FOR,
    SignalReport,
    SignalReportArtefact,
    SignalScoutRun,
)
from products.signals.backend.report_generation.research import ActionabilityAssessment, PriorityAssessment
from products.signals.backend.scout_harness.tools.emit import _assert_team_owns_run, _preflight_emit_gates

logger = logging.getLogger(__name__)

# Per-run circuit breaker on direct report creation. A scout that decides everything it
# sees deserves its own report is the failure mode this caps — the inbox is a curated
# surface, not a log stream. Updates are uncapped: editing existing reports doesn't grow
# the inbox.
MAX_REPORTS_PER_RUN = 10

# States a scout may transition a report to. Deliberately narrower than `transition_to`'s
# full matrix: pipeline-internal states (candidate, in_progress, ready, failed) are owned
# by the workflows, and `deleted` must go through the deletion workflow (it also cleans up
# the ClickHouse signal rows). `transition_to` still validates the from-state.
SCOUT_ALLOWED_TARGET_STATES = (
    SignalReport.Status.SUPPRESSED,
    SignalReport.Status.POTENTIAL,
    SignalReport.Status.RESOLVED,
)


class InvalidReportWriteError(ValueError):
    """The agent tried a report write with an invalid shape (empty title, bad judgment payload, etc)."""


class ReportNotFoundError(LookupError):
    """The referenced report does not exist on this team (or is deleted)."""


@dataclass(frozen=True)
class ReportWriteResult:
    """Outcome of a create_report / update_report call.

    `skipped_reason` mirrors `EmitResult` (emit.py): None means the write persisted.
    Additional value over emit's set:
      - "unsafe_content": the safety filter classified the scout-authored title/summary
        as adversarial; nothing was written.
      - "report_cap_reached": the run already created `MAX_REPORTS_PER_RUN` reports
        (create only).
    """

    report_id: str | None
    persisted: bool
    skipped_reason: str | None


def _normalize_reviewers(suggested_reviewers: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Shape reviewer entries to match the stored `suggested_reviewers` artefact format.

    Same wire shape as the summary workflow and custom-agent paths write (the artefact
    serializer enriches by `github_login` at read time; `relevant_commits` is part of the
    shape but a scout has no commit evidence to attach). Login normalization mirrors
    `CustomAgentAssignee` — that schema isn't imported here because pulling in the
    `custom_agent` package drags the temporal workflow modules along (circular import).
    """
    if suggested_reviewers is None:
        return None
    normalized: list[dict[str, Any]] = []
    for entry in suggested_reviewers:
        login = str(entry.get("github_login") or "").strip().lower().lstrip("@")
        if not login:
            raise InvalidReportWriteError("suggested_reviewers entries must carry a non-empty github_login")
        normalized.append(
            {
                "github_login": login,
                "github_name": entry.get("github_name") or None,
                "relevant_commits": [],
            }
        )
    return normalized


def _validate_judgments(
    priority: dict[str, Any] | None,
    actionability: dict[str, Any] | None,
    suggested_reviewers: list[dict[str, Any]] | None,
) -> tuple[PriorityAssessment | None, ActionabilityAssessment | None, list[dict[str, Any]] | None]:
    """Parse judgment payloads through the canonical pydantic schemas.

    Validation failures raise `InvalidReportWriteError` — a malformed judgment silently
    stored would poison the latest-wins reads and `_load_previous_research`.
    """
    parsed_priority: PriorityAssessment | None = None
    parsed_actionability: ActionabilityAssessment | None = None
    try:
        if priority is not None:
            parsed_priority = PriorityAssessment.model_validate(priority)
        if actionability is not None:
            parsed_actionability = ActionabilityAssessment.model_validate(actionability)
    except ValidationError as exc:
        raise InvalidReportWriteError(f"invalid judgment payload: {exc}") from exc
    return parsed_priority, parsed_actionability, _normalize_reviewers(suggested_reviewers)


def _check_content_safety(team: Team, run: SignalScoutRun, title: str | None, summary: str | None) -> str | None:
    """Run the signal safety filter over scout-authored report prose.

    Returns "unsafe_content" when blocked, None when safe. The pipeline path gets this
    filter in the buffer workflow; the direct path runs it inline before the write. On
    block, fires the same `signal_blocked_by_safety_filter` lifecycle event so safety
    monitoring sees direct-path drops alongside pipeline drops.
    """
    # Deferred to keep harness module import light and avoid loading temporal deps eagerly.
    from products.signals.backend.temporal.safety_filter import (  # noqa: PLC0415 — keeps temporal deps off the import path
        SafetyFilterInput,
        _capture_signal_blocked_event,
        safety_filter,
    )

    parts = [part for part in (title, summary) if part and part.strip()]
    if not parts:
        return None
    text = "\n\n".join(parts)
    result = async_to_sync(safety_filter)(team.id, text)
    if result.safe:
        return None
    logger.warning(
        "signals_scout.report: content blocked by safety filter",
        extra={
            "team_id": team.id,
            "run_id": str(run.id),
            "threat_type": result.threat_type,
        },
    )
    async_to_sync(_capture_signal_blocked_event)(
        SafetyFilterInput(
            description=text,
            team_id=team.id,
            source_product="signals_scout",
            source_type="scout_report",
            source_id=f"run:{run.id}",
            extra={"scout_run_id": str(run.id), "skill_name": run.skill_name},
        ),
        result,
    )
    return "unsafe_content"


def _judgment_artefacts(
    *,
    team_id: int,
    report: SignalReport,
    run: SignalScoutRun,
    priority: PriorityAssessment | None,
    actionability: ActionabilityAssessment | None,
    reviewers: list[dict[str, Any]] | None,
) -> list[SignalReportArtefact]:
    artefacts: list[SignalReportArtefact] = []
    if actionability is not None:
        artefacts.append(
            SignalReportArtefact(
                team_id=team_id,
                report=report,
                type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                content=actionability.model_dump_json(),
                created_by_scout_run=run,
            )
        )
    if priority is not None:
        artefacts.append(
            SignalReportArtefact(
                team_id=team_id,
                report=report,
                type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                content=priority.model_dump_json(),
                created_by_scout_run=run,
            )
        )
    # `is not None` (not truthiness): an explicit empty list is a real payload — the newest
    # artefact wins on read, so `[]` is how a caller clears stale reviewer suggestions.
    if reviewers is not None:
        artefacts.append(
            SignalReportArtefact(
                team_id=team_id,
                report=report,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                content=json.dumps(reviewers),
                created_by_scout_run=run,
            )
        )
    return artefacts


def create_report_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    title: str,
    summary: str,
    priority: dict[str, Any] | None = None,
    actionability: dict[str, Any] | None = None,
    suggested_reviewers: list[dict[str, Any]] | None = None,
) -> ReportWriteResult:
    """Create a READY inbox report authored by a scout, in one transaction.

    The report lands with `signal_count=0` / `total_weight=0` like the custom-agent path —
    the scout's evidence lives in the summary prose and the appended judgment artefacts,
    not in backing signal rows.
    """
    _assert_team_owns_run(team, run)
    if not title or not title.strip():
        raise InvalidReportWriteError("title must not be empty")
    if not summary or not summary.strip():
        raise InvalidReportWriteError("summary must not be empty")
    parsed_priority, parsed_actionability, parsed_reviewers = _validate_judgments(
        priority, actionability, suggested_reviewers
    )

    preflight = _preflight_emit_gates(team, run)
    if preflight is not None:
        logger.warning(
            "signals_scout.report: create skipped %s",
            preflight,
            extra={"team_id": team.id, "run_id": str(run.id)},
        )
        return ReportWriteResult(report_id=None, persisted=False, skipped_reason=preflight)

    # Cheap unlocked pre-check so a capped run skips before the (costly) LLM safety call.
    # NOT the authoritative gate — the locked re-check inside the transaction below is.
    created_count = SignalReport.objects.filter(team_id=team.id, created_by_scout_run=run).count()
    if created_count >= MAX_REPORTS_PER_RUN:
        logger.warning(
            "signals_scout.report: create skipped report_cap_reached",
            extra={"team_id": team.id, "run_id": str(run.id), "created_count": created_count},
        )
        return ReportWriteResult(report_id=None, persisted=False, skipped_reason="report_cap_reached")

    unsafe = _check_content_safety(team, run, title, summary)
    if unsafe is not None:
        return ReportWriteResult(report_id=None, persisted=False, skipped_reason=unsafe)

    with transaction.atomic():
        # Serialize concurrent creates from the same run on the run row, then re-check the
        # cap under the lock — without this, parallel calls could all pass the unlocked
        # pre-check and overshoot the cap. Same locking anchor `_record_emit` uses.
        locked_run = SignalScoutRun.all_teams.select_for_update().filter(pk=run.pk).first()
        if locked_run is None:
            raise InvalidReportWriteError("run no longer exists")
        created_count = SignalReport.objects.filter(team_id=team.id, created_by_scout_run=run).count()
        if created_count >= MAX_REPORTS_PER_RUN:
            logger.warning(
                "signals_scout.report: create skipped report_cap_reached",
                extra={"team_id": team.id, "run_id": str(run.id), "created_count": created_count},
            )
            return ReportWriteResult(report_id=None, persisted=False, skipped_reason="report_cap_reached")
        report = SignalReport.objects.create(
            team_id=team.id,
            status=SignalReport.Status.READY,
            title=title,
            summary=summary,
            signal_count=0,
            total_weight=0.0,
            created_by_scout_run=run,
        )
        artefacts = _judgment_artefacts(
            team_id=team.id,
            report=report,
            run=run,
            priority=parsed_priority,
            actionability=parsed_actionability,
            reviewers=parsed_reviewers,
        )
        if artefacts:
            SignalReportArtefact.objects.bulk_create(artefacts)

    logger.info(
        "signals_scout.report: created",
        extra={"team_id": team.id, "run_id": str(run.id), "report_id": str(report.id)},
    )
    return ReportWriteResult(report_id=str(report.id), persisted=True, skipped_reason=None)


def update_report_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    report_id: str | uuid.UUID,
    title: str | None = None,
    summary: str | None = None,
    new_state: str | None = None,
    snooze_for: int | None = None,
    priority: dict[str, Any] | None = None,
    actionability: dict[str, Any] | None = None,
    suggested_reviewers: list[dict[str, Any]] | None = None,
) -> ReportWriteResult:
    """Update an existing report on the scout's team: rewrite title/summary, transition
    state, and/or append judgment artefacts — all in one transaction.

    Raises:
      - `ReportNotFoundError` for a missing/foreign/deleted report (view maps to 404).
      - `InvalidReportWriteError` for shape problems (view maps to 400).
      - `InvalidStatusTransition` (from `transition_to`) for an illegal state move
        (view maps to 409, same as the user-facing state endpoint).
    """
    _assert_team_owns_run(team, run)
    if title is not None and not title.strip():
        raise InvalidReportWriteError("title must not be blank when provided")
    if summary is not None and not summary.strip():
        raise InvalidReportWriteError("summary must not be blank when provided")
    if new_state is not None and new_state not in {state.value for state in SCOUT_ALLOWED_TARGET_STATES}:
        allowed = ", ".join(state.value for state in SCOUT_ALLOWED_TARGET_STATES)
        raise InvalidReportWriteError(f"new_state must be one of: {allowed}")
    # The DRF serializer already caps this, but the tool layer must hold the bound on its
    # own: an uncapped snooze pushes `signals_at_run` out far enough to suppress the report
    # from re-promotion forever (and an int4-overflowing value would 500 on save).
    if snooze_for is not None and not 1 <= snooze_for <= SIGNAL_REPORT_MAX_SNOOZE_FOR:
        raise InvalidReportWriteError(f"snooze_for must be between 1 and {SIGNAL_REPORT_MAX_SNOOZE_FOR}")
    if all(value is None for value in (title, summary, new_state, priority, actionability, suggested_reviewers)):
        raise InvalidReportWriteError("at least one field to update must be provided")
    parsed_priority, parsed_actionability, parsed_reviewers = _validate_judgments(
        priority, actionability, suggested_reviewers
    )

    preflight = _preflight_emit_gates(team, run)
    if preflight is not None:
        logger.warning(
            "signals_scout.report: update skipped %s",
            preflight,
            extra={"team_id": team.id, "run_id": str(run.id), "report_id": str(report_id)},
        )
        return ReportWriteResult(report_id=str(report_id), persisted=False, skipped_reason=preflight)

    unsafe = _check_content_safety(team, run, title, summary)
    if unsafe is not None:
        return ReportWriteResult(report_id=str(report_id), persisted=False, skipped_reason=unsafe)

    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update()
            .filter(team_id=team.id, id=report_id)
            .exclude(status=SignalReport.Status.DELETED)
            .first()
        )
        if report is None:
            raise ReportNotFoundError(f"report {report_id} not found on team {team.id}")

        updated_fields: set[str] = set()
        if new_state is not None:
            # `snooze_for` only applies on a snooze back to potential, mirroring the user
            # state endpoint. `transition_to` raises InvalidStatusTransition on illegal moves.
            effective_snooze = snooze_for if new_state == SignalReport.Status.POTENTIAL else None
            updated_fields.update(report.transition_to(SignalReport.Status(new_state), snooze_for=effective_snooze))
            # Every scout-driven transition leaves a user-visible audit artefact (the user
            # dismissal flow writes the same type). Scouts can move any report on the team —
            # all transitions are reversible and deletion is excluded — so a transition steered
            # by adversarial telemetry must be attributable and recoverable from the report
            # itself, not just from app logs.
            SignalReportArtefact.objects.create(
                team_id=team.id,
                report=report,
                type=SignalReportArtefact.ArtefactType.DISMISSAL,
                content=json.dumps(
                    {
                        "reason": "scout_state_change",
                        "note": f"Transitioned to {new_state} by scout run {run.id} ({run.skill_name})",
                    }
                ),
                created_by_scout_run=run,
            )
        if title is not None:
            report.title = title
            updated_fields.update(["title", "updated_at"])
        if summary is not None:
            report.summary = summary
            updated_fields.update(["summary", "updated_at"])
        if updated_fields:
            report.save(update_fields=list(updated_fields))

        artefacts = _judgment_artefacts(
            team_id=team.id,
            report=report,
            run=run,
            priority=parsed_priority,
            actionability=parsed_actionability,
            reviewers=parsed_reviewers,
        )
        if artefacts:
            SignalReportArtefact.objects.bulk_create(artefacts)

    logger.info(
        "signals_scout.report: updated",
        extra={
            "team_id": team.id,
            "run_id": str(run.id),
            "report_id": str(report.id),
            "new_state": new_state,
            "updated_fields": sorted(updated_fields),
            "artefact_count": len(artefacts),
        },
    )
    return ReportWriteResult(report_id=str(report.id), persisted=True, skipped_reason=None)
