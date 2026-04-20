"""Report enrichment: gather commit hashes, code paths, and data context for a pre-formed report.

Used by the emit_report workflow to enrich caller-provided reports with code context
before persisting artefacts and checking auto-start conditions.

Multi-turn flow:
1. Code investigation — search the codebase, read implementations, run git blame → CodeInvestigationResult
2. Data investigation — use PostHog MCP to query analytics data, cross-reference with code findings → DataInvestigationResult
3. Final synthesis — combine code + data into the final enrichment finding → ReportEnrichmentFinding
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext, OutputFn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models — one per turn, plus the final output
# ---------------------------------------------------------------------------


class CodeInvestigationResult(BaseModel):
    """Turn 1 output: code paths and commit hashes from codebase investigation."""

    relevant_code_paths: list[str] = Field(
        description=(
            "File paths in the codebase relevant to this report, ordered from most critical first. "
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
    code_summary: str = Field(
        description=(
            "Brief summary of what you found in the code — which components are involved, "
            "how the relevant logic works, and what the commit history reveals."
        ),
    )


class DataInvestigationResult(BaseModel):
    """Turn 2 output: analytics data queried via PostHog MCP."""

    data_queried: str = Field(
        description=(
            "What PostHog MCP queries you ran (e.g. execute-sql, query-run, insight-query) "
            "and what the results showed. If no relevant queries could be run, explain why."
        ),
    )
    additional_code_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Any additional code paths discovered during data investigation that weren't in the "
            "initial code investigation. Empty list if none."
        ),
    )
    additional_commit_hashes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Any additional commit hashes discovered during data investigation. "
            "Same format as before: 'short SHA' -> 'reason'. Empty dict if none."
        ),
    )


class ReportEnrichmentFinding(BaseModel):
    """Final enrichment output — merged code + data investigation results."""

    relevant_code_paths: list[str] = Field(
        description=(
            "File paths in the codebase relevant to this report, ordered from most critical first. "
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


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_WRITING_GUIDE = """<writing_guide>
We use American English.
We use the Oxford comma.
We always use sentence case rather than title case, including in titles, headings, subheadings, or bold text. However if quoting provided text, we keep the original case.
When writing numbers in the thousands to the billions, it's acceptable to abbreviate them (like 10M or 100B - capital letter, no space). If you write out the full number, use commas (like 15,000,000).
We never use the em-dash, only the en-dash (–).
</writing_guide>"""


def build_code_investigation_prompt(title: str, summary: str) -> str:
    """Turn 1: investigate the codebase — find relevant code paths and git blame commit hashes."""
    schema = json.dumps(CodeInvestigationResult.model_json_schema(), indent=2)

    return f"""You are a research agent investigating a report for the PostHog codebase.
This is the first of two investigation steps. In this step, focus entirely on the **codebase** —
find the relevant code paths and use git blame to identify causative commits.

{_WRITING_GUIDE}

The full PostHog repository is available on disk. Use file search, grep, and code reading.

## Report under investigation

**Title:** {title}

**Summary:**
{summary}

## Research protocol

1. **Find the code:** Search the codebase for the feature, component, or code path described in this report. Read the implementation and understand the relevant logic.
2. **Trace the flow:** Follow call chains, imports, and related modules to understand the full scope. Look for `posthog.capture` calls or feature flag checks nearby — these show what the team tracks and gates.
3. **Git blame:** Run `git blame` on the key files/regions to find the commits most relevant to this report. Prioritize causative commits (e.g. the commit that introduced a bug or changed behavior) over general authorship. Include 1–5 commits.

**Budget:** Spend no more than ~10 tool calls on code investigation.

## Output format

Respond with a JSON object matching this schema:

<jsonschema>
{schema}
</jsonschema>"""


def build_data_investigation_prompt() -> str:
    """Turn 2: use PostHog MCP to query analytics data, cross-reference with code findings."""
    schema = json.dumps(DataInvestigationResult.model_json_schema(), indent=2)

    return f"""Good. Now use **PostHog MCP tools** to check the real-world impact of what you found in the code.

Available MCP tools include: `execute-sql`, `query-run`, `read-data-schema`, `insights-get-all`, `experiment-get`, `list-errors`, `feature-flag-get-all`, etc.

