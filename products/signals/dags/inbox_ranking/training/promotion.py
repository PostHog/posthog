"""Champion promotion rule.

A candidate replaces the champion when it is at least as good on every head the champion could
read, has at least one readable head itself, and enough days have passed since the last promotion.
The quality gates run before the wait, so `gates_passed` says whether the candidate is good enough
even on a day the wait blocks it. Pure function over the two metadata records so the rule is
testable without S3.

`champion_grades` holds the champion's holdout booster graded on the candidate's holdout, so both
models are compared on one set of reports; the stored AUCs are the fallback for a head without one.

AUC reads the ranking only, so a candidate must also not be worse calibrated than the champion on
those heads. The champion's calibration error comes from the same paired grade. There is no stored
fallback: a champion's stored error was read on its own holdout, which can hold a different base
rate, so a head without a paired error skips this check.

A paired grade also says how many positives the shared holdout holds. Below the head's
`min_holdout_positives` neither model can be read on it, so the head is skipped, not counted as a
regression. A head the candidate did not train still blocks: a candidate must not replace a champion
by losing a head the champion serves.

An owner can change one family's outcome through the `promotion` override (see
`products/signals/backend/ranking/overrides.py`). `skip_gates` waives named checks inside the rule,
and `apply_promotion_override` applies `freeze` and `force` to the rule's decision.
"""

import datetime
from collections.abc import Collection, Mapping
from typing import Any

from posthog.dataclasses import frozen

from products.signals.backend.ranking.overrides import PromotionOverride
from products.signals.dags.inbox_ranking.training.train import HoldoutGrade

# A candidate may be this much worse than the champion on a readable head and still promote: at
# the readability floor the AUC's noise is about this size, so exact dominance would never trigger.
AUC_TOLERANCE = 0.02
# A candidate's holdout calibration error may exceed the champion's paired one by this much and
# still promote. The error is in probability units and a decile read on one holdout is noisy by
# about this much at the readability floor.
ECE_TOLERANCE = 0.02


@frozen
class PromotionDecision:
    promote: bool
    reason: str
    # True when the candidate passed every quality gate, whether or not the wait blocked it.
    gates_passed: bool
    # Champion-readable heads whose shared holdout had too few positives to compare.
    skipped_heads: tuple[str, ...] = ()


@frozen
class PromotionOutcome:
    promote: bool
    # "frozen", "forced" or "skipped_gates" when an override applied, else None.
    override: str | None


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
    champion_grades: Mapping[str, HoldoutGrade] | None = None,
    min_holdout_positives: Mapping[str, int] | None = None,
    skip_gates: Collection[str] = (),
) -> PromotionDecision:
    """`skip_gates` waives `min_days` (the wait since the last promotion), `ece` (the calibration
    check) and `min_holdout_positives` (a head whose candidate holdout has fewer positives than its
    minimum is skipped rather than blocking)."""
    if not _readable_aucs(candidate):
        return PromotionDecision(promote=False, reason="candidate has no readable head", gates_passed=False)
    if champion is None:
        return PromotionDecision(promote=True, reason="no champion yet", gates_passed=True)

    # A backfill replays old partitions, so reject any candidate not newer than the champion to keep
    # the pointer from moving backwards to a stale model. model_version is the partition date, and
    # ISO date strings compare chronologically (same ordering the dataset dag's latest/ stamp relies on).
    if candidate["model_version"] <= champion["model_version"]:
        return PromotionDecision(
            promote=False,
            reason=f"candidate {candidate['model_version']} is not newer than champion {champion['model_version']}",
            gates_passed=False,
        )

    decision = _compare_to_champion(candidate, champion, champion_grades or {}, min_holdout_positives or {}, skip_gates)
    promoted_at = datetime.datetime.fromisoformat(champion["promoted_at"])
    if (
        decision.promote
        and "min_days" not in skip_gates
        and now - promoted_at < datetime.timedelta(days=min_days_between)
    ):
        return PromotionDecision(
            promote=False,
            reason=f"candidate passed every gate but champion {champion['model_version']} promoted less than {min_days_between}d ago",
            gates_passed=True,
            skipped_heads=decision.skipped_heads,
        )
    return decision


