import asyncio
import logging

from django.core.management.base import BaseCommand

from products.signals.backend.report_generation.executor import run_sandbox_agent_get_structured_output
from products.signals.backend.report_generation.research import ReportResearchOutput, build_research_prompt
from products.signals.backend.temporal.types import SignalData

logger = logging.getLogger(__name__)

# Simulated signals from 3 related GitHub issues about funnel enhancements
TEST_SIGNALS = [
    SignalData(
        signal_id="test-funnel-compare-42606",
        content=(
            "Feature request: Compare against previous option for funnel insights. "
            "Customer would be able to select two arbitrary intervals (week, month etc) and compare "
            "the % change in conversion between those two periods. Current workaround is HogQL "
            "breakdown like toString(toISOWeek(timestamp)). "
            "Check how many users are currently using the funnel insight type to gauge demand."
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
            "width option (e.g., '1 minute per bin'). From Zendesk support ticket. "
            "There may be existing insights or dashboards tracking funnel conversion times worth checking."
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
            "alongside or instead of average. From Zendesk support ticket. "
            "Check if there's a feature flag gating any funnel stats improvements already in progress."
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

# # TODO: Remove after tests
# simple_test_prompt = 'Return how many signups I got in the last 30 days. Return in JSON format: `{"answer": N}`'


# class SimpleTestModel(BaseModel):
#     answer: str


class Command(BaseCommand):
    help = "Test the report research agent via sandbox against simulated funnel enhancement signals."

    def _flushing_write(self, msg: str) -> None:
        self.stdout.write(msg)
        self.stdout.flush()

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Stream full raw S3 log lines instead of only agent messages",
        )

    def handle(self, *args, **options):
        verbose = options["verbose"]
        prompt = build_research_prompt(
            title=TEST_TITLE,
            summary=TEST_SUMMARY,
            signals=TEST_SIGNALS,
        )

        self.stdout.write(f"Report title: {TEST_TITLE}")
        self.stdout.write(f"Signals: {len(TEST_SIGNALS)}")
        self.stdout.write("")

        result = asyncio.run(
            run_sandbox_agent_get_structured_output(
                # prompt=simple_test_prompt,
                prompt=prompt,
                branch="master",
                # model_to_validate=SimpleTestModel,
                model_to_validate=ReportResearchOutput,
                step_name="report_research",
                verbose=verbose,
                output_fn=self._flushing_write,
            )
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Research Result ==="))
        self.stdout.write(f"Actionability: {result.actionability}")
        self.stdout.write(f"Priority: {result.priority}")
        self.stdout.write(f"Already addressed: {result.already_addressed}")
        self.stdout.write(f"Explanation: {result.explanation}")
        self.stdout.write("")
        for finding in result.findings:
            self.stdout.write(self.style.WARNING(f"--- Signal: {finding.signal_id} ---"))
            self.stdout.write(f"  Verified: {finding.verified}")
            self.stdout.write(f"  Code paths: {finding.relevant_code_paths}")
            self.stdout.write(f"  Data: {finding.data_queried}")
            self.stdout.write("")
