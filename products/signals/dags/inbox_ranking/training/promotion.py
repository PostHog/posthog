"""Champion promotion rule.

A candidate replaces the champion when it is at least as good on every head the champion could
read, has at least one readable head itself, and enough days have passed since the last promotion
(scores are consumed by an online shadow read, and a champion that changes every day muddies it).
Pure function over the two metadata records so the rule is testable without S3. The champion's
AUCs should be `champion_aucs`, its holdout booster graded on the candidate's holdout, so both
models are compared on one set of reports; the stored numbers are the fallback.
"""

import datetime
from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen

# A candidate may be this much worse than the champion on a readable head and still promote: at
# the readability floor the AUC's noise is about this size, so exact dominance would never trigger.
AUC_TOLERANCE = 0.02


@frozen
class PromotionDecision:
    promote: bool
    reason: str


def _readable_aucs(metadata: Mapping[str, Any]) -> dict[str, float]:
    return {
        head["head"]: float(head["holdout_auc"])
        for head in metadata.get("heads", [])
        if head.get("readable") and head.get("holdout_auc") is not None
    }


def decide_promotion(
    candidate: Mapping[str, Any],
    champion: Mapping[str, Any] | None,
    *,
    now: datetime.datetime,
    min_days_between: int,
    champion_aucs: Mapping[str, float] | None = None,
) -> PromotionDecision:
    candidate_aucs = _readable_aucs(candidate)
    if not candidate_aucs:
        return PromotionDecision(promote=False, reason="candidate has no readable head")
    if champion is None:
        return PromotionDecision(promote=True, reason="no champion yet")

    # A backfill replays old partitions, so reject any candidate not newer than the champion to keep
    # the pointer from moving backwards to a stale model. model_version is the partition date, and
    # ISO date strings compare chronologically (same ordering the dataset dag's latest/ stamp relies on).
    if candidate["model_version"] <= champion["model_version"]:
        return PromotionDecision(
            promote=False,
            reason=f"candidate {candidate['model_version']} is not newer than champion {champion['model_version']}",
        )

    promoted_at = datetime.datetime.fromisoformat(champion["promoted_at"])
    if now - promoted_at < datetime.timedelta(days=min_days_between):
        return PromotionDecision(
            promote=False, reason=f"champion {champion['model_version']} promoted less than {min_days_between}d ago"
        )
    for head, stored_auc in _readable_aucs(champion).items():
        champion_auc = champion_aucs.get(head, stored_auc) if champion_aucs else stored_auc
        candidate_auc = candidate_aucs.get(head)
        if candidate_auc is None:
            return PromotionDecision(promote=False, reason=f"{head} readable on champion but not on candidate")
        if candidate_auc < champion_auc - AUC_TOLERANCE:
            return PromotionDecision(
                promote=False, reason=f"{head} regressed: {candidate_auc:.3f} vs champion {champion_auc:.3f}"
            )
    return PromotionDecision(promote=True, reason="candidate at or above champion on every readable head")
