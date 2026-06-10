"""``CustomSignalAgent`` that flags stale external-API version pins as cited inbox reports.

The deterministic detector (``products/signals/backend/api_deprecation``) finds in-code API version
pins; this agent researches each against the vendor's real changelog and files one READY report for
the deprecations it can cite. It rides the shared custom-agent rails — launch it with ``run_agent``,
passing the detector's inventory as ``initial_prompt`` (see ``research.build_research_initial_prompt``).
The base class handles the sandbox, persistence, and the ``auto_start`` hand-off to PostHog Code, so
there is no bespoke Temporal workflow or dispatcher here.

Classification gates remediation without a separate dispatcher: mechanical+cited+confident findings
are marked immediately actionable (eligible for an auto-started draft PR), everything else is marked
``requires_human_input`` so it is never auto-PR'd.
"""

from __future__ import annotations

from datetime import date

from products.signals.backend.api_deprecation.research import BATCH_RESEARCH_INSTRUCTION
from products.signals.backend.api_deprecation.schema import (
    MECHANICAL_CONFIDENCE_THRESHOLD,
    Classification,
    ResearchedDeprecation,
    ResearchedDeprecationList,
)
from products.signals.backend.api_deprecation.severity import score_severity, select_most_urgent
from products.signals.backend.custom_agent.base import CustomSignalAgent
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)


def _render_finding(finding: ResearchedDeprecation, today: date) -> str:
    severity = score_severity(finding.cutoff_date, today)
    cutoff = finding.cutoff_date.isoformat() if finding.cutoff_date else "no published date"
    if finding.cutoff_date and finding.cutoff_date < today:
        cutoff += " (already past)"
    migration = " · needs data migration" if finding.pin.persisted_per_row else ""
    affected = f" · affected fields: {', '.join(finding.affected_fields)}" if finding.affected_fields else ""
    return (
        f"- **{severity} [{finding.classification.value}]** {finding.pin.product} "
        f"`{finding.pin.pinned_version}` → `{finding.recommended_version or 'latest GA'}` "
        f"at `{finding.pin.file}:{finding.pin.line}`. Cutoff: {cutoff}{migration}{affected}.\n"
        f'  Evidence: [{finding.evidence_url}]({finding.evidence_url}) — "{finding.evidence_quote}"'
    )


class ApiDeprecationAgent(CustomSignalAgent):
    """Researches each detected version pin against its vendor changelog and reports the cited stale ones."""

    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return ("signals", "api_deprecation")

    async def run(self) -> bool:
        researched = await self.send(BATCH_RESEARCH_INSTRUCTION, ResearchedDeprecationList, label="research")
        today = date.today()
        ranked = select_most_urgent(researched.items, today)
        if not ranked:
            return False  # nothing citable to report — a valid outcome

        top = ranked[0]
        auto_remediable = (
            top.classification == Classification.MECHANICAL and top.confidence >= MECHANICAL_CONFIDENCE_THRESHOLD
        )

        self.register_title(
            f"{top.pin.product}: {top.pin.pinned_version} deprecated — bump to {top.recommended_version or 'latest GA'}"[
                :255
            ]
        )
        self.register_description(
            f"{len(ranked)} stale external-API version pin(s), grounded in vendor changelogs:\n\n"
            + "\n".join(_render_finding(f, today) for f in ranked)
        )
        self.register_actionability(
            ActionabilityAssessment(
                explanation=(
                    f"Mechanical bump ({top.pin.pinned_version} → {top.recommended_version}); "
                    "fields in use are unchanged per the cited changelog."
                    if auto_remediable
                    else f"Classification '{top.classification.value}' (confidence {top.confidence}); "
                    "needs human review before any code change."
                ),
                # Only mechanical+cited+confident findings are auto-remediable; everything else stays
                # with a human so it is never auto-PR'd.
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE
                if auto_remediable
                else ActionabilityChoice.REQUIRES_HUMAN_INPUT,
                already_addressed=False,
            )
        )
        self.register_priority(
            PriorityAssessment(
                explanation=(
                    f"{top.pin.host} {top.pin.pinned_version} cutoff "
                    f"{top.cutoff_date.isoformat() if top.cutoff_date else 'unpublished'}."
                ),
                priority=Priority(score_severity(top.cutoff_date, today)),
            )
        )
        # Suggested reviewers are left to the base resolver (idiomatic), which infers them from the
        # research conversation. auto_start only opens a draft PR if a reviewer opted into autonomy.
        return True
