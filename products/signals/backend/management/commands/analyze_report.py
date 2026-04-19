"""Local dev tool for manually testing the agentic signals report flow. DEBUG only.

Exercises the research and update flows against synthetic inputs and saved fixtures.
Intended to be reworked into an eval harness — keeping it now preserves coverage of
the multi-turn research path while the eval infrastructure is built.
"""

import json
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.signals.backend.report_generation.research import ReportResearchOutput, run_multi_turn_research
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.services.dev_sandbox_context import resolve_sandbox_context_for_local_dev

logger = logging.getLogger(__name__)

DEFAULT_REPOSITORY = "posthog/posthog"
DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "report_generation"
    / "fixtures"
    / "analyze_report_funnel_research_output.json"
)
SYNTHETIC_REPORT_ID = "test-funnel-report-001"

# Simulated signals from related GitHub issues about funnel enhancements.
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
        timestamp=datetime(2025, 12, 3, 16, 21, 28, tzinfo=UTC),
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
        timestamp=datetime(2025, 12, 9, 0, 56, 33, tzinfo=UTC),
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
        timestamp=datetime(2025, 12, 9, 0, 58, 16, tzinfo=UTC),
        extra={
            "labels": ["feature/funnels", "team/product-analytics"],
            "url": "https://github.com/PostHog/posthog/issues/42996",
        },
    ),
    SignalData(
        signal_id="test-funnel-drop-off-43201",
        content=(
            "Bug report: Customer reports that their onboarding funnel conversion rate dropped "
            "significantly in the last two weeks but they haven't shipped any product changes. "
            "The funnel goes: page view on /signup -> custom event 'user_signed_up' -> "
            "custom event 'onboarding_completed'. They suspect a tracking regression - possibly "
            "the 'onboarding_completed' event stopped firing or its volume dropped. "
            "Needs investigation of actual event volumes in the events table to confirm or deny."
        ),
        source_product="zendesk",
        source_type="bug",
        source_id="44891",
        weight=0.8,
        timestamp=datetime(2025, 12, 11, 14, 32, 7, tzinfo=UTC),
        extra={
            "labels": ["feature/funnels", "team/product-analytics"],
        },
    ),
]

UPDATE_SIGNAL = SignalData(
    signal_id="test-funnel-time-to-convert-reporting-43310",
    content=(
        "Feature request: Another customer wants funnel Time to Convert reports to be stable across recurring "
        "weekly reviews. They asked for percentile summaries like P50 and P95 plus fixed histogram bucket sizes "
        "when comparing onboarding funnel performance month over month. Right now the average-only summary and "
        "shifting histogram bins make the report hard to trust for trend analysis."
    ),
    source_product="github_issues",
    source_type="enhancement",
    source_id="43310",
    weight=0.6,
    timestamp=datetime(2025, 12, 13, 9, 41, 5, tzinfo=UTC),
    extra={
        "labels": ["feature/funnels", "team/product-analytics"],
        "url": "https://github.com/PostHog/posthog/issues/43310",
    },
)


def load_previous_report_fixture() -> tuple[str, ReportResearchOutput]:
    path = DEFAULT_FIXTURE_PATH
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise CommandError(f"Fixture not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"Fixture is not valid JSON: {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise CommandError(f"Fixture root must be a JSON object: {path}")

    result_payload = payload.get("result")
    if result_payload is None:
        raise CommandError(f"Fixture missing 'result': {path}")

    try:
        previous_report_research = ReportResearchOutput.model_validate(result_payload)
    except Exception as exc:
        raise CommandError(f"Fixture result is not a valid ReportResearchOutput: {path}: {exc}") from exc

    report_id = payload.get("report_id")
    if not isinstance(report_id, str) or not report_id:
        report_id = SYNTHETIC_REPORT_ID

    return report_id, previous_report_research


class Command(BaseCommand):
    help = "Local dev tool: test the agentic report research/update flow. DEBUG only. Will be reworked into evals."

    def _flushing_write(self, msg: str) -> None:
        self.stdout.write(msg)
        self.stdout.flush()

    def add_arguments(self, parser):
        parser.add_argument(
            "mode",
            choices=["research", "update"],
            help="Run a fresh research pass or update an existing researched report.",
        )
        parser.add_argument(
            "--repository",
            type=str,
            default=DEFAULT_REPOSITORY,
            help=f"GitHub repository in org/repo format (default: {DEFAULT_REPOSITORY})",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Stream full raw S3 log lines instead of only agent messages",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        mode = options["mode"]
        verbose = options["verbose"]
        repository = options["repository"]

        title: str | None = None
        summary: str | None = None
        signals = list(TEST_SIGNALS)
        previous_report_id: str | None = None
        previous_report_research: ReportResearchOutput | None = None

        if mode == "update":
            previous_report_id, previous_report_research = load_previous_report_fixture()
            title = previous_report_research.title
            summary = previous_report_research.summary
            signals.append(UPDATE_SIGNAL)
            self.stdout.write(f"Loaded previous research fixture: {DEFAULT_FIXTURE_PATH}")
            self.stdout.write(f"Previous report ID: {previous_report_id}")
            self.stdout.write(f"Previous title: {previous_report_research.title}")
            self.stdout.write("")

        try:
            context = resolve_sandbox_context_for_local_dev(repository)
        except RuntimeError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return

        self.stdout.write(f"Mode: {mode}")
        self.stdout.write(f"Signals: {len(signals)}")
        self.stdout.write("")

        result = asyncio.run(
            run_multi_turn_research(
                signals,
                context,
                title=title,
                summary=summary,
                previous_report_id=previous_report_id,
                previous_report_research=previous_report_research,
                branch="master",
                verbose=verbose,
                output_fn=self._flushing_write,
            )
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Research Result ==="))
        self.stdout.write(f"Title: {result.title}")
        self.stdout.write(f"Summary: {result.summary}")
        self.stdout.write(f"Actionability: {result.actionability.actionability}")
        self.stdout.write(f"Already addressed: {result.actionability.already_addressed}")
        self.stdout.write(f"Actionability explanation: {result.actionability.explanation}")
        if result.priority:
            self.stdout.write(f"Priority: {result.priority.priority}")
            self.stdout.write(f"Priority explanation: {result.priority.explanation}")
        else:
            self.stdout.write("Priority: N/A (not actionable)")
        self.stdout.write("")
        for finding in result.findings:
            self.stdout.write(self.style.WARNING(f"--- Signal: {finding.signal_id} ---"))
            self.stdout.write(f"  Verified: {finding.verified}")
            self.stdout.write(f"  Code paths: {finding.relevant_code_paths}")
            self.stdout.write(f"  Data: {finding.data_queried}")
            self.stdout.write("")
