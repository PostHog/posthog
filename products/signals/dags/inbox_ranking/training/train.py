"""Per-head grading shared by every learner: holdout metrics, the label-permutation null, and the
readable rule the promotion gate reads.
"""

from collections.abc import Sequence

import numpy as np
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score

from posthog.dataclasses import frozen

from products.signals.dags.inbox_ranking.training.calibration import (
    CalibrationBucket,
    calibration_buckets,
    expected_calibration_error,
)
from products.signals.dags.inbox_ranking.training.classification import (
    UNKNOWN_THRESHOLD,
    ClassificationMetrics,
    classification_metrics,
)
from products.signals.dags.inbox_ranking.training.heads import Head
from products.signals.dags.inbox_ranking.training.within_team import NO_TEAMS, WithinTeamAuc, within_team_auc

# A readable head must also clear its own permutation null by this much; below it the AUC is
# within the noise of this many positives.
NULL_MARGIN = 0.05
# Each null is a full fit on permuted labels, so this multiplies the training cost per head. One
# draw swings with whichever feature the permuted fit happened to lean on, so the mean of a few
# draws is the number the margin is compared against, and the spread is reported so a wide band is
# visible.
NULL_PERMUTATIONS = 3


@frozen
class HeadMetrics:
    head: str
    train_rows: int
    train_positives: int
    holdout_rows: int
    holdout_positives: int
    holdout_auc: float | None
    # Mean and spread over NULL_PERMUTATIONS label-permutation fits scored on the holdout.
    null_auc: float | None
    null_auc_std: float | None
    readable: bool
    # Metrics for the dashboard, not the gate: the train-fit AUC on its own rows (the gap to
    # holdout_auc is the overfit signal), and holdout metrics that read better than AUC when
    # positives are rare.
    train_auc: float | None = None
    holdout_average_precision: float | None = None
    holdout_logloss: float | None = None
    holdout_positive_rate: float | None = None
    # The mean predicted score next to `holdout_positive_rate`, the rate it was predicting, and the
    # decile error between them. Both read the rows the head was capped to. `cap_examples` keeps whole
    # days, so the rate is the population rate of the kept window. Both also read the train-only fit, while the candidate that ships and the unseen side grades is
    # the refit on every row. A refit moves the predicted probabilities without moving their rank, so
    # part of a gap to the unseen numbers is the refit rather than holdout optimism.
    holdout_mean_score: float | None = None
    holdout_expected_calibration_error: float | None = None
    # The holdout graded at the positive rate of the train-only rows, the threshold fixed before the
    # holdout outcomes are read.
    holdout_classification: ClassificationMetrics = UNKNOWN_THRESHOLD
    # The positive rate of every row the refit that ships was fit on. The unseen grades of this
    # model read it as their threshold, so it is saved here rather than derived from the unseen rows.
    refit_classification_threshold: float | None = None
    # The holdout AUC over pairs inside one team only. The promotion gate keeps reading the pooled
    # `holdout_auc`.
    holdout_within_team: WithinTeamAuc = NO_TEAMS

    def as_dict(self) -> dict[str, object]:
        return {
            "head": self.head,
            "train_rows": self.train_rows,
            "train_positives": self.train_positives,
            "holdout_rows": self.holdout_rows,
            "holdout_positives": self.holdout_positives,
            "holdout_auc": self.holdout_auc,
            **self.holdout_within_team.as_dict(prefix="holdout_"),
            "null_auc": self.null_auc,
            "null_auc_std": self.null_auc_std,
            "null_permutations": NULL_PERMUTATIONS,
            "readable": self.readable,
            "train_auc": self.train_auc,
            "holdout_average_precision": self.holdout_average_precision,
            "holdout_logloss": self.holdout_logloss,
            "holdout_positive_rate": self.holdout_positive_rate,
            "holdout_mean_score": self.holdout_mean_score,
            "holdout_expected_calibration_error": self.holdout_expected_calibration_error,
            **self.holdout_classification.as_dict(prefix="holdout_"),
            "refit_classification_threshold": self.refit_classification_threshold,
        }


