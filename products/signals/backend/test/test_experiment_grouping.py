"""
Test script: would 10 experiment-finished signals be grouped into one report or stay separate?

Calls the real LLM matching logic with synthetic experiment signals.
Requires ANTHROPIC_API_KEY in the environment (or Django settings).

Usage:
    ANTHROPIC_API_KEY=sk-... pytest products/signals/backend/test/test_experiment_grouping.py -s
"""

import uuid

import pytest

from products.signals.backend.temporal.grouping import match_signal_to_report
from products.signals.backend.temporal.types import ExistingReportMatch, ReportContext, SignalCandidate

# ---------------------------------------------------------------------------
# Fixture data: 10 unrelated experiments
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

# Signals about the SAME experiment (should be grouped together)
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


def _make_candidate(description: str, report_id: str, source_id: str, distance: float = 0.15) -> SignalCandidate:
    return SignalCandidate(
        signal_id=str(uuid.uuid4()),
        report_id=report_id,
        content=description,
        source_product="experiments",
        source_type="experiment_finished",
        distance=distance,
    )


async def _test_pairwise_grouping(
    existing_description: str,
    existing_source_id: str,
    new_description: str,
    new_source_id: str,
    report_title: str,
) -> tuple[bool, str]:
    """
    Simulate: one signal already exists in a report. Would the new signal join it?
    Returns (matched: bool, reason: str).
    """
    report_id = str(uuid.uuid4())
    candidate = _make_candidate(existing_description, report_id, existing_source_id)

    queries = [f"experiment finished {new_source_id}"]
    query_results = [[candidate]]
    report_contexts = {
        report_id: ReportContext(report_id=report_id, title=report_title, signal_count=1),
    }

    result = await match_signal_to_report(
        description=new_description,
        source_product="experiments",
        source_type="experiment_finished",
        queries=queries,
        query_results=query_results,
        report_contexts=report_contexts,
    )

    if isinstance(result, ExistingReportMatch):
        return True, result.match_metadata.reason
    else:
        return False, result.match_metadata.reason


@pytest.mark.asyncio
class TestExperimentSignalGrouping:
    """
    Integration tests that call the real LLM to verify grouping behavior.
    Run with: pytest products/signals/backend/test/test_experiment_grouping.py -s
    """

    @pytest.mark.parametrize(
        "i,j",
        # Test a sample of pairs, not all 45 combinations (save API calls)
        [(0, 1), (0, 4), (2, 7), (3, 9), (5, 8)],
        ids=lambda pair: f"exp-{pair + 1}" if isinstance(pair, int) else None,
    )
    async def test_unrelated_experiments_stay_separate(self, i, j):
        exp_a = UNRELATED_EXPERIMENTS[i]
        exp_b = UNRELATED_EXPERIMENTS[j]

        matched, reason = await _test_pairwise_grouping(
            existing_description=exp_a["description"],
            existing_source_id=exp_a["source_id"],
            new_description=exp_b["description"],
            new_source_id=exp_b["source_id"],
            report_title=f"Experiment {exp_a['source_id']} results",
        )

        print(f"\n[{exp_a['source_id']} vs {exp_b['source_id']}] matched={matched}, reason={reason}")  # noqa: T201
        assert not matched, (
            f"Expected unrelated experiments {exp_a['source_id']} and {exp_b['source_id']} "
            f"to stay separate, but they were grouped. Reason: {reason}"
        )

    @pytest.mark.parametrize(
        "new_idx",
        [1, 2],
        ids=["follow-up-analysis", "early-significance"],
    )
    async def test_same_experiment_signals_group_together(self, new_idx):
        existing = SAME_EXPERIMENT_SIGNALS[0]
        new = SAME_EXPERIMENT_SIGNALS[new_idx]

        matched, reason = await _test_pairwise_grouping(
            existing_description=existing["description"],
            existing_source_id=existing["source_id"],
            new_description=new["description"],
            new_source_id=new["source_id"],
            report_title="Experiment 'Blue CTA button on pricing page' results",
        )

        print(f"\n[same experiment, signal {new_idx}] matched={matched}, reason={reason}")  # noqa: T201
        assert matched, (
            f"Expected same-experiment signals to group together, but they were kept separate. Reason: {reason}"
        )
