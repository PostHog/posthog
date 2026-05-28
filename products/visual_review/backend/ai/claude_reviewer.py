"""LLM-backed agent reviewer for visual_review.

One batched call per run to Claude Haiku 4.5 over structured snapshot
metadata — no images, no per-snapshot calls. The model reads cluster
summaries, diff metrics, and identifier names, and emits a verdict
(``approved`` / ``rejected`` / ``deferred``) per snapshot plus a
run-level rollup.

Why Haiku + structured metadata: the diff pipeline already gives us
strong signals (cluster shape, SSIM, change_kind, size_mismatch); a
vision model on PNG bytes would be ~100x more expensive without adding
much over those numbers for the obvious-noise vs obvious-intentional
buckets. Vision is reserved for a future escalation tier.
"""

from __future__ import annotations

import json
from typing import Literal

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ee.hogai.llm import MaxChatAnthropic

from .heuristic import SnapshotSignals

logger = structlog.get_logger(__name__)

MODEL_NAME = "claude-haiku-4-5"

# Cap per-call snapshot count so a pathological run can't blow the context
# window or the latency budget. Above this, we sample by severity (worst
# diffs first) and tell the model how many we dropped.
MAX_SNAPSHOTS_PER_CALL = 40

Verdict = Literal["approved", "rejected", "deferred"]

SYSTEM_PROMPT = """You are a visual regression triage assistant for PostHog's Visual Review product.

Visual Review captures screenshots in CI, diffs each one against a baseline image committed to the repo, and asks a human to approve genuine visual changes. Your job is to look at the **structured diff metrics** for each changed snapshot in a run and decide whether the change looks intentional, looks like noise/instability, or needs a human to actually look at the images.

You will NOT see the images. You only see numeric diff metrics, cluster summaries, and snapshot identifiers (which encode the test file path, e.g. `scenes-app-settings-user--profile--dark`).

For each snapshot, emit ONE of three verdicts:

- **approved** — the change looks intentional and focused (single tight cluster, modest pixel diff, consistent with a code change). A reviewer would almost certainly accept it.
- **rejected** — the change looks like rendering noise, anti-aliasing, a viewport drift, or a partial render. A reviewer would NOT accept this; the developer needs to investigate. Examples: dimensions changed mid-run; many tiny clusters scattered across the image; high SSIM but lots of diff pixels.
- **deferred** — the metrics don't make the call obvious. A reviewer needs to actually look at the images. Use this when in doubt; it's better than guessing.

Be conservative with `approved` — when uncertain, defer. The cost of a wrong `approved` (regression shipped) is much higher than a wrong `deferred` (human spends 30 seconds looking).

Also emit a run-level rollup verdict:
- `rejected` if ANY snapshot was rejected
- `deferred` if ANY snapshot was deferred (and none rejected)
- `approved` only if ALL snapshots were approved

Keep reasoning to one short sentence per snapshot — a human will read these inline in the review UI."""


class SnapshotVerdictOutput(BaseModel):
    """LLM output for a single snapshot."""

    identifier: str = Field(description="Snapshot identifier from the input — must match exactly.")
    verdict: Verdict = Field(description="One of: approved, rejected, deferred.")
    confidence: float = Field(ge=0.0, le=1.0, description="Your confidence in this verdict, 0.0 to 1.0.")
    reasoning: str = Field(description="One short sentence explaining the verdict, shown to the human reviewer.")


class RunReviewOutput(BaseModel):
    """LLM output for the whole run."""

    run_verdict: Verdict = Field(description="Rollup verdict for the run.")
    run_confidence: float = Field(ge=0.0, le=1.0, description="Rollup confidence (min across snapshots).")
    run_summary: str = Field(
        description="One- or two-sentence summary of the run-level verdict, shown to the human reviewer."
    )
    snapshots: list[SnapshotVerdictOutput] = Field(description="One entry per snapshot the agent reviewed.")


def _build_user_message(
    run_metadata: dict,
    signals: list[SnapshotSignals],
    dropped: int,
) -> str:
    """Render the structured run + snapshot context as a prompt body."""
    payload = {
        "run": run_metadata,
        "snapshots": [s.to_dict() for s in signals],
    }
    body = (
        "Review this Visual Review run. Below is the run context and the diff metrics for every changed/new/removed snapshot.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```\n\n"
    )
    if dropped > 0:
        body += (
            f"Note: this run had {dropped} additional snapshot(s) that were dropped from this call to stay under the context budget. "
            "Focus on the ones above; the rollup should still reflect 'deferred' if you think the dropped ones could change the call.\n\n"
        )
    body += "Produce a verdict per snapshot AND a run-level rollup. Use the schema you've been given."
    return body


def _select_signals(signals: list[SnapshotSignals]) -> tuple[list[SnapshotSignals], int]:
    """Cap snapshot count, dropping the smallest-diff ones first.

    A run with 200 changed snapshots usually means a sweeping
    cross-cutting change — sampling the highest-signal ones is more
    useful than truncating in order.
    """
    if len(signals) <= MAX_SNAPSHOTS_PER_CALL:
        return signals, 0

    def severity(s: SnapshotSignals) -> float:
        if s.diff_percentage is not None:
            return s.diff_percentage
        if s.ssim_score is not None:
            return (1.0 - s.ssim_score) * 100
        return 0.0

    sorted_signals = sorted(signals, key=severity, reverse=True)
    kept = sorted_signals[:MAX_SNAPSHOTS_PER_CALL]
    dropped = len(signals) - len(kept)
    return kept, dropped


def review_run(
    *,
    run_metadata: dict,
    signals: list[SnapshotSignals],
    user,
    team,
) -> RunReviewOutput:
    """Call Claude over the run's structured snapshot metadata.

    Returns a ``RunReviewOutput`` with one verdict per snapshot plus a
    rollup. Synchronous (the run scene's "Ask AI" button is a foreground
    request); typical latency is sub-second for runs of <40 snapshots.
    """
    selected, dropped = _select_signals(signals)
    user_message = _build_user_message(run_metadata, selected, dropped)

    # max_tokens at 8K: at the per-call cap of 40 snapshots, output JSON is
    # roughly 40 * (identifier + one-sentence reasoning) ≈ 4–6K tokens plus
    # the rollup. 4K was too tight and risked truncating structured output
    # on the dense runs reviewers most want help triaging.
    llm = MaxChatAnthropic(
        model=MODEL_NAME,
        user=user,
        team=team,
        temperature=0.0,
        billable=True,
        max_tokens=8192,
        posthog_properties={"ai_feature": "visual_review_agent"},
    ).with_structured_output(RunReviewOutput, include_raw=False)

    logger.info(
        "visual_review.agent_review.invoke",
        team_id=getattr(team, "id", None),
        snapshot_count=len(selected),
        dropped=dropped,
    )

    response = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_message)])
    # with_structured_output returns the parsed pydantic instance directly
    if not isinstance(response, RunReviewOutput):
        raise RuntimeError(f"Unexpected LLM response shape: {type(response).__name__}")

    # Sanity: identifiers in the response must be a subset of what we sent
    sent_identifiers = {s.identifier for s in selected}
    response.snapshots = [s for s in response.snapshots if s.identifier in sent_identifiers]

    return response
