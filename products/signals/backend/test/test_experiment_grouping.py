"""
Test script: would 10 experiment-finished signals be grouped into one report or stay separate?

Calls the real LLM matching logic with synthetic experiment signals.
Simulates sequential pipeline processing: each signal sees all previously
emitted signals as search candidates, just like the real workflow.

Requires ANTHROPIC_API_KEY in the environment (or Django settings).

Usage:
    ANTHROPIC_API_KEY=sk-... pytest products/signals/backend/test/test_experiment_grouping.py -s
"""

import uuid
from dataclasses import dataclass, field

import pytest

from products.signals.backend.temporal.grouping import match_signal_to_report
from products.signals.backend.temporal.types import ExistingReportMatch, NewReportMatch, ReportContext, SignalCandidate

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

UNRELATED_EXPERIMENTS = [
    {
        "source_id": "exp-001",
        "description": (
            "Experiment 'Blue CTA button on pricing page' finished. "
            "Variant B (blue button) won with 97% significance. "
            "Conversion rate: control 3.2%, variant 4.8% (+50%). "
            "1,245 users in each arm over 14 days."
        ),
    },
    {
        "source_id": "exp-002",
        "description": (
            "Experiment 'Onboarding tooltip sequence' finished. "
            "Variant A (3-step tooltips) won with 95% significance. "
            "Activation rate: control 41%, variant 52% (+27%). "
            "3,100 new users over 21 days."
        ),
    },
    {
        "source_id": "exp-003",
        "description": (
            "Experiment 'Checkout page single-step vs multi-step' finished. "
            "No significant winner after 28 days. "
            "Completion rate: control 68%, variant 69% (+1.5%). "
            "p-value 0.42, 8,500 users per arm."
        ),
    },
    {
        "source_id": "exp-004",
        "description": (
            "Experiment 'Dark mode default for new users' finished. "
            "Variant (dark mode) lost with 93% significance. "
            "7-day retention: control 34%, variant 29% (-15%). "
            "2,000 users per arm over 14 days."
        ),
    },
    {
        "source_id": "exp-005",
        "description": (
            "Experiment 'AI-generated dashboard descriptions' finished. "
            "Variant won with 99% significance. "
            "Dashboard creation rate: control 12%, variant 19% (+58%). "
            "5,000 users over 7 days."
        ),
    },
    {
        "source_id": "exp-006",
        "description": (
            "Experiment 'Weekly digest email frequency' finished. "
            "Bi-weekly variant won with 96% significance. "
            "Email open rate: weekly 18%, bi-weekly 31% (+72%). "
            "10,000 users over 42 days."
        ),
    },
    {
        "source_id": "exp-007",
        "description": (
            "Experiment 'Search bar placement in top nav' finished. "
            "Variant (center placement) won with 91% significance. "
            "Search usage: control 8%, variant 14% (+75%). "
            "15,000 users over 14 days."
        ),
    },
    {
        "source_id": "exp-008",
        "description": (
            "Experiment 'Simplified permissions UI' finished. "
            "Variant won with 98% significance. "
            "Permission setup completion: control 45%, variant 72% (+60%). "
            "800 team admins over 30 days."
        ),
    },
    {
        "source_id": "exp-009",
        "description": (
            "Experiment 'In-app survey after first insight' finished. "
            "No significant winner. NPS response rate: control 5%, variant 7%. "
            "p-value 0.18, 4,000 users over 21 days."
        ),
    },
    {
        "source_id": "exp-010",
        "description": (
            "Experiment 'Funnel visualization redesign' finished. "
            "Variant (horizontal funnel) won with 94% significance. "
            "Time to first funnel insight: control 4.2min, variant 2.8min (-33%). "
            "1,800 users over 14 days."
        ),
    },
]

SAME_EXPERIMENT_SIGNALS = [
    {
        "source_id": "exp-001",
        "description": (
            "Experiment 'Blue CTA button on pricing page' finished. "
            "Variant B (blue button) won with 97% significance. "
            "Conversion rate: control 3.2%, variant 4.8% (+50%). "
            "1,245 users in each arm over 14 days."
        ),
    },
    {
        "source_id": "exp-001",
        "description": (
            "Follow-up analysis for experiment 'Blue CTA button on pricing page'. "
            "Revenue impact: variant B generated $12,400 more in monthly revenue. "
            "Effect strongest for users on Pro plan (+62% conversion)."
        ),
    },
    {
        "source_id": "exp-001",
        "description": (
            "Experiment 'Blue CTA button on pricing page' reached significance early "
            "at day 10 of 14. Sequential testing boundary crossed. "
            "Recommend stopping experiment and shipping variant B."
        ),
    },
]


# ---------------------------------------------------------------------------
# In-memory state that accumulates as signals are processed sequentially
# ---------------------------------------------------------------------------


@dataclass
class EmittedSignal:
    signal_id: str
    report_id: str
    description: str
    source_id: str


@dataclass
class ReportState:
    report_id: str
    title: str
    signal_count: int = 1


