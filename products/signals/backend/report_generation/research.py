from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from products.signals.backend.temporal.actionability_judge import ActionabilityChoice, Priority
from products.signals.backend.temporal.types import SignalData

if TYPE_CHECKING:
    from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext, OutputFn

logger = logging.getLogger(__name__)

# TODO: Signals deduplication step before the research


class SignalFinding(BaseModel):
    signal_id: str = Field(description="The signal_id from the input signal list")
    relevant_code_paths: list[str] = Field(
        description=(
            "File paths in the codebase relevant to this signal. "
            "Include paths to the feature/component the signal is about, "
            "related posthog.capture() calls, and feature flag checks."
        ),
    )
    data_queried: str = Field(
        description=(
            "What PostHog MCP queries you ran (e.g. execute-sql, query-run, insight-query) "
            "and what the results showed. If no relevant queries could be run, explain why."
        ),
    )
    verified: bool = Field(
        description=(
            "Whether you could confirm the signal's claim by finding supporting evidence "
            "in code or data. False if the claim couldn't be verified either way."
        ),
    )


class ActionabilityAssessment(BaseModel):
    explanation: str = Field(
        description=(
            "2-3 sentence evidence-grounded explanation of your actionability assessment. "
            "Reference specific code paths and data points from your research."
        ),
    )
    actionability: ActionabilityChoice = Field(description="Overall actionability assessment")
    already_addressed: bool = Field(
        description=(
            "Whether the core issue described by this report appears to have been "
            "already fixed or addressed in recent code changes."
        ),
    )

    @field_validator("explanation")
    @classmethod
    def explanation_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Explanation must not be empty")
        return v


class PriorityAssessment(BaseModel):
    explanation: str = Field(
        description=(
            "2-3 sentence justification for the priority level. "
            "Reference quantified user impact, error frequency, or scope of affected code paths."
        ),
    )
    priority: Priority = Field(description="Priority (P0-P4)")

    @field_validator("explanation")
    @classmethod
    def explanation_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Explanation must not be empty")
        return v


class ReportResearchOutput(BaseModel):
    findings: list[SignalFinding] = Field(
        description="One finding per signal in the report, in the same order as the input signals.",
    )
    actionability: ActionabilityAssessment = Field(description="Actionability assessment.")
    priority: PriorityAssessment | None = Field(
        default=None, description="Priority assessment. None when not actionable."
    )


def _render_signal_for_research(signal: SignalData, index: int, total: int) -> str:
    """Render a single signal for the research prompt, with numbering."""
    lines = [f"### Signal {index}/{total} (id: `{signal.signal_id}`)"]
    lines.append(f"- **Source:** {signal.source_product} / {signal.source_type}")
    lines.append(f"- **Source ID:** {signal.source_id}")
    lines.append(f"- **Weight:** {signal.weight}")
    lines.append(f"- **Timestamp:** {signal.timestamp}")
    if signal.extra:
        if "url" in signal.extra:
            lines.append(f"- **URL:** {signal.extra['url']}")
        if "labels" in signal.extra:
            lines.append(f"- **Labels:** {', '.join(signal.extra['labels'])}")
    lines.append(f"- **Description:** {signal.content}")
    return "\n".join(lines)


_RESEARCH_PREAMBLE = """You are a research agent investigating a signal report for the PostHog codebase.
Your findings will be passed downstream to a coding agent that will act on this report — thorough, evidence-based research here directly improves the quality of the coding agent's work.

You have two investigation tools:
1. **The codebase** — the full PostHog repository is available on disk. Use file search, grep, and code reading.
2. **PostHog MCP** — you can query PostHog analytics data via MCP tools like `execute-sql`, `query-run`, `read-data-schema`, `insights-get-all`, `experiment-get`, `list-errors`, `feature-flag-get-all`, etc."""

_RESEARCH_PROTOCOL = """## Research protocol

For each signal, find **code evidence** and **data evidence**:

- **Code:** Trace the code path behind the signal's claim — find the relevant files, read the implementation, and understand how the logic actually works. Even if the signal doesn't mention specific files, search for the feature/component and dig in. Also look for `posthog.capture` calls or feature flag checks nearby — these show what the team tracks and gates, which helps gauge importance.
- **Data:** Use PostHog MCP tools (`execute-sql`, `query-run`, `read-data-schema`, etc.) to check real impact — error rates, user counts, conversion metrics. If the signal references a specific insight, experiment, or feature flag, look it up directly.

Cross-reference code and data — does the data corroborate what the code suggests?

**Budget:** Spend no more than ~8 tool calls per signal. If you can't verify a signal's claim after that, mark it unverified and move on."""

_ACTIONABILITY_CRITERIA = """## Actionability criteria

1. **immediately_actionable** — A coding agent could take concrete, useful action right now. Examples: bug fixes, experiment reactions, feature flag cleanup, UX fixes, deep investigation with clear jumping-off points.
2. **requires_human_input** — Actionable but needs human judgment first (business context, trade-offs, multiple valid approaches, purely informational).
3. **not_actionable** — No useful code action can be derived (too vague, insufficient evidence, expected behavior).

When in doubt between "immediately_actionable" and "requires_human_input", choose "immediately_actionable".
When in doubt between "requires_human_input" and "not_actionable", choose "not_actionable"."""


