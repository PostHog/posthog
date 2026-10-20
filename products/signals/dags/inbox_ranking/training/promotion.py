"""Candidate grading rule.

The rule says whether a candidate would replace the incumbent: it is at least as good on every head
the incumbent could read, and it has at least one readable head itself. The incumbent is the served
model when it has the candidate's `model_name`. The rule never moves the served pointer: a person
does that with `inbox_ranking_promote_job`, and reads this decision to choose. Pure function over
the two metadata records so the rule is testable without S3.

`champion_grades` holds the champion's holdout booster graded on the candidate's holdout, so both
models are compared on one set of reports; the stored AUCs are the fallback for a head without one.

AUC reads the ranking only, so a candidate must also not be worse calibrated than the champion on
those heads. The champion's calibration error comes from the same paired grade. There is no stored
fallback: a champion's stored error was read on its own holdout, which can hold a different base
rate, so a head without a paired error skips this check.

A paired grade also says how many positives the shared holdout holds. Below the head's
`min_holdout_positives` neither model can be read on it, so the head is skipped, not counted as a
regression. A head the candidate did not train still blocks: a candidate must not replace a champion
by losing a head the champion serves. A champion head that is no longer in `HEADS` is not compared:
it was retired, so no candidate trains it.
"""

from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen

from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME
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
    # True when the candidate passed every quality gate.
    gates_passed: bool
    # Champion-readable heads whose shared holdout had too few positives to compare.
    skipped_heads: tuple[str, ...] = ()


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
    champion_grades: Mapping[str, HoldoutGrade] | None = None,
    min_holdout_positives: Mapping[str, int] | None = None,
) -> PromotionDecision:
    if not _readable_aucs(candidate):
        return PromotionDecision(promote=False, reason="candidate has no readable head", gates_passed=False)
    if champion is None:
        return PromotionDecision(
            promote=True, reason="no served model of this model_name to compare against", gates_passed=True
        )

    # A backfill replays old partitions, so reject any candidate not newer than the champion to keep
    # the pointer from moving backwards to a stale model. model_version is the partition date, and
    # ISO date strings compare chronologically (same ordering the dataset dag's latest/ stamp relies on).
    if candidate["model_version"] <= champion["model_version"]:
        return PromotionDecision(
            promote=False,
            reason=f"candidate {candidate['model_version']} is not newer than champion {champion['model_version']}",
            gates_passed=False,
        )

    return _compare_to_champion(candidate, champion, champion_grades or {}, min_holdout_positives or {})


def _compare_to_champion(
    candidate: Mapping[str, Any],
    champion: Mapping[str, Any],
    champion_grades: Mapping[str, HoldoutGrade],
    min_holdout_positives: Mapping[str, int],
) -> PromotionDecision:
    candidate_aucs = _readable_aucs(candidate)
    candidate_heads = {head["head"]: head for head in candidate.get("heads", [])}
    skipped: list[str] = []
    for head, stored_auc in _readable_aucs(champion).items():
        if head not in HEADS_BY_NAME:
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
        if champion_ece is not None and candidate_ece is not None and candidate_ece > champion_ece + ECE_TOLERANCE:
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
