"""Render researched deprecations into a Signals inbox report (the inbox edge).

Maps the cited ``ResearchedDeprecation`` findings onto the custom-agent report shape and persists a
READY ``SignalReport``. The rendering helpers are pure (used by ``ApiDeprecationAgent`` too); only
``emit_signal_to_inbox`` touches the DB.

Assignees are intentionally empty: an empty reviewer list makes ``maybe_autostart_implementation_task``
a no-op, so emitting NEVER opens a PR. Dispatch to PostHog Code is added explicitly in milestone 2,
and only for mechanical, cited, high-confidence findings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from products.signals.backend.api_deprecation.schema import (
    MECHANICAL_CONFIDENCE_THRESHOLD,
    Classification,
    ResearchedDeprecation,
)
from products.signals.backend.api_deprecation.severity import score_severity, select_most_urgent
from products.signals.backend.custom_agent.persistence import (
    PersistedCustomAgentReport,
    create_custom_agent_ready_report,
)
from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult


@dataclass(frozen=True)
class ReportComponents:
    title: str
    description: str
    actionability: ActionabilityAssessment
    priority: PriorityAssessment


def _render_finding(finding: ResearchedDeprecation, today: date) -> str:
    severity = score_severity(finding.cutoff_date, today)
    cutoff = finding.cutoff_date.isoformat() if finding.cutoff_date else "no published date"
    if finding.already_past_cutoff:
        cutoff += " (already past)"
    migration = " · needs data migration" if finding.pin.persisted_per_row else ""
    affected = f" · affected fields: {', '.join(finding.affected_fields)}" if finding.affected_fields else ""
    return (
        f"- **{severity} [{finding.classification.value}]** {finding.pin.product} "
        f"`{finding.pin.pinned_version}` → `{finding.recommended_version or 'latest GA'}` "
        f"at `{finding.pin.file}:{finding.pin.line}`. Cutoff: {cutoff}{migration}{affected}.\n"
        f'  Evidence: [{finding.evidence_url}]({finding.evidence_url}) — "{finding.evidence_quote}"'
    )


def render_report(findings: list[ResearchedDeprecation], today: date) -> ReportComponents | None:
    """Build inbox report components from cited findings, most-urgent first. None ⇒ nothing to report."""
    ranked = select_most_urgent(findings, today)
    if not ranked:
        return None
    top = ranked[0]

    auto_remediable = (
        top.classification == Classification.MECHANICAL
        and top.confidence >= MECHANICAL_CONFIDENCE_THRESHOLD
        and bool(top.evidence_url.strip())
    )
    title = (
        f"{top.pin.product}: {top.pin.pinned_version} deprecated — bump to {top.recommended_version or 'latest GA'}"
    )[:255]
    description = f"{len(ranked)} stale external-API version pin(s), grounded in vendor changelogs:\n\n" + "\n".join(
        _render_finding(f, today) for f in ranked
    )
    actionability = ActionabilityAssessment(
        explanation=(
            f"Mechanical bump ({top.pin.pinned_version} → {top.recommended_version}); "
            "fields we use are unchanged per the cited changelog."
            if auto_remediable
            else f"Classification '{top.classification.value}' (confidence {top.confidence}); "
            "needs human review before any code change."
        ),
        actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE
        if auto_remediable
        else ActionabilityChoice.REQUIRES_HUMAN_INPUT,
        already_addressed=False,
    )
    priority = PriorityAssessment(
        explanation=(
            f"{top.pin.host} {top.pin.pinned_version} cutoff "
            f"{top.cutoff_date.isoformat() if top.cutoff_date else 'unpublished'}."
        ),
        priority=Priority(score_severity(top.cutoff_date, today)),
    )
    return ReportComponents(title=title, description=description, actionability=actionability, priority=priority)


def emit_signal_to_inbox(
    *,
    team_id: int,
    findings: list[ResearchedDeprecation],
    today: date,
    repository: str = "posthog/posthog",
) -> PersistedCustomAgentReport | None:
    """Persist cited findings as one READY ``SignalReport`` (no PR side effects). None ⇒ nothing emitted."""
    components = render_report(findings, today)
    if components is None:
        return None
    final = CustomAgentFinalReport(
        title=components.title,
        description=components.description,
        actionability=components.actionability,
        assignees=[],  # empty → never auto-opens a PR
        priority=components.priority,
    )
    return create_custom_agent_ready_report(
        team_id=team_id,
        final_report=final,
        repo_selection=RepoSelectionResult(
            repository=repository,
            reason="API deprecation loop — codebase scanned for stale external-API version pins.",
        ),
    )
