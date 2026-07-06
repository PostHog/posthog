"""Live research cases — broad coverage across signal sources, verdicts, and evidence types.

Two flavours:

- **Data-grounded**: the signal references data that actually exists in the eval project
  (hedgebox: error-tracking issues, file-download events, experiments). These set
  ``expect_data_evidence=True`` so the agent must actually query the project via the PostHog MCP,
  and they run against a small, fast-cloning repo since the verdict rests on data, not this repo's
  code.
- **Code-grounded**: the signal maps to real code in `posthog/posthog` (e.g. the funnel case), so
  code paths and commit attribution are asserted.

Subjective judgments (actionability/priority) use acceptable-range ground truth — a live agent can
reasonably land on more than one verdict — while deterministic dimensions stay exact. Sources are
varied (error_tracking, session_replay, github, linear, zendesk, conversations) to mirror the real
inbox. Run: ``python manage.py run_agentic_eval --step research --mode live`` (add ``--case <id>``).
"""

from __future__ import annotations

from products.signals.eval.agentic.cases.research import CASES as _ALL_RESEARCH_CASES
from products.signals.eval.agentic.datasets import ResearchCase, ResearchExpectation, SignalSpec
from products.signals.eval.agentic.scorers_judge import ResearchSummaryJudge
from products.signals.eval.agentic.scorers_research import default_research_scorers

# Repo the agent gets on disk. Data-grounded cases use a small repo (fast clone) since the verdict
# rests on project data, not this repo's code; code-grounded cases use the monorepo.
_FAST_REPO = "posthog/posthog-python"
_CODE_REPO = "posthog/posthog"

_funnel_case = next(c for c in _ALL_RESEARCH_CASES if c.case_id == "research_funnel_tz")

CASES: list[ResearchCase] = [
    # ── Code-grounded ────────────────────────────────────────────────────────────
    _funnel_case,
    # ── Data-grounded (real hedgebox data; agent must query the project) ──────────
    ResearchCase(
        case_id="research_live_checkout_timeout",
        step="research",
        repo=_FAST_REPO,
        notes="error_tracking signal tied to the real 'Checkout API timeout' issue — agent must query errors.",
        signals=(
            SignalSpec(
                signal_id="sig_checkout",
                content=(
                    "Error tracking shows a 'Checkout API timeout' issue. Customers report the checkout/upgrade "
                    "flow hanging and timing out. Investigate the impact and whether it's worth acting on."
                ),
                source_product="error_tracking",
                source_type="issue_spiking",
                source_id="checkout_timeout",
                weight=0.9,
            ),
        ),
        # Data-grounded cases assert what they actually test: the agent found and analyzed the
        # relevant project data, and summarized it. The actionability/priority verdict depends on the
        # data's magnitude (which varies in demo data), so verdict calibration is left to the
        # verdict-variety cases below — asserting a fixed verdict here would test data volume, not the agent.
        expected=ResearchExpectation(
            expect_data_evidence=True,
            summary_must_mention=("checkout",),
        ),
        scorers=(*default_research_scorers(), ResearchSummaryJudge()),
    ),
    ResearchCase(
        case_id="research_live_download_engagement",
        step="research",
        repo=_FAST_REPO,
        notes="session_replay/engagement signal grounded in real downloaded_file event volume.",
        signals=(
            SignalSpec(
                signal_id="sig_downloads",
                content=(
                    "Session replays suggest users struggle to find the download button, and we suspect file "
                    "download engagement is lower than it should be. Check the downloaded_file event trend and "
                    "whether there's a real drop worth acting on."
                ),
                source_product="session_replay",
                source_type="replay_vision",
                source_id="download_engagement",
                weight=0.6,
            ),
        ),
        expected=ResearchExpectation(
            expect_data_evidence=True,
            summary_must_mention=("download",),
        ),
        scorers=(*default_research_scorers(), ResearchSummaryJudge()),
    ),
    ResearchCase(
        case_id="research_live_pricing_experiment",
        step="research",
        repo=_FAST_REPO,
        notes="github signal about the real 'Pricing page redesign' experiment — agent must read experiment data.",
        signals=(
            SignalSpec(
                signal_id="sig_pricing_exp",
                content=(
                    "A teammate flagged that the 'Pricing page redesign' experiment may be inconclusive or "
                    "negative. Look at the experiment results and recommend whether to ship, iterate, or roll back."
                ),
                source_product="github",
                source_type="issue_created",
                source_id="pricing_experiment",
                weight=0.5,
            ),
        ),
        expected=ResearchExpectation(
            expect_data_evidence=True,
            summary_must_mention=("pricing",),
        ),
        scorers=(*default_research_scorers(), ResearchSummaryJudge()),
    ),
    # ── Verdict variety ──────────────────────────────────────────────────────────
    ResearchCase(
        case_id="research_live_vague_low_signal",
        step="research",
        repo=_FAST_REPO,
        notes="zendesk vague complaint — should land low / requires-human, never high priority.",
        signals=(
            SignalSpec(
                signal_id="sig_vague",
                content="A customer wrote in to say 'the app just feels kind of slow sometimes'. No specifics.",
                source_product="zendesk",
                source_type="ticket",
                source_id="vague_slow",
                weight=0.3,
            ),
        ),
        expected=ResearchExpectation(
            expected_actionability=("requires_human_input", "not_actionable"),
            expected_priority=("P2", "P3", "P4"),
        ),
        scorers=(*default_research_scorers(), ResearchSummaryJudge()),
    ),
    ResearchCase(
        case_id="research_live_feature_request",
        step="research",
        repo=_FAST_REPO,
        notes="linear feature request — actionable-or-human, not a P0 emergency.",
        signals=(
            SignalSpec(
                signal_id="sig_feature",
                content=(
                    "Feature request: let users bulk-download an entire folder as a single zip instead of file "
                    "by file. Several customers have asked for this."
                ),
                source_product="linear",
                source_type="issue_created",
                source_id="bulk_download",
                weight=0.5,
            ),
        ),
        expected=ResearchExpectation(
            expected_actionability=("requires_human_input", "immediately_actionable"),
            expected_priority=("P2", "P3", "P4"),
            summary_must_mention=("download",),
        ),
        scorers=(*default_research_scorers(), ResearchSummaryJudge()),
    ),
]
