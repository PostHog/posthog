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

from products.signals.backend.artefact_schemas import ActionabilityAssessment, ActionabilityChoice, SafetyJudgment
from products.signals.backend.models import SignalReport
from products.signals.backend.scout_harness.tools.emit import SOURCE_PRODUCT, SOURCE_TYPE
from products.signals.backend.scout_report.persistence import ScoutReportSignal
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
        case _:
            raise ValueError(f"unhandled actionability choice: {actionability}")


def _report_content_signal(title: str, summary: str) -> SignalData:
    """Wrap the authored `title` + `summary` as a `SignalData` so the safety judge evaluates the exact
    prose that will surface (and feed autostart), not just the backing evidence. Prompt-injection can
    land in the report body itself while the evidence descriptions look benign — this makes the judge
    see the report text too, so an unsafe title/summary suppresses the report."""
    return SignalData(
        signal_id=str(uuid.uuid4()),
        content=f"{title}\n\n{summary}",
        source_product=SOURCE_PRODUCT,
        source_type=SOURCE_TYPE,
        source_id="report_content",
        weight=0.0,
        timestamp=timezone.now(),
        extra={},
    )


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
    title: str,
    summary: str,
    signals: list[ScoutReportSignal],
    actionability: ActionabilityAssessment,
) -> ScoutReportJudgement:
    """Run the safety judge on the authored report and resolve the birth status.

    The judge sees the authored `title`/`summary` *and* the backing observations — so prompt-injection
    in the report prose itself (not just the evidence) is caught before the report can surface or feed
    autostart. The safety judge is a plain LLM call (`judge_report_safety`) — no Temporal workflow, no
    sandbox — so this runs inline on whatever worker is authoring the report.
    """
    safety_input = [_report_content_signal(title, summary), *_to_signal_data(signals)]
    safety_response = await judge_report_safety(team_id=team_id, signals=safety_input)
    safety = SafetyJudgment(
        choice=safety_response.choice,
        explanation=safety_response.explanation if not safety_response.choice else None,
    )
    status = resolve_authored_report_status(safe=safety_response.choice, actionability=actionability.actionability)
    return ScoutReportJudgement(status=status, safety=safety, actionability=actionability)