## Instructions

1. Query for data that corroborates or contradicts the report's claims — error rates, user counts, conversion metrics, event volumes, etc.
2. If the report references a specific insight, experiment, or feature flag, look it up directly.
3. Cross-reference the data with the code paths you found — does the data match what the code suggests?
4. If you discover additional relevant code paths or commits during data investigation, include them.
5. If no relevant MCP queries can be run for this report, explain why.

**Budget:** Spend no more than ~8 tool calls on data investigation.

## Output format

Respond with a JSON object matching this schema:

<jsonschema>
{schema}
</jsonschema>"""


def build_synthesis_prompt() -> str:
    """Turn 3: combine code + data findings into the final enrichment output."""
    schema = json.dumps(ReportEnrichmentFinding.model_json_schema(), indent=2)

    return f"""Now synthesize your code investigation and data investigation into a single final finding.

Merge the code paths and commit hashes from both turns (deduplicating, keeping the most critical first).
Combine your data_queried notes into a coherent summary of what you queried and found.

## Output format

Respond with a JSON object matching this schema:

<jsonschema>
{schema}
</jsonschema>"""


async def run_report_enrichment(
    title: str,
    summary: str,
    context: CustomPromptSandboxContext,
    *,
    report_id: str | None = None,
    branch: str = "master",
    output_fn: OutputFn = None,
) -> ReportEnrichmentFinding:
    """Run a multi-turn sandbox session to enrich a report with code context.

    Turn 1: Code investigation — search codebase, read implementations, git blame → CodeInvestigationResult
    Turn 2: Data investigation — PostHog MCP queries, cross-reference with code → DataInvestigationResult
    Turn 3: Synthesis — merge code + data into final ReportEnrichmentFinding
    """
    from products.tasks.backend.services.custom_prompt_multi_turn_runner import MultiTurnSession

    if output_fn:
        output_fn("Starting report enrichment (code investigation)...")

    # Turn 1: Code investigation
    initial_prompt = build_code_investigation_prompt(title, summary)
    session, code_result = await MultiTurnSession.start(
        prompt=initial_prompt,
        context=context,
        model=CodeInvestigationResult,
        branch=branch,
        step_name="report_enrichment",
        output_fn=output_fn,
        origin_product="signal_report",
        signal_report_id=report_id,
    )

    # Record the research task relationship immediately after task creation
    if report_id:
        from products.signals.backend.models import SignalReportTask

        await SignalReportTask.objects.acreate(
            team_id=context.team_id,
            report_id=report_id,
            task_id=str(session.task.id),
            relationship=SignalReportTask.Relationship.RESEARCH,
        )

    if output_fn:
        output_fn(
            f"Code investigation done: {len(code_result.relevant_code_paths)} code paths, "
            f"{len(code_result.relevant_commit_hashes)} commits. Querying analytics data..."
        )

    # Turn 2: Data investigation
    data_prompt = build_data_investigation_prompt()
    data_result = await session.send_followup(
        data_prompt,
        DataInvestigationResult,
        label="data_investigation",
    )

    if output_fn:
        output_fn("Data investigation done. Synthesizing final finding...")

    # Turn 3: Synthesis
    synthesis_prompt = build_synthesis_prompt()
    finding = await session.send_followup(
        synthesis_prompt,
        ReportEnrichmentFinding,
        label="synthesis",
    )

    await session.end()

    if output_fn:
        output_fn(
            f"Enrichment complete: {len(finding.relevant_code_paths)} code paths, "
            f"{len(finding.relevant_commit_hashes)} commits"
        )

    logger.info(
        "run_report_enrichment: completed",
        extra={
            "report_id": report_id,
            "code_paths": len(finding.relevant_code_paths),
            "commit_hashes": len(finding.relevant_commit_hashes),
            "code_only_paths": len(code_result.relevant_code_paths),
            "code_only_commits": len(code_result.relevant_commit_hashes),
            "additional_paths_from_data": len(data_result.additional_code_paths),
            "additional_commits_from_data": len(data_result.additional_commit_hashes),
        },
    )
    return finding
