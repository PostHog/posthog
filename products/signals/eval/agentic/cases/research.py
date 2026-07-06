"""Research eval dataset.

Each case feeds synthetic signals through the real ``run_multi_turn_research`` and grades
the findings, assessments, and summary. Ground truth uses substring matching so it stays
robust to incidental formatting while still asserting the agent reached the right code and
the right verdict.
"""

from __future__ import annotations

from products.signals.eval.agentic.datasets import ResearchCase, ResearchExpectation, SignalSpec
from products.signals.eval.agentic.scorers_judge import ResearchSummaryJudge
from products.signals.eval.agentic.scorers_research import default_research_scorers

CASES: list[ResearchCase] = [
    ResearchCase(
        case_id="research_funnel_tz",
        step="research",
        repo="posthog/posthog",
        cassette="research_funnel_tz.json",
        notes="Single funnel-timezone bug signal; strong actionable P1 outcome.",
        signals=(
            SignalSpec(
                signal_id="sig_funnel_tz",
                content=(
                    "The 'Signup conversion' funnel shows 0% conversion for the last 7 days. It started "
                    "right after the 2026 DST change. Users report the funnel breaks across the timezone shift."
                ),
                source_product="error_tracking",
                source_type="issue_spiking",
                source_id="issue_funnel_tz",
                weight=0.9,
            ),
        ),
        expected=ResearchExpectation(
            # Subjective judgments on a synthetic signal have an acceptable range, not one right
            # answer — a live agent that finds the funnel code but no corroborating data may land on
            # either verdict. Accept the defensible set; the deterministic dims below stay exact.
            expected_actionability=("immediately_actionable", "requires_human_input"),
            expected_priority=("P1", "P2", "P3"),
            expected_already_addressed=False,
            # This is a synthetic signal with no matching data in the project, so a live agent
            # honestly reports verified=False (it can't confirm a fabricated metric claim).
            # Asserting verification here would be a wrong expectation; verification is still
            # graded by research_flag_cleanup_multi (replay). Left unset so live + replay agree.
            expect_verified=None,
            expected_code_path_substrings={"sig_funnel_tz": ("funnel",)},
            summary_must_mention=("funnel", "timezone"),
            min_commit_hashes=2,
        ),
        scorers=(*default_research_scorers(), ResearchSummaryJudge()),
    ),
    ResearchCase(
        case_id="research_flag_cleanup_multi",
        step="research",
        repo="posthog/posthog",
        cassette="research_flag_cleanup_multi.json",
        notes="Two related signals about a stale feature flag; exercises the multi-signal follow-up path.",
        signals=(
            SignalSpec(
                signal_id="sig_flag_1",
                content="The 'new-onboarding-flow' feature flag has been at 100% rollout for 90 days but the code still branches on it.",
                source_product="error_tracking",
                source_type="issue_created",
                source_id="issue_flag_1",
                weight=0.6,
            ),
            SignalSpec(
                signal_id="sig_flag_2",
                content="Dead code path behind 'new-onboarding-flow' off-branch is never executed in production for 3 months.",
                source_product="error_tracking",
                source_type="issue_created",
                source_id="issue_flag_2",
                weight=0.5,
            ),
        ),
        expected=ResearchExpectation(
            expected_actionability="immediately_actionable",
            expected_priority="P3",
            expected_already_addressed=False,
            expect_verified=True,
            expected_code_path_substrings={
                "sig_flag_1": ("onboarding",),
                "sig_flag_2": ("onboarding",),
            },
            summary_must_mention=("flag", "onboarding"),
            min_commit_hashes=1,
        ),
        scorers=(*default_research_scorers(), ResearchSummaryJudge()),
    ),
]
