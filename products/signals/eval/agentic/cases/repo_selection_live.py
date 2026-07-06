"""Live repository-selection cases.

In live mode the candidate list comes from the team's actual GitHub integration (not the
case), and the agent queries the real repository cache via ``execute-sql``. These cases use
unambiguous, recognizable repositories from that integration so the expected pick is clear.
Swap the expected full names if your local integration differs (list eligible repos with
``Integration.repository_cache_entries``).
"""

from __future__ import annotations

from products.signals.eval.agentic.datasets import RepoSelectionCase, RepoSelectionExpectation, SignalSpec
from products.signals.eval.agentic.scorers_repo_selection import default_repo_selection_scorers

CASES: list[RepoSelectionCase] = [
    RepoSelectionCase(
        case_id="reposel_live_feedback_board",
        step="repo_selection",
        notes="Product-feedback board → fider (open platform to collect/prioritize feedback).",
        signals=(
            SignalSpec(
                signal_id="sig_fider",
                content=(
                    "On our public feature-request board, customers submit ideas and upvote them, but the "
                    "upvote count double-counts when a user votes, navigates away, and returns."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/fider"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_siwe_starter",
        step="repo_selection",
        notes="Sign-In With Ethereum on the Next.js starter → next-ethereum.",
        signals=(
            SignalSpec(
                signal_id="sig_siwe",
                content=(
                    "The Sign-In With Ethereum flow in our Next.js starter throws 'nonce mismatch' on wallet "
                    "connect after upgrading the wallet library."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/next-ethereum"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_support_inbox",
        step="repo_selection",
        notes="Open-source customer support inbox (Intercom alternative) → chatwoot.",
        signals=(
            SignalSpec(
                signal_id="sig_chatwoot",
                content=(
                    "Our self-hosted open-source customer support inbox (the Intercom/Zendesk alternative) drops "
                    "incoming conversations when an agent is assigned during a reply."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/chatwoot"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_timenavi_webapp",
        step="repo_selection",
        notes="Named product (TimeNavi) — two TimeNavi repos exist (webapp + schedule), both defensible.",
        signals=(
            SignalSpec(
                signal_id="sig_timenavi",
                content=(
                    "In the TimeNavi web app, the calendar view fails to render recurring events after a "
                    "Google Calendar sync; the React component throws on the recurrence rule."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(
            expected_repository=("joshsny/webapp", "joshsny/timenavi-schedule"),
        ),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_billing_null",
        step="repo_selection",
        notes="Pure billing/refund ops request — no candidate repo owns it; correct answer is null.",
        context=(
            "A customer disputes last month's invoice and wants a prorated refund plus the dispute escalated "
            "to their account manager. They are not reporting any product bug."
        ),
        candidate_repos=(),
        expected=RepoSelectionExpectation(expect_null=True),
        scorers=default_repo_selection_scorers(),
    ),
]
