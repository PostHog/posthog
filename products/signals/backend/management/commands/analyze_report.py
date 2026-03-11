import json
import asyncio
import logging

from django.core.management.base import BaseCommand

from pydantic import BaseModel, Field

from products.signals.backend.report_generation.executor import run_sandbox_agent_get_structured_output
from products.signals.backend.temporal.actionability_judge import ACTIONABILITY_JUDGE_SYSTEM_PROMPT
from products.signals.backend.temporal.types import SignalData, render_signals_to_text

logger = logging.getLogger(__name__)

# Simulated signals from 3 related GitHub issues about funnel enhancements
TEST_SIGNALS = [
    SignalData(
        signal_id="test-funnel-compare-42606",
        content=(
            "Feature request: Compare against previous option for funnel insights. "
            "Customer would be able to select two arbitrary intervals (week, month etc) and compare "
            "the % change in conversion between those two periods. Current workaround is HogQL "
            "breakdown like toString(toISOWeek(timestamp))."
        ),
        source_product="github_issues",
        source_type="enhancement",
        source_id="42606",
        weight=0.5,
        timestamp="2025-12-03T16:21:28Z",
        extra={
            "labels": ["feature/funnels", "team/product-analytics"],
            "url": "https://github.com/PostHog/posthog/issues/42606",
        },
    ),
    SignalData(
        signal_id="test-funnel-binwidth-42995",
        content=(
            "Feature request: Configurable bin width for funnel Time to Convert histogram. "
            "The Time to Convert histogram calculates bin width dynamically based on max conversion "
            "time / number of bins. Bin boundaries shift when data distribution changes, making it "
            "harder to track trends over time or compare across date ranges. Request for fixed bin "
            "width option (e.g., '1 minute per bin'). From Zendesk support ticket."
        ),
        source_product="github_issues",
        source_type="enhancement",
        source_id="42995",
        weight=0.5,
        timestamp="2025-12-09T00:56:33Z",
        extra={
            "labels": ["feature/funnels", "team/product-analytics"],
            "url": "https://github.com/PostHog/posthog/issues/42995",
        },
    ),
    SignalData(
        signal_id="test-funnel-percentiles-42996",
        content=(
            "Feature request: Median and percentile options for funnel Time to Convert. "
            "The Time to Convert view only shows average conversion time as a summary stat. "
            "Averages can be skewed by outliers, making median or percentiles (P50, P90, P99) more "
            "useful for understanding typical user behavior. Request to add aggregation options "
            "alongside or instead of average. From Zendesk support ticket."
        ),
        source_product="github_issues",
        source_type="enhancement",
        source_id="42996",
        weight=0.5,
        timestamp="2025-12-09T00:58:16Z",
        extra={
            "labels": ["feature/funnels", "team/product-analytics"],
            "url": "https://github.com/PostHog/posthog/issues/42996",
        },
    ),
]

TEST_TITLE = "Funnel insights lack time-based comparison and statistical options"
TEST_SUMMARY = (
    "Multiple users are requesting enhanced funnel analytics capabilities. "
    "Key gaps include: (1) no ability to compare conversion rates across arbitrary time periods, "
    "(2) dynamic bin widths in Time to Convert histograms make trend tracking unreliable, and "
    "(3) only average conversion time is available — median and percentile options (P50, P90, P99) "
    "are missing. All three requests come from the product-analytics/funnels area and have "
    "Zendesk support ticket backing."
)


def _build_sandbox_prompt(title: str, summary: str, signals: list[SignalData]) -> str:
    signals_text = render_signals_to_text(signals)
    return f"""{ACTIONABILITY_JUDGE_SYSTEM_PROMPT}

---

REPORT TO ASSESS:

Title: {title}
Summary: {summary}

UNDERLYING SIGNALS:

<signal_data>
{signals_text}
</signal_data>"""


test_prompt = """
## Task
- Tell me how many signups I had in the last 30 days and what's the insight to track that.
- Check PostHog MCP to get the data.
- Check the codebase to find the endpoint/function that tracks that data.

Respond with a JSON object:
<jsonschema>
{json_schema}
</jsonschema>
"""


class TestModel(BaseModel):
    number_of_signups: int = Field(description="Number of signups I got")
    insight_name: str = Field(
        description="The name of Posthog insight or dashboard that displays the number of signups"
    )
    code_path: str = Field(description="Path to the endpoint/function that captures the signups")


# test_prompt = """
# Tell me a joke about monkeys.

# Respond with a JSON object:
# - "answer": The answer to the question I asked.
# """


# class TestModel(BaseModel):
#     answer: str


class Command(BaseCommand):
    help = "Test the actionability judge via sandbox agent against simulated funnel enhancement signals."

    def handle(self, *args, **options):
        json_schema = json.dumps(TestModel.model_json_schema(), indent=2)
        prompt = test_prompt.format(json_schema=json_schema)
        # self.stdout.write(f"Report title: {TEST_TITLE}")
        # self.stdout.write(f"Signals: {len(TEST_SIGNALS)}")
        # self.stdout.write("")

        result = asyncio.run(
            run_sandbox_agent_get_structured_output(
                prompt=prompt,
                branch="master",
                model_to_validate=TestModel,
                step_name="analyze_report_actionability",
            )
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Result ==="))
        self.stdout.write(f"{result.model_dump_json()}")