def _auc(y: np.ndarray, scores: np.ndarray) -> float | None:
    if y.sum() == 0 or y.sum() == len(y):
        return None
    return float(roc_auc_score(y, scores))


def _head_readable(
    holdout_auc: float | None, null_auc: float | None, holdout_positives: int, *, min_positives: int
) -> bool:
    """Readable = enough holdout positives, an above-chance holdout AUC, and clearing the head's own
    permutation null by NULL_MARGIN. The absolute 0.5 floor is load-bearing on top of the null
    margin because the null is a mean of a few noisy draws: an inversely predictive head (AUC below
    chance) can still beat a low null mean by the margin, and must not be graded readable."""
    if holdout_auc is None or null_auc is None:
        return False
    return holdout_positives >= min_positives and holdout_auc > 0.5 and holdout_auc - null_auc >= NULL_MARGIN


def head_metrics(
    head: Head,
    *,
    y_train: np.ndarray,
    train_scores: np.ndarray,
    y_test: np.ndarray,
    holdout_scores: np.ndarray,
    null_aucs: Sequence[float],
    refit_positive_rate: float,
    holdout_team_ids: np.ndarray,
) -> tuple[HeadMetrics, tuple[CalibrationBucket, ...]]:
    """One head's metrics and holdout calibration from the scores of its train-only fit.

    Every learner grades a head through this function, so the families' metadata carry the same
    fields with the same meaning, and one promotion rule reads them all. `null_aucs` are the holdout
    AUCs of the learner's fits on permuted labels.
    """
    holdout_auc = _auc(y_test, holdout_scores) if len(y_test) else None
    null_auc = float(np.mean(null_aucs)) if null_aucs else None
    null_auc_std = float(np.std(null_aucs)) if null_aucs else None
    readable = _head_readable(holdout_auc, null_auc, int(y_test.sum()), min_positives=head.min_holdout_positives)
    calibration = calibration_buckets(y_test.astype(bool), holdout_scores)
    metrics = HeadMetrics(
        head=head.name,
        train_rows=int(len(y_train)),
        train_positives=int(y_train.sum()),
        holdout_rows=int(len(y_test)),
        holdout_positives=int(y_test.sum()),
        holdout_auc=holdout_auc,
        null_auc=null_auc,
        null_auc_std=null_auc_std,
        readable=readable,
        train_auc=_auc(y_train, train_scores),
        holdout_average_precision=(
            float(average_precision_score(y_test, holdout_scores)) if holdout_auc is not None else None
        ),
        # Logloss is defined on a single-class holdout, unlike AUC and average precision.
        holdout_logloss=float(log_loss(y_test, holdout_scores, labels=[0, 1])) if len(y_test) else None,
        holdout_positive_rate=float(y_test.mean()) if len(y_test) else None,
        holdout_mean_score=float(holdout_scores.mean()) if len(y_test) else None,
        holdout_expected_calibration_error=expected_calibration_error(calibration),
        holdout_classification=classification_metrics(y_test, holdout_scores, float(y_train.mean())),
        refit_classification_threshold=refit_positive_rate,
        holdout_within_team=within_team_auc(y_test, holdout_scores, holdout_team_ids),
    )
    return metrics, calibration


@frozen
class HoldoutGrade:
    auc: float | None
    expected_calibration_error: float | None
    positives: int


def holdout_grade(y: np.ndarray, scores: np.ndarray) -> HoldoutGrade:
    """A saved model's AUC and calibration error on a candidate's holdout outcomes `y`."""
    return HoldoutGrade(
        auc=_auc(y, scores),
        expected_calibration_error=expected_calibration_error(calibration_buckets(y.astype(bool), scores)),
        positives=int(y.sum()),
    )