def _compare_to_champion(
    candidate: Mapping[str, Any],
    champion: Mapping[str, Any],
    champion_grades: Mapping[str, HoldoutGrade],
    min_holdout_positives: Mapping[str, int],
    skip_gates: Collection[str],
) -> PromotionDecision:
    candidate_aucs = _readable_aucs(candidate)
    candidate_heads = {head["head"]: head for head in candidate.get("heads", [])}
    skipped: list[str] = []
    for head, stored_auc in _readable_aucs(champion).items():
        candidate_positives = candidate_heads.get(head, {}).get("holdout_positives")
        if (
            "min_holdout_positives" in skip_gates
            and candidate_positives is not None
            and candidate_positives < min_holdout_positives.get(head, 0)
        ):
            skipped.append(head)
            continue
        grade = champion_grades.get(head)
        if grade is None:
            # No shared holdout: readability was read on two different holdouts, so compare it as stored.
            candidate_auc = candidate_aucs.get(head)
            if candidate_auc is None:
                return PromotionDecision(
                    promote=False, reason=f"{head} readable on champion but not on candidate", gates_passed=False
                )
            champion_auc = stored_auc
        else:
            if head not in candidate_heads:
                return PromotionDecision(promote=False, reason=f"{head} not trained on candidate", gates_passed=False)
            if grade.positives < min_holdout_positives.get(head, 0):
                skipped.append(head)
                continue
            # The candidate is graded whether or not it cleared its null margin: a weak head fails on its numbers.
            raw_auc = candidate_heads[head].get("holdout_auc")
            if raw_auc is None:
                return PromotionDecision(
                    promote=False, reason=f"{head} has no holdout AUC on candidate", gates_passed=False
                )
            candidate_auc = float(raw_auc)
            champion_auc = grade.auc if grade.auc is not None else stored_auc
        if candidate_auc < champion_auc - AUC_TOLERANCE:
            return PromotionDecision(
                promote=False,
                reason=f"{head} regressed: {candidate_auc:.3f} vs champion {champion_auc:.3f}",
                gates_passed=False,
            )
        champion_ece = grade.expected_calibration_error if grade is not None else None
        raw_ece = candidate_heads.get(head, {}).get("holdout_expected_calibration_error")
        candidate_ece = float(raw_ece) if raw_ece is not None else None
        if (
            "ece" not in skip_gates
            and champion_ece is not None
            and candidate_ece is not None
            and candidate_ece > champion_ece + ECE_TOLERANCE
        ):
            return PromotionDecision(
                promote=False,
                reason=f"{head} calibration regressed: ECE {candidate_ece:.3f} vs champion {champion_ece:.3f}",
                gates_passed=False,
            )
    if skipped:
        return PromotionDecision(
            promote=True,
            reason=f"candidate at or above champion on every comparable head (skipped: {', '.join(skipped)})",
            gates_passed=True,
            skipped_heads=tuple(skipped),
        )
    return PromotionDecision(
        promote=True, reason="candidate at or above champion on every readable head", gates_passed=True
    )


def apply_promotion_override(
    decision: PromotionDecision,
    candidate: Mapping[str, Any],
    champion: Mapping[str, Any] | None,
    override: PromotionOverride,
) -> PromotionOutcome:
    """The rule's decision with `freeze` or `force` applied.

    `force` still needs a readable head on a candidate newer than the champion, so it can never
    move the pointer backwards or onto a model with nothing to read.
    """
    if override.freeze:
        return PromotionOutcome(promote=False, override="frozen")
    if (
        override.force
        and not decision.promote
        and _readable_aucs(candidate)
        and (champion is None or candidate["model_version"] > champion["model_version"])
    ):
        return PromotionOutcome(promote=True, override="forced")
    return PromotionOutcome(promote=decision.promote, override="skipped_gates" if override.skip_gates else None)
