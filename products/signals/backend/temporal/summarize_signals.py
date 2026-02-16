import json
from dataclasses import dataclass

import structlog
import temporalio
from pydantic import BaseModel, Field

from products.signals.backend.temporal.llm import call_llm
from products.signals.backend.temporal.types import SignalData, render_signals_to_text

logger = structlog.get_logger(__name__)


class SummarizeSignalsResponse(BaseModel):
    title: str = Field(description="A short, descriptive title for the report (max 100 chars)")
    summary: str = Field(description="A 2-4 sentence summary of the key findings")


SUMMARIZE_SYSTEM_PROMPT = """You are a product analytics assistant. Your job is to summarize a collection of related signals into a concise report.

Signals come from diverse sources: exceptions, experiments, insight alerts, session behaviour analysis, and more.
They have been grouped together because they share a common underlying cause.

Given a list of signals, produce:
1. A short, descriptive title (max 100 characters) that captures the essence of what these signals are about
2. A 2-4 sentence summary that explains:
   - What the signals indicate
   - The potential impact or significance
   - Any patterns or trends observed

Signals have a weight - this is a number, between 0 and 1, representing how important the signal is. Signals with higher weights are more important.

Signal groups have a weight equal to the sum of all their signals' weights, and when the group has a weight of 1, you're asked to produce a report about them.

The report you produce will be consumed by both humans and coding agents with access to the underlying codebase.
Be specific and actionable. Avoid generic phrases like "various issues detected". The goal of the report is to give the jumping off point for a
code change, or other specific action, in response to some observed pattern or trend in the users product.

Respond with a JSON object containing "title" and "summary" fields. Return ONLY valid JSON, no other text. The first token of output must be {"""


def _build_summarize_prompt(signals: list[SignalData]) -> str:
    return "SIGNALS TO SUMMARIZE:\n\n" + render_signals_to_text(signals)


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

        if len(result.title) > 100:
            raise ValueError("Title exceeds maximum length")

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