def build_initial_research_prompt(
    first_signal: SignalData,
    total_signals: int,
    *,
    title: str | None = None,
    summary: str | None = None,
) -> str:
    """Build the opening prompt for the first signal in a multi-turn research session."""
    signal_block = _render_signal_for_research(first_signal, 1, total_signals)
    finding_schema = json.dumps(SignalFinding.model_json_schema(), indent=2)

    report_context = ""
    if title or summary:
        report_context = "\n---\n\n## Report under investigation\n\n"
        if title:
            report_context += f"**Title:** {title}\n\n"
        if summary:
            report_context += f"**Summary:** {summary}\n\n"

    return f"""{_RESEARCH_PREAMBLE}

You will investigate **{total_signals} signal(s)** one at a time. I will send each signal in a separate message. For each one, investigate it thoroughly then respond with a `SignalFinding` JSON object.
{report_context}
---

{_RESEARCH_PROTOCOL}

---

## Signal 1 of {total_signals}

{signal_block}

---

## Output format

Investigate this signal, then respond with a JSON object matching this schema:

<jsonschema>
{finding_schema}
</jsonschema>"""


def build_signal_investigation_prompt(signal: SignalData, index: int, total: int) -> str:
    """Build a follow-up prompt for signal N (2..total)."""
    signal_block = _render_signal_for_research(signal, index, total)
    finding_schema = json.dumps(SignalFinding.model_json_schema(), indent=2)

    return f"""## Signal {index} of {total}

{signal_block}

---

If this signal substantially overlaps with one you already investigated, reference your earlier finding and focus only on what's new or different — don't re-investigate the same code paths and data.

Investigate this signal using the same protocol, then respond with a JSON object matching this schema:

<jsonschema>
{finding_schema}
</jsonschema>"""


def build_actionability_prompt(total_signals: int) -> str:
    """Build the prompt asking for an actionability assessment after all signals are investigated."""
    schema = json.dumps(ActionabilityAssessment.model_json_schema(), indent=2)

    return f"""You have investigated all {total_signals} signal(s). Now assess: **is this report actionable?**

{_ACTIONABILITY_CRITERIA}

Consider all your findings together.

Respond with a JSON object matching this schema:

<jsonschema>
{schema}
</jsonschema>"""


def build_priority_prompt(total_signals: int) -> str:
    """Build the prompt asking for a priority assessment (only sent when actionable)."""
    schema = json.dumps(PriorityAssessment.model_json_schema(), indent=2)

    return f"""Now assess the **priority** of this report based on your research across all {total_signals} signal(s).

## Priority criteria

- **P0** — Critical. Production errors, core flow broken, data loss, security vulnerability.
- **P1** — High. Significant user-facing impact, statistically significant regression, notable error rate increase.
- **P2** — Medium. Clear improvement opportunity, contained issue with workarounds.
- **P3** — Low. Minor improvement, low-impact issue, marginal experiment results.
- **P4** — Minimal. Cosmetic, negligible performance, optional investigation.

Base your priority on **evidence from your research** — quantified user impact, error frequency, or scope of affected code paths — not just the signal descriptions.

Respond with a JSON object matching this schema:

<jsonschema>
{schema}
</jsonschema>"""


async def run_multi_turn_research(
    signals: list[SignalData],
    context: CustomPromptSandboxContext,
    *,
    title: str | None = None,
    summary: str | None = None,
    branch: str = "master",
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> ReportResearchOutput:
    """Orchestrate a multi-turn sandbox session that investigates each signal individually."""
    from products.tasks.backend.services.custom_prompt_multi_turn_runner import (
        end_session,
        send_followup,
        start_session,
    )

    total = len(signals)
    if total == 0:
        raise ValueError("No signals to investigate")

    if output_fn:
        output_fn(f"Starting multi-turn research: {total} signal(s)")

    # Turn 1: initial prompt with signal 1
    initial_prompt = build_initial_research_prompt(signals[0], total, title=title, summary=summary)
    session, first_finding = await start_session(
        prompt=initial_prompt,
        context=context,
        model=SignalFinding,
        branch=branch,
        step_name="report_research",
        verbose=verbose,
        output_fn=output_fn,
    )
    findings: list[SignalFinding] = [first_finding]
    if output_fn:
        output_fn(f"Signal 1/{total} done: {first_finding.signal_id}")

    # Turns 2..N: one follow-up per remaining signal
    for i, signal in enumerate(signals[1:], start=2):
        if output_fn:
            output_fn(f"Investigating signal {i}/{total}...")
        followup_prompt = build_signal_investigation_prompt(signal, i, total)
        finding = await send_followup(
            session,
            followup_prompt,
            SignalFinding,
            label=f"signal_{i}_of_{total}",
        )
        findings.append(finding)
        if output_fn:
            output_fn(f"Signal {i}/{total} done: {finding.signal_id}")

    # Actionability assessment
    if output_fn:
        output_fn("Assessing actionability...")
    actionability_prompt = build_actionability_prompt(total)
    actionability_result = await send_followup(
        session,
        actionability_prompt,
        ActionabilityAssessment,
        label="actionability",
    )
    if output_fn:
        output_fn(f"Actionability: {actionability_result.actionability.value}")

    # Priority assessment (only when actionable)
    priority_result: PriorityAssessment | None = None
    if actionability_result.actionability != ActionabilityChoice.NOT_ACTIONABLE:
        if output_fn:
            output_fn("Assessing priority...")
        priority_prompt = build_priority_prompt(total)
        priority_result = await send_followup(
            session,
            priority_prompt,
            PriorityAssessment,
            label="priority",
        )
        if output_fn:
            output_fn(f"Priority: {priority_result.priority.value}")

    await end_session(session)

    logger.info("multi_turn_research: completed with %d findings", len(findings))
    return ReportResearchOutput(
        findings=findings,
        actionability=actionability_result,
        priority=priority_result,
    )
