"""Safety + actionability gating for scout-authored reports, before they surface in the inbox.

`custom_agent/` writes its reports straight to READY because it is an engineering-only surface. Scouts
are customer-facing, so a scout-authored report passes the same prompt-injection **safety judge** the
pipeline runs (decision #3) before it can surface. Actionability is supplied by the scout itself — it
authored the report and made the actionability call, exactly as `custom_agent` carries its own
`ActionabilityAssessment` — rather than re-derived by a second sandbox research pass (which the
pipeline's actionability judge requires and which would defeat the point of direct authorship).

The two combine into the status the report is born at:

    unsafe                      -> SUPPRESSED   (never surface a report whose signals look adversarial)
    safe + immediately_actionable -> READY
    safe + requires_human_input   -> PENDING_INPUT
    safe + not_actionable         -> SUPPRESSED

The mapping is a pure function (`resolve_authored_report_status`) so it is unit-tested without the LLM;
`judge_scout_report` wraps it with the actual safety-judge call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.utils import timezone

from posthog.sync import database_sync_to_async

from products.signals.backend.artefact_schemas import ActionabilityAssessment, ActionabilityChoice, SafetyJudgment
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalScoutRun
from products.signals.backend.scout_harness.tools.emit import SOURCE_PRODUCT, SOURCE_TYPE
from products.signals.backend.scout_report.persistence import (
    PersistedScoutReport,
    ScoutReportSignal,
    create_scout_report,
)
from products.signals.backend.temporal.report_safety_judge import judge_report_safety
from products.signals.backend.temporal.types import SignalData


@dataclass(frozen=True)
class ScoutReportJudgement:
    """The verdict that decides whether (and how) an authored report surfaces."""

    status: SignalReport.Status
    safety: SafetyJudgment
    actionability: ActionabilityAssessment


def resolve_authored_report_status(*, safe: bool, actionability: ActionabilityChoice) -> SignalReport.Status:
    """Pure status mapping for an authored report (see module docstring). Unsafe always wins —
    an adversarial-looking report is suppressed regardless of how actionable the scout judged it."""
    if not safe:
        return SignalReport.Status.SUPPRESSED
    match actionability:
        case ActionabilityChoice.IMMEDIATELY_ACTIONABLE:
            return SignalReport.Status.READY
        case ActionabilityChoice.REQUIRES_HUMAN_INPUT:
            return SignalReport.Status.PENDING_INPUT
        case ActionabilityChoice.NOT_ACTIONABLE:
            return SignalReport.Status.SUPPRESSED


def _to_signal_data(signals: list[ScoutReportSignal]) -> list[SignalData]:
    """Adapt the authored-report signals into the `SignalData` shape the safety judge renders."""
    return [
        SignalData(
            signal_id=signal.document_id or str(uuid.uuid4()),
            content=signal.description,
            source_product=SOURCE_PRODUCT,
            source_type=SOURCE_TYPE,
            source_id=signal.source_id,
            weight=signal.weight,
            timestamp=signal.timestamp or timezone.now(),
            extra=dict(signal.extra),
        )
        for signal in signals
    ]


async def judge_scout_report(
    *,
    team_id: int,
    signals: list[ScoutReportSignal],
    actionability: ActionabilityAssessment,
) -> ScoutReportJudgement:
    """Run the safety judge on the authored report's signals and resolve the birth status.

    The safety judge is a plain LLM call (`judge_report_safety`) — no Temporal workflow, no sandbox —
    so this runs inline on whatever worker is authoring the report.
    """
    safety_response = await judge_report_safety(team_id=team_id, signals=_to_signal_data(signals))
    safety = SafetyJudgment(
        choice=safety_response.choice,
        explanation=safety_response.explanation if not safety_response.choice else None,
    )
    status = resolve_authored_report_status(safe=safety_response.choice, actionability=actionability.actionability)
    return ScoutReportJudgement(status=status, safety=safety, actionability=actionability)


async def author_scout_report(
    *,
    team_id: int,
    title: str,
    summary: str,
    signals: list[ScoutReportSignal],
    actionability: ActionabilityAssessment,
    attribution: ArtefactAttribution,
    run: SignalScoutRun | None = None,
) -> tuple[PersistedScoutReport, ScoutReportJudgement]:
    """The integration point the harness `emit_report` tool (Phase 3) calls: judge, then persist at the
    judged status with the safety + actionability verdicts recorded as artefacts.

    Returns the persisted report and the judgement, so the tool can tell the agent why a report was
    suppressed/held rather than surfaced (the safety explanation, the actionability choice)."""
    judgement = await judge_scout_report(team_id=team_id, signals=signals, actionability=actionability)
    persisted = await database_sync_to_async(create_scout_report, thread_sensitive=False)(
        team_id=team_id,
        title=title,
        summary=summary,
        signals=signals,
        attribution=attribution,
        status=judgement.status,
        safety=judgement.safety,
        actionability=judgement.actionability,
        run=run,
    )
    return persisted, judgement
