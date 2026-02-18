import json
from dataclasses import dataclass

import structlog
import temporalio
from pydantic import BaseModel, Field

from products.signals.backend.temporal.llm import call_llm
from products.signals.backend.temporal.types import SignalData, render_signals_to_text

logger = structlog.get_logger(__name__)


class ReportDescription(BaseModel):
    title: str = Field(description="A short, descriptive title for the report (max 100 chars)")
    summary: str = Field(description="A 2-4 sentence summary of the key findings for this topic")


class CoherenceJudgeResponse(BaseModel):
    reports: list[ReportDescription] = Field(
        description="One report if the signals are coherent, multiple if they should be split by topic",
        min_length=1,
    )


COHERENCE_JUDGE_SYSTEM_PROMPT = """You are a signal analysis judge. You will be given a collection of signals that have been grouped together.

Your job is twofold:
1. Determine whether these signals genuinely relate to a single cohesive topic, or whether the group has become incoherent — covering multiple distinct, unrelated topics that should be split into separate reports.
2. Produce a title and summary for each report.

Signals come from diverse sources: exceptions, experiments, insight alerts, session behaviour analysis, and more.
Signals CAN be different types and still be coherent — what matters is whether they share a common root cause, affected feature, or user journey.

Examples of COHERENT groups (should NOT be split):
- An experiment result + error spike + session anomaly all related to the same checkout flow redesign
- Multiple error signals all stemming from the same database migration
- A feature flag change + performance degradation + user behaviour shift all tied to the same feature rollout

Examples of INCOHERENT groups (SHOULD be split):
- Signals about a payment processing bug mixed with signals about an unrelated onboarding flow experiment
- Error tracking signals from completely different services with no shared root cause
- A dashboard performance issue grouped with an unrelated mobile app crash pattern
- Multiple bug reports about the same feature or product, but describing different issues that require distinct code changes to fix

If the signals form a single coherent topic, return exactly ONE report with a title and summary.
If the signals span multiple distinct topics, return one report PER topic — each with its own title and summary.

Each report should have:
- A title (max 100 chars) that captures the essence of that topic
- A summary (2-4 sentences) that explains what the signals indicate, the potential impact, and any patterns observed

Signals have a weight between 0 and 1 representing importance. Higher weight = more important.

The reports you produce will be consumed by both humans and coding agents with access to the underlying codebase.
Be specific and actionable. Avoid generic phrases like "various issues detected". The goal is to give the jumping off point for a code change, or other specific action, in response to observed patterns or trends.

When splitting, every signal in the original group should logically belong to exactly one of the new reports.

Be conservative about splitting — only split when the topics are genuinely distinct. Superficial differences in signal type or source don't make a group incoherent. The bar for splitting should be high: the topics must be clearly unrelated.

Respond with a JSON object containing a "reports" array:
- Single topic: {"reports": [{"title": "...", "summary": "..."}]}
- Multiple topics: {"reports": [{"title": "...", "summary": "..."}, {"title": "...", "summary": "..."}, ...]}

Return ONLY valid JSON, no other text. The first token of output must be {"""


def _build_coherence_judge_prompt(signals: list[SignalData]) -> str:
    return f"""SIGNALS TO ANALYZE:

{render_signals_to_text(signals)}"""


async def judge_report_coherence(
    signals: list[SignalData],
) -> CoherenceJudgeResponse:
    user_prompt = _build_coherence_judge_prompt(signals)

    def validate(text: str) -> CoherenceJudgeResponse:
        data = json.loads(text)
        result = CoherenceJudgeResponse.model_validate(data)

        if len(result.reports) == 0:
            raise ValueError("Must return at least one report")

        for i, report in enumerate(result.reports):
            if len(report.title) > 100:
                raise ValueError(f"Report {i} title exceeds 100 characters")
            if not report.title.strip():
                raise ValueError(f"Report {i} title is empty")
            if not report.summary.strip():
                raise ValueError(f"Report {i} summary is empty")

        return result

    return await call_llm(
        system_prompt=COHERENCE_JUDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        validate=validate,
        thinking=True,
    )


@dataclass
class CoherenceJudgeInput:
    team_id: int
    report_id: str
    signals: list[SignalData]


@dataclass
class NewReportInfo:
    title: str
    summary: str


@dataclass
class CoherenceJudgeOutput:
    reports: list[NewReportInfo]


@temporalio.activity.defn
async def coherence_judge_activity(input: CoherenceJudgeInput) -> CoherenceJudgeOutput:
    try:
        result = await judge_report_coherence(signals=input.signals)

        reports = [NewReportInfo(title=r.title, summary=r.summary) for r in result.reports]

        if len(reports) == 1:
            logger.debug(
                f"Coherence judge: report {input.report_id} is coherent",
                report_id=input.report_id,
            )
        else:
            logger.info(
                f"Coherence judge: report {input.report_id} is incoherent, splitting into {len(reports)} reports",
                report_id=input.report_id,
                new_report_count=len(reports),
            )

        return CoherenceJudgeOutput(reports=reports)

    except Exception as e:
        logger.exception(
            f"Failed to run coherence judge for report {input.report_id}: {e}",
            report_id=input.report_id,
        )
        raise
