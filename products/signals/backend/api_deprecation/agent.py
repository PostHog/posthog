"""``CustomSignalAgent`` that flags deprecated third-party API usage as cited inbox reports.

The deterministic detector (``scanner`` + ``extractors`` in this package) inventories the codebase's
external URL usages; this agent triages which are genuine API call sites, researches those against
the vendor's official documentation (version-level and endpoint-level), and files one READY report
for the deprecations it can cite. It rides the shared custom-agent rails — launch it with
``run_agent``, passing the detector's inventory as ``initial_prompt`` (see
``research.build_research_initial_prompt``). The base class handles the sandbox, persistence, and
the ``auto_start`` hand-off to PostHog Code, so there is no bespoke Temporal workflow or dispatcher
here. This module stays Temporal-free — the workflow activity imports it dynamically via
``import_agent_class``.

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
from products.signals.backend.custom_agent import CustomSignalAgent
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
    migration = " · needs data migration" if finding.usage.persisted_per_row else ""
    affected = f" · affected fields: {', '.join(finding.affected_fields)}" if finding.affected_fields else ""
    pinned = f" (pinned `{finding.usage.version}`)" if finding.usage.version else ""
    return (
        f"- **{severity} [{finding.classification.value}]** {finding.headline} — "
        f"`{finding.usage.host}{finding.usage.endpoint}`{pinned} "
        f"at `{finding.usage.file}:{finding.usage.line}`. Cutoff: {cutoff}{migration}{affected}.\n"
        f'  Evidence: [{finding.evidence_url}]({finding.evidence_url}) — "{finding.evidence_quote}"'
    )


def _render_triage(researched: ResearchedDeprecationList) -> str:
    if not researched.cleared and not researched.skipped:
        return ""
    return (
        f"\n\nAlso researched and verified current: {len(researched.cleared)} usage(s); "
        f"triaged as non-API references (docs, scopes, assets): {len(researched.skipped)}."
    )


class ApiDeprecationAgent(CustomSignalAgent):
    """Triages detected API usages, researches them against vendor docs, and reports the cited deprecations."""

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

        # PR-style title (same convention as ReportPresentationOutput) — it flows into the
        # auto-started implementation task and ultimately a draft PR.
        self.register_title(f"fix(cdp): {top.headline}"[:96])
        self.register_description(
            f"{len(ranked)} deprecated third-party API usage(s), grounded in vendor documentation:\n\n"
            + "\n".join(_render_finding(f, today) for f in ranked)
            + _render_triage(researched)
        )
        self.register_actionability(
            ActionabilityAssessment(
                explanation=(
                    f"{top.headline}: mechanical change; fields in use are unchanged per the cited source."
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
                    f"{top.usage.host}{top.usage.endpoint} cutoff "
                    f"{top.cutoff_date.isoformat() if top.cutoff_date else 'unpublished'}."
                ),
                priority=Priority(score_severity(top.cutoff_date, today)),
            )
        )
        # Suggested reviewers are left to the base resolver (idiomatic), which infers them from the
        # research conversation. auto_start only opens a draft PR if a reviewer opted into autonomy.
        return True