@dataclass
class PipelineState:
    """Simulates the accumulated ClickHouse + Postgres state after each signal."""

    signals: list[EmittedSignal] = field(default_factory=list)
    reports: dict[str, ReportState] = field(default_factory=dict)

    def get_candidates(self) -> list[SignalCandidate]:
        """All previously emitted signals, as the semantic search would return them."""
        return [
            SignalCandidate(
                signal_id=s.signal_id,
                report_id=s.report_id,
                content=s.description,
                source_product="experiments",
                source_type="experiment_finished",
                # Real distances vary; use a low distance so the LLM always sees them.
                # The matching decision is based on content, not distance threshold.
                distance=0.15,
            )
            for s in self.signals
        ]

    def get_report_contexts(self) -> dict[str, ReportContext]:
        return {
            rid: ReportContext(report_id=rid, title=r.title, signal_count=r.signal_count)
            for rid, r in self.reports.items()
        }

    def apply_result(
        self,
        result: ExistingReportMatch | NewReportMatch,
        description: str,
        source_id: str,
    ) -> str:
        """Apply the match result to the state, return the report_id."""
        signal_id = str(uuid.uuid4())

        if isinstance(result, ExistingReportMatch):
            report_id = result.report_id
            self.reports[report_id].signal_count += 1
        else:
            report_id = str(uuid.uuid4())
            self.reports[report_id] = ReportState(
                report_id=report_id,
                title=result.title,
            )

        self.signals.append(
            EmittedSignal(
                signal_id=signal_id,
                report_id=report_id,
                description=description,
                source_id=source_id,
            )
        )
        return report_id


async def _process_signal_sequentially(
    state: PipelineState,
    description: str,
    source_id: str,
) -> tuple[str, ExistingReportMatch | NewReportMatch]:
    """
    Process one signal against the current pipeline state.
    Returns (report_id, match_result).
    """
    candidates = state.get_candidates()

    if not candidates:
        # First signal: no candidates, always creates a new report.
        # Skip the LLM call — the real pipeline also creates a new report
        # when semantic search returns no results.
        result = NewReportMatch(
            title=description.split(".")[0],
            summary=description,
            match_metadata=type("FakeNoMatch", (), {"reason": "first signal, no candidates"})(),  # type: ignore[arg-type]
        )
    else:
        queries = [f"experiment results {source_id}"]
        query_results = [candidates]
        report_contexts = state.get_report_contexts()

        result = await match_signal_to_report(
            description=description,
            source_product="experiments",
            source_type="experiment_finished",
            queries=queries,
            query_results=query_results,
            report_contexts=report_contexts,
        )

    report_id = state.apply_result(result, description, source_id)
    return report_id, result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExperimentSignalGrouping:
    """
    Integration tests that call the real LLM to verify grouping behavior.
    Signals are processed sequentially, accumulating state like the real pipeline.

    Run with: pytest products/signals/backend/test/test_experiment_grouping.py -s
    """

    async def test_unrelated_experiments_stay_separate(self):
        """10 unrelated experiments processed sequentially should produce 10 distinct reports."""
        state = PipelineState()
        report_ids: list[str] = []

        for i, exp in enumerate(UNRELATED_EXPERIMENTS):
            report_id, result = await _process_signal_sequentially(state, exp["description"], exp["source_id"])
            report_ids.append(report_id)

            matched = isinstance(result, ExistingReportMatch)
            reason = result.match_metadata.reason if hasattr(result.match_metadata, "reason") else "n/a"
            print(  # noqa: T201
                f"\n  Signal {i + 1} ({exp['source_id']}): "
                f"{'GROUPED into' if matched else 'NEW report'} {report_id[:8]}... "
                f"reason={reason}"
            )

        unique_reports = set(report_ids)
        print(f"\n  Total reports: {len(unique_reports)} (expected 10)")  # noqa: T201
        print(f"  Report distribution: {dict(state.reports)}")  # noqa: T201

        assert len(unique_reports) == len(UNRELATED_EXPERIMENTS), (
            f"Expected {len(UNRELATED_EXPERIMENTS)} distinct reports for unrelated experiments, "
            f"got {len(unique_reports)}. Some unrelated experiments were incorrectly grouped."
        )

    async def test_same_experiment_signals_group_together(self):
        """3 signals about the same experiment should converge into 1 report."""
        state = PipelineState()
        report_ids: list[str] = []

        for i, sig in enumerate(SAME_EXPERIMENT_SIGNALS):
            report_id, result = await _process_signal_sequentially(state, sig["description"], sig["source_id"])
            report_ids.append(report_id)

            matched = isinstance(result, ExistingReportMatch)
            reason = result.match_metadata.reason if hasattr(result.match_metadata, "reason") else "n/a"
            print(  # noqa: T201
                f"\n  Signal {i + 1}: {'GROUPED into' if matched else 'NEW report'} {report_id[:8]}... reason={reason}"
            )

        unique_reports = set(report_ids)
        print(f"\n  Total reports: {len(unique_reports)} (expected 1)")  # noqa: T201

        assert len(unique_reports) == 1, (
            f"Expected 1 report for same-experiment signals, got {len(unique_reports)}. "
            f"Signals about the same experiment were incorrectly split apart."
        )
