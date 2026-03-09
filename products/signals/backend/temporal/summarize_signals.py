import json
from dataclasses import dataclass

import structlog
import temporalio
from pydantic import BaseModel, Field

from products.signals.backend.temporal.llm import call_llm
from products.signals.backend.temporal.types import SignalData, render_signals_to_text

logger = structlog.get_logger(__name__)


class SummarizeSignalsResponse(BaseModel):
    title: str = Field(description="A short, descriptive title for the report (max 75 chars)", max_length=75)
    summary: str = Field(
        description="An Axios-style summary with 'Why it matters', 'What's happening', and 'The bottom line' sections"
    )


SUMMARIZE_SYSTEM_PROMPT = """You are a product analytics assistant. Your job is to summarize a collection of related signals into a concise report, written in the Axios Smart Brevity style.

Signals come from diverse sources: exceptions, experiments, insight alerts, session behaviour analysis, and more.
They have been grouped together because they share a common underlying cause.

Signals have a weight - this is a number, between 0 and 1, representing how important the signal is. Signals with higher weights are more important.

Signal groups have a weight equal to the sum of all their signals' weights, and when the group has a weight of 1, you're asked to produce a report about them.

The report you produce will be consumed by both humans and coding agents with access to the underlying codebase.

Given a list of signals, produce a JSON object with two fields:

1. "title": A short, declarative headline (max 75 chars). Lead with the most newsworthy takeaway, not a label.

2. "summary": An Axios-style brief using these sections, each on its own line:
   - **Why it matters:** One sentence on the business or user impact. This is the most important part — lead with it.
   - **What's happening:** 1-2 sentences on the concrete facts. Reference specific signals, error types, metrics, or patterns.
   - **The bottom line:** One sentence with the specific, actionable next step — a code change, investigation, or decision.

Style rules:
- Be direct and specific. Every sentence must carry information.
- No filler phrases ("various issues detected", "it's worth noting", "in summary").
- Use plain language. No jargon unless the audience needs it (they're engineers).
- Bold the section labels exactly as shown above.

Respond with ONLY valid JSON, no other text. The first token of output must be {"""


def _build_summarize_prompt(signals: list[SignalData]) -> str:
    return f"""SIGNALS TO SUMMARIZE:

<signal_data>
{render_signals_to_text(signals)}
</signal_data>"""


async def summarize_signals(signals: list[SignalData]) -> tuple[str, str]:
    """
    Summarize a list of signals into a title and summary.

    Returns:
        Tuple of (title, summary)
    """
    user_prompt = _build_summarize_prompt(signals)

    def validate(text: str) -> tuple[str, str]:
        data = json.loads(text)
        result = SummarizeSignalsResponse.model_validate(data)
        return result.title, result.summary

    return await call_llm(
        system_prompt=SUMMARIZE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        validate=validate,
        temperature=0.2,
    )


@dataclass
class SummarizeSignalsInput:
    report_id: str
    signals: list[SignalData]


@dataclass
class SummarizeSignalsOutput:
    title: str
    summary: str


@temporalio.activity.defn
async def summarize_signals_activity(input: SummarizeSignalsInput) -> SummarizeSignalsOutput:
    """Summarize signals into a title and summary for the report."""
    try:
        title, summary = await summarize_signals(input.signals)
        logger.debug(
            f"Summarized {len(input.signals)} signals for report {input.report_id}",
            report_id=input.report_id,
            signal_count=len(input.signals),
            title=title,
        )
        return SummarizeSignalsOutput(title=title, summary=summary)
    except Exception as e:
        logger.exception(
            f"Failed to summarize signals for report {input.report_id}: {e}",
            report_id=input.report_id,
        )
        raise
