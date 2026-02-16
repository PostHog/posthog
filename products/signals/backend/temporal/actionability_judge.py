import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import structlog
import temporalio
from pydantic import BaseModel, Field

from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.temporal.llm import call_llm
from products.signals.backend.temporal.types import SignalData, render_signals_to_text

logger = structlog.get_logger(__name__)


class ActionabilityChoice(str, Enum):
    IMMEDIATELY_ACTIONABLE = "immediately_actionable"
    REQUIRES_HUMAN_INPUT = "requires_human_input"
    NOT_ACTIONABLE = "not_actionable"


class ActionabilityJudgeResponse(BaseModel):
    choice: ActionabilityChoice = Field(description="The actionability judgment")
    explanation: str = Field(
        description="3-6 sentence explanation of the decision, required unless choice is immediately_actionable",
    )


ACTIONABILITY_JUDGE_SYSTEM_PROMPT = """You are an actionability judge reviewing a signal report to determine whether it can be acted on by an autonomous coding agent.

The coding agent that would receive this report has:
- MCP access to PostHog tools (analytics, feature flags, experiments, session replays, etc.)
- Code access to the underlying codebase the report is about, with the ability to write and open PRs
- The ability to execute commands in a sandboxed environment

You must classify the report into one of three categories:

1. "immediately_actionable" — The coding agent could take ANY concrete, useful action right now with little ambiguity. Examples:
   - Bug fixes: the report identifies a bug or error that can be fixed in code
   - Experiment reactions: the report describes an A/B test result that warrants a code change (e.g., rolling out the winning variant, removing losing variant code)
   - Feature flag cleanup: the report identifies a feature flag that should be cleaned up (removing references in code, disabling the flag)
   - User experience issues: the report identifies UX problems observed in session data that can be addressed in code
   - Deep investigation: slightly surprisingly, one possible action the agent can take is to deep dive into a report, looking at code context and querying posthog data. The agent
     is able to ask for human input once the investigation is complete, so if the report clearly outlines an issue and provides a lot of "jumping off" context for a deeper dive,
     even though the agent might not be able to immediately make a code change, it's able to take immediately useful actions.

2. "requires_human_input" — The report describes something actionable, but a human needs to make a decision before a coding agent should proceed.
   Crucially, reports where the coding agent could usefully do _some_ portion of work up-front, with human judgement only being required far into implementation, are immediately actionable.
   Examples include:
   - The report suggests a code change but the correct approach depends on business context or product strategy
   - Multiple valid courses of action exist and picking one requires human judgment
   - The report identifies an issue but the fix involves trade-offs a human should weigh
   - It is purely informational with no clear code action (e.g., "traffic increased 10% this week")

3. "not_actionable" — The report lacks sufficient context for either a coding agent or a human to derive a useful immediate action, without a large amount of additional information.
   - The signals are too vague or contradictory to derive a specific action
   - There's some evidence of an issue, but insufficient evidence to determine its root cause, or that it's not transient
   - It describes expected/normal product behavior

When in doubt between "immediately_actionable" and "requires_human_input", choose "immediately_actionable" - again, if the coding agent has _any_ unambiguous actions it can take immediately, it should.
When in doubt between "requires_human_input" and "not_actionable", choose "not_actionable" - we want to filter out noise as much as possible.

Respond with a JSON object:
- "choice": one of "immediately_actionable", "requires_human_input", or "not_actionable"
- "explanation": a 3-6 sentence explanation of your reasoning.

Return ONLY valid JSON, no other text. The first token of output must be {"""


def _build_actionability_judge_prompt(
    title: str,
    summary: str,
    signals: list[SignalData],
) -> str:
    return f"""REPORT TO ASSESS:

Title: {title}
Summary: {summary}

UNDERLYING SIGNALS:

{render_signals_to_text(signals)}"""


async def judge_report_actionability(
    title: str,
    summary: str,
    signals: list[SignalData],
) -> ActionabilityJudgeResponse:
    user_prompt = _build_actionability_judge_prompt(title, summary, signals)

    def validate(text: str) -> ActionabilityJudgeResponse:
        data = json.loads(text)
        result = ActionabilityJudgeResponse.model_validate(data)

        # Require explanation for non-immediately-actionable outcomes
        if result.choice != ActionabilityChoice.IMMEDIATELY_ACTIONABLE and not result.explanation.strip():
            raise ValueError(f"Explanation is required when choice is {result.choice.value}")

        return result

    return await call_llm(
        system_prompt=ACTIONABILITY_JUDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        validate=validate,
        thinking=True,
    )


@dataclass
class ActionabilityJudgeInput:
    team_id: int
    report_id: str
    title: str
    summary: str
    signals: list[SignalData]


@dataclass
class ActionabilityJudgeOutput:
    choice: str  # ActionabilityChoice value, serialized for temporal transport
    explanation: Optional[str]


@temporalio.activity.defn
async def actionability_judge_activity(input: ActionabilityJudgeInput) -> ActionabilityJudgeOutput:
    """Assess report actionability and store result as artefact."""
    try:
        result = await judge_report_actionability(
            title=input.title,
            summary=input.summary,
            signals=input.signals,
        )

        # Store judgment as a report artefact
        artefact_content = json.dumps(
            {
                "choice": result.choice.value,
                "explanation": result.explanation,
            }
        ).encode("utf-8")

        await SignalReportArtefact.objects.acreate(
            team_id=input.team_id,
            report_id=input.report_id,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=artefact_content,
        )

        logger.debug(
            f"Actionability judge assessed report {input.report_id}",
            report_id=input.report_id,
            choice=result.choice.value,
        )
        return ActionabilityJudgeOutput(
            choice=result.choice.value,
            explanation=result.explanation if result.choice != ActionabilityChoice.IMMEDIATELY_ACTIONABLE else None,
        )
    except Exception as e:
        logger.exception(
            f"Failed to run actionability judge for report {input.report_id}: {e}",
            report_id=input.report_id,
        )
        raise
