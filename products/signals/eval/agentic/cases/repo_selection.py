"""Repository-selection eval dataset.

Each case gives the agent a rendered request and a candidate list (drawn from the OSS
repo registry) and grades whether it picks the repo a developer would change — or
correctly declines when no candidate is the subject.
"""

from __future__ import annotations

from products.signals.eval.agentic.datasets import RepoSelectionCase, RepoSelectionExpectation, SignalSpec
from products.signals.eval.agentic.repos import candidate_full_names
from products.signals.eval.agentic.scorers_repo_selection import default_repo_selection_scorers

_BROAD_POOL = ["cal", "supabase", "n8n", "excalidraw", "posthog-js"]

CASES: list[RepoSelectionCase] = [
    RepoSelectionCase(
        case_id="reposel_cal_booking",
        step="repo_selection",
        cassette="reposel_cal_booking.json",
        notes="Clear single-domain match to the scheduling app.",
        signals=(
            SignalSpec(
                signal_id="sig_cal",
                content=(
                    "Round-robin booking links assign the wrong host when two team members share availability; "
                    "the booking page shows a double-booked slot."
                ),
            ),
        ),
        candidate_repos=tuple(candidate_full_names(_BROAD_POOL)),
        expected=RepoSelectionExpectation(expected_repository="calcom/cal.com"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_python_sdk",
        step="repo_selection",
        cassette="reposel_python_sdk.json",
        notes="Same-product (SDK) disambiguation: Python vs JS.",
        signals=(
            SignalSpec(
                signal_id="sig_pysdk",
                content=(
                    "ImportError: cannot import name 'feature_flags' — traceback is all .py frames ending in "
                    "posthog/feature_flags.py when calling get_feature_flag from a Django app."
                ),
            ),
        ),
        candidate_repos=tuple(candidate_full_names(["posthog-js", "posthog-python", "cal"])),
        expected=RepoSelectionExpectation(expected_repository="posthog/posthog-python"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_billing_null",
        step="repo_selection",
        cassette="reposel_billing_null.json",
        notes="No candidate owns the domain — correct answer is null.",
        context=(
            "Customer disputes an invoice and is unhappy with the refund SLA. They want the charge reversed "
            "and the dispute escalated to an account manager."
        ),
        candidate_repos=tuple(candidate_full_names(_BROAD_POOL)),
        expected=RepoSelectionExpectation(expect_null=True),
        scorers=default_repo_selection_scorers(),
    ),
]
