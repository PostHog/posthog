from __future__ import annotations

import json
import logging
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from products.signals.backend.temporal.types import SignalData, _render_extra_to_text


class ActionabilityChoice(str, Enum):
    IMMEDIATELY_ACTIONABLE = "immediately_actionable"
    REQUIRES_HUMAN_INPUT = "requires_human_input"
    NOT_ACTIONABLE = "not_actionable"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


if TYPE_CHECKING:
    from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext, OutputFn

logger = logging.getLogger(__name__)

# TODO: Signals deduplication step before the research


class SignalFinding(BaseModel):
    signal_id: str = Field(description="The signal_id from the input signal list")
    relevant_code_paths: list[str] = Field(
        description=(
            "File paths in the codebase relevant to this signal, ordered from most critical first. "
            "The first path should be the highest-impact file (e.g. the buggy module or core feature file). "
            "Then include supporting paths."
        ),
    )
    relevant_commit_hashes: dict[str, str] = Field(
        default_factory=dict,
        json_schema_extra={"minProperties": 1},
        description=(
            "A mapping of 'git commit short SHA (7 characters)' -> 'reason'. "
            "Values are short explanations of WHY each commit is relevant. "
            "Use `git blame` on the most critical code paths to identify commits that caused, or are most closely related to, "
            "the issue described by this report. Prioritize causative commits "
            "(e.g. the commit that introduced a bug) over general authorship commits. Include 1-5 commits."
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
    actionability: ActionabilityChoice = Field(
        description="Overall actionability assessment. Must be one of the allowed enum values — do not invent new ones.",
    )
    already_addressed: bool = Field(
        description=(
            "Whether the core issue described by this report appears to have been "
            "already fixed or addressed in recent code changes. Tracked separately from `actionability`."
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


class ReportPresentationOutput(BaseModel):
    title: str = Field(
        description="""
A PR-style title (max 70 chars) scoped to one concrete concern.
It should read like a pull request title that one engineer could ship in a single PR. Target one feature, one bug, one component, or one tightly-scoped change.
Follow the Conventional Commits style (sentence-cased).
If the report already has a title that is PR-specific and still accurate after your research, keep it — don't replace a good PR title with a vaguer one.
- Good: fix(date-picker): Handle timezone conversion in insights
- Good: feat(funnel): Add percentile options to Time to Convert
- Bad: fix(funnel): various funnel improvements and bug fixes
- Bad: multiple analytics issues
        """,
        max_length=96,  # Generous enough for descriptive PR-style titles
    )
    summary: str = Field(
        description="""
An Axios-style summary in four brief paragraphs:
- A one-sentence "why it matters" tl;dr of the report. Ideally start with "Users …", explaining how users are being impacted, how many, or how important they are. If users aren't impacted, but the team building the product is, describe that. Otherwise, just describe what's going on.
- '**What's happening:** …' - a brief description of the concrete facts, expanding on the tl;dr sentence. Reference specific signals, errors, metrics, or patterns. Use available tools to do research here like a product manager would.
- '**Root cause:** …' - dig as deep as you can into the root cause of the issue, and explain it in plain terms. Use concrete references to problematic APIs or UI elements, so that the engineer familiar with the code understands this.
- '**How to resolve:** …' - a single, concrete action plan for the code-level fix that addresses the root cause directly. Skip if the report is not actionable.

Principles:
- Be direct and specific. Every sentence must carry information.
- No filler phrases ("various issues detected", "it's worth noting").
- Bold the section labels exactly as shown above.
"""
    )

    @field_validator("title", "summary")
    @classmethod
    def fields_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title and summary must not be empty")
        return v


class ReportResearchOutput(BaseModel):
    title: str = Field(description="Generated report title.")
    summary: str = Field(description="Generated factual report summary.")
    findings: list[SignalFinding] = Field(
        description="One finding per signal in the report, in the same order as the input signals.",
    )
    actionability: ActionabilityAssessment = Field(description="Actionability assessment.")
    priority: PriorityAssessment | None = Field(
        default=None, description="Priority assessment. None when not actionable."
    )


def _render_existing_report_context(previous_report_id: str | None) -> str:
    if not previous_report_id:
        return ""

    return (
        "\n---\n\n## Existing report context\n\n"
        f"**Report ID:** `{previous_report_id}`\n\n"
        "This is a re-research of an existing report. "
        "If a signal already has previous findings, validate them lightly first and reuse them if they still hold. "
        "Only re-research deeply when the old evidence looks stale or no longer matches the codebase.\n"
    )


def _render_previous_finding_context(previous_finding: SignalFinding | None) -> str:
    if previous_finding is None:
        return ""

    finding_json = previous_finding.model_dump_json(indent=2)
    return f"""
## Previous finding for this signal

This signal was already analyzed in an earlier report run.

- First, lightly validate whether the cited code paths still exist and whether the previous claim still appears true.
- If the previous finding is still valid, reuse it with only minimal edits and avoid deep re-research.
- If the old code paths are stale or the evidence no longer holds, investigate the signal as new.
- When lightly validating a previous finding, aim to spend fewer tool calls than a fresh investigation.

Previous finding:

```json
{finding_json}
```"""


def _render_previous_actionability_context(previous_actionability: ActionabilityAssessment | None) -> str:
    if previous_actionability is None:
        return ""

    assessment_json = previous_actionability.model_dump_json(indent=2)
    return f"""## Previous actionability assessment

This report was previously assessed as:

```json
{assessment_json}
```

Decide whether the updated set of signal findings changes that assessment.

- If it still holds, keep the assessment materially the same and update the explanation only as much as needed.
- If it changed, return the new assessment and explain what changed.
"""


def _render_previous_priority_context(previous_priority: PriorityAssessment | None) -> str:
    if previous_priority is None:
        return ""

    priority_json = previous_priority.model_dump_json(indent=2)
    return f"""## Previous priority assessment

This report was previously prioritized as:

```json
{priority_json}
```

Decide whether the updated set of signal findings changes that priority.

- If it still holds, keep the priority materially the same and update the explanation only as much as needed.
- If it changed, return the new priority and explain what changed.
"""


def _render_previous_presentation_context(previous_title: str | None, previous_summary: str | None) -> str:
    if not previous_title and not previous_summary:
        return ""

    parts = ["## Previous title and summary", "", "This report previously used:"]
    if previous_title:
        parts.append(f"- **Title:** {previous_title}")
    if previous_summary:
        parts.append(f"- **Summary:** {previous_summary}")
    parts.extend(
        [
            "",
            "If they are still accurate after incorporating the latest findings, keep them materially the same and edit minimally.",
            "If the new findings change the shape of the report, update them.",
        ]
    )
    return "\n".join(parts)


def _render_signal_for_research(signal: SignalData, index: int, total: int) -> str:
    """Render a single signal for the research prompt, with numbering."""
    lines = [f"### Signal {index}/{total} (id: `{signal.signal_id}`)"]
    lines.append(f"- **Source:** {signal.source_product} / {signal.source_type}")
    lines.append(f"- **Source ID:** {signal.source_id}")
    lines.append(f"- **Weight:** {signal.weight}")
    lines.append(f"- **Timestamp:** {signal.timestamp}")
    lines.append(f"- **Description:** {signal.content}")
    if signal.extra:
        lines.append("#### Extras")
        lines.extend(_render_extra_to_text(signal.extra))
    return "\n".join(lines)


_RESEARCH_PREAMBLE = """You are a research agent investigating a signal report for the PostHog codebase.
Your findings will be passed downstream to a coding agent that will act on this report — thorough, evidence-based research here directly improves the quality of the coding agent's work.

<writing_guide>
We use American English.
We use the Oxford comma.
We always use sentence case rather than title case, including in titles, headings, subheadings, or bold text. However if quoting provided text, we keep the original case.
When writing numbers in the thousands to the billions, it's acceptable to abbreviate them (like 10M or 100B - capital letter, no space). If you write out the full number, use commas (like 15,000,000).
We never use the em-dash, only the en-dash (–).
</writing_guide>

You have two investigation tools:
1. **The codebase** — the full PostHog repository is available on disk. Use file search, grep, and code reading.
2. **PostHog MCP** — you can query PostHog analytics data via MCP tools like `execute-sql`, `query-run`, `read-data-schema`, `insights-get-all`, `experiment-get`, `list-errors`, `feature-flag-get-all`, etc.

When a signal includes **Attached images**, the URLs are publicly reachable — fetch them directly to inspect screenshots, UI issues, or other visual evidence."""

_RESEARCH_PROTOCOL = """## Research protocol

For each signal, find **code evidence** and **data evidence**:

- **Code:** Trace the code path behind the signal's claim — find the relevant files, read the implementation, and understand how the logic actually works. Even if the signal doesn't mention specific files, search for the feature/component and dig in. Also look for `posthog.capture` calls or feature flag checks nearby — these show what the team tracks and gates, which helps gauge importance.
- **Git blame:** Once you've identified the most critical code paths, run `git blame` on the key files/regions to find the commits most relevant to this signal. Prioritize causative commits (e.g. the commit that introduced a bug or changed behavior) over general authorship. If no causative commit is clear, include the commits that authored the bulk of the relevant code.
- **Data:** Use PostHog MCP tools (`execute-sql`, `query-run`, `read-data-schema`, etc.) to check real impact — error rates, user counts, conversion metrics. If the signal references a specific insight, experiment, or feature flag, look it up directly.

Cross-reference code and data — does the data corroborate what the code suggests?

**Budget:** Spend no more than ~10 tool calls per signal. If you can't verify a signal's claim after that, mark it unverified and move on."""

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
    previous_report_id: str | None = None,
    previous_finding: SignalFinding | None = None,
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

    existing_report_context = _render_existing_report_context(previous_report_id)
    previous_finding_context = _render_previous_finding_context(previous_finding)
    investigation_instruction = (
        "You will investigate **{total_signals} signal(s)** one at a time. I will send each signal in a separate "
        "message. For signals with previous findings, validate them lightly first and reuse them if they still "
        "hold. Investigate genuinely new or stale signals thoroughly, then respond with a `SignalFinding` JSON "
        "object."
        if previous_report_id or previous_finding
        else "You will investigate **{total_signals} signal(s)** one at a time. I will send each signal in a "
        "separate message. For each one, investigate it thoroughly then respond with a `SignalFinding` JSON object."
    )

    return f"""{_RESEARCH_PREAMBLE}

{investigation_instruction.format(total_signals=total_signals)}
{report_context}
{existing_report_context}
---

{_RESEARCH_PROTOCOL}

---

## Signal 1 of {total_signals}

{signal_block}
{previous_finding_context}

---

## Output format

Investigate this signal, then respond with a JSON object matching this schema:

<jsonschema>
{finding_schema}
</jsonschema>"""


def build_signal_investigation_prompt(
    signal: SignalData,
    index: int,
    total: int,
    *,
    previous_finding: SignalFinding | None = None,
) -> str:
    """Build a follow-up prompt for signal N (2..total)."""
    signal_block = _render_signal_for_research(signal, index, total)
    finding_schema = json.dumps(SignalFinding.model_json_schema(), indent=2)
    previous_finding_context = _render_previous_finding_context(previous_finding)

    return f"""## Signal {index} of {total}

{signal_block}
{previous_finding_context}

---

If this signal substantially overlaps with one you already investigated, reference your earlier finding and focus only on what's new or different — don't re-investigate the same code paths and data.

Investigate this signal using the same protocol, then respond with a JSON object matching this schema:

<jsonschema>
{finding_schema}
</jsonschema>"""


def build_actionability_prompt(
    total_signals: int,
    *,
    previous_actionability: ActionabilityAssessment | None = None,
) -> str:
    """Build the prompt asking for an actionability assessment after all signals are investigated."""
    schema = json.dumps(ActionabilityAssessment.model_json_schema(), indent=2)
    previous_actionability_context = _render_previous_actionability_context(previous_actionability)

    return f"""You have investigated all {total_signals} signal(s). Now assess: **is this report actionable?**

{_ACTIONABILITY_CRITERIA}

{previous_actionability_context}

Consider all your findings together.

Respond with a JSON object matching this schema:

<jsonschema>
{schema}
</jsonschema>"""


# TODO: When deciding on priority - also look at top N reports now, to decide if it should be higher/lower?


def build_priority_prompt(
    total_signals: int,
    *,
    previous_priority: PriorityAssessment | None = None,
) -> str:
    """Build the prompt asking for a priority assessment (only sent when actionable)."""
    schema = json.dumps(PriorityAssessment.model_json_schema(), indent=2)
    previous_priority_context = _render_previous_priority_context(previous_priority)

    return f"""Now assess the **priority** of this report based on your research across all {total_signals} signal(s).

## Priority criteria

- **P0** — Critical. Production errors, core flow broken, data loss, security vulnerability.
- **P1** — High. Significant user-facing impact, statistically significant regression, notable error rate increase.
- **P2** — Medium. Clear improvement opportunity, contained issue with workarounds.
- **P3** — Low. Minor improvement, low-impact issue, marginal experiment results.
- **P4** — Minimal. Cosmetic, negligible performance, optional investigation.

{previous_priority_context}

Base your priority on **evidence from your research** — quantified user impact, error frequency, or scope of affected code paths — not just the signal descriptions.

Respond with a JSON object matching this schema:

<jsonschema>
{schema}
</jsonschema>"""


def build_report_presentation_prompt(
    total_signals: int,
    *,
    previous_title: str | None = None,
    previous_summary: str | None = None,
) -> str:
    schema = json.dumps(ReportPresentationOutput.model_json_schema(), indent=2)
    previous_presentation_context = _render_previous_presentation_context(previous_title, previous_summary)

    return f"""Now write the final **report title and summary** based on your research across all {total_signals} signal(s).

Style rules:
{previous_presentation_context}

Respond with a JSON object matching this schema:

<jsonschema>
{schema}
</jsonschema>"""


def _enforce_signal_id(finding: SignalFinding, expected_id: str) -> SignalFinding:
    """Correct the finding's signal_id if the model returned a wrong one."""
    if finding.signal_id != expected_id:
        logger.exception(
            "Signal ID mismatch: expected %s, got %s — correcting",
            expected_id,
            finding.signal_id,
        )
        finding = finding.model_copy(update={"signal_id": expected_id})
    return finding


async def run_multi_turn_research(
    signals: list[SignalData],
    context: CustomPromptSandboxContext,
    *,
    title: str | None = None,
    summary: str | None = None,
    previous_report_id: str | None = None,
    previous_report_research: ReportResearchOutput | None = None,
    branch: str | None = None,
    verbose: bool = False,
    output_fn: OutputFn = None,
    signal_report_id: str | None = None,
) -> ReportResearchOutput:
    """Orchestrate a multi-turn sandbox session that investigates each signal individually."""
    from products.tasks.backend.models import Task
    from products.tasks.backend.services.custom_prompt_multi_turn_runner import MultiTurnSession

    total = len(signals)
    if total == 0:
        raise ValueError("No signals to investigate")

    previous_findings_by_signal_id = (
        {finding.signal_id: finding for finding in previous_report_research.findings}
        if previous_report_research
        else {}
    )

    if output_fn:
        if previous_report_research:
            output_fn(f"Starting report update research: {total} signal(s)")
        else:
            output_fn(f"Starting multi-turn research: {total} signal(s)")

    # Turn 1: initial prompt + signal 1
    initial_prompt = build_initial_research_prompt(
        signals[0],
        total,
        title=title,
        summary=summary,
        previous_report_id=previous_report_id,
        previous_finding=previous_findings_by_signal_id.get(signals[0].signal_id),
    )
    session, first_finding = await MultiTurnSession.start(
        prompt=initial_prompt,
        context=context,
        model=SignalFinding,
        branch=branch,
        step_name="report_research",
        verbose=verbose,
        output_fn=output_fn,
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        signal_report_id=signal_report_id,
        internal=True,
    )

    # Record the research task relationship immediately after task creation
    if signal_report_id:
        from products.signals.backend.models import SignalReportTask

        await SignalReportTask.objects.acreate(
            team_id=context.team_id,
            report_id=signal_report_id,
            task_id=str(session.task.id),
            relationship=SignalReportTask.Relationship.RESEARCH,
        )

    first_finding = _enforce_signal_id(first_finding, signals[0].signal_id)
    findings: list[SignalFinding] = [first_finding]
    if output_fn:
        output_fn(f"Signal 1/{total} done: {first_finding.signal_id}")

    # Turns 2..N: one follow-up per remaining signal
    for i, signal in enumerate(signals[1:], start=2):
        if output_fn:
            output_fn(f"Investigating signal {i}/{total}...")
        followup_prompt = build_signal_investigation_prompt(
            signal,
            i,
            total,
            previous_finding=previous_findings_by_signal_id.get(signal.signal_id),
        )
        finding = await session.send_followup(
            followup_prompt,
            SignalFinding,
            label=f"signal_{i}_of_{total}",
        )
        finding = _enforce_signal_id(finding, signal.signal_id)
        findings.append(finding)
        if output_fn:
            output_fn(f"Signal {i}/{total} done: {finding.signal_id}")

    # Actionability assessment
    if output_fn:
        output_fn("Assessing actionability...")
    actionability_prompt = build_actionability_prompt(
        total,
        previous_actionability=previous_report_research.actionability if previous_report_research else None,
    )
    actionability_result = await session.send_followup(
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
        priority_prompt = build_priority_prompt(
            total,
            previous_priority=previous_report_research.priority if previous_report_research else None,
        )
        priority_result = await session.send_followup(
            priority_prompt,
            PriorityAssessment,
            label="priority",
        )
        if output_fn:
            output_fn(f"Priority: {priority_result.priority.value}")

    if output_fn:
        output_fn("Generating title and summary...")
    presentation_prompt = build_report_presentation_prompt(
        total,
        previous_title=title or (previous_report_research.title if previous_report_research else None),
        previous_summary=summary or (previous_report_research.summary if previous_report_research else None),
    )
    presentation_result = await session.send_followup(
        presentation_prompt,
        ReportPresentationOutput,
        label="presentation",
    )
    if output_fn:
        output_fn(f"Report title: {presentation_result.title}")

    await session.end()

    logger.info("multi_turn_research: completed with %d findings", len(findings))
    return ReportResearchOutput(
        title=presentation_result.title,
        summary=presentation_result.summary,
        findings=findings,
        actionability=actionability_result,
        priority=priority_result,
    )
