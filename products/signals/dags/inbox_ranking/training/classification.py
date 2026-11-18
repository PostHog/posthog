"""Per-head classification metrics at a frozen threshold.

AUC and calibration grade the scores as a ranking and as probabilities. They do not say how many of
the reports a head flags have the outcome, or how many of the outcomes it flags. Those answers need
a cut, and every head predicts positive when its score is at least the positive rate of the rows its
booster was fit on: "at least as likely as the average fitting example", not "above 50%".

The threshold comes from the fit, never from the rows being graded. The holdout grade reads the
train-only rate, and the unseen grade reads the refit rate saved with the model. A row budget keeps
every positive, so that rate is the sample's rate and not the population's prevalence.
"""

import numpy as np

from posthog.dataclasses import frozen


@frozen
class ClassificationMetrics:
    """The confusion counts at `threshold`, and the ratios derived from them.

    Every field is None when the threshold is unknown, which is the case for a model or a scores
    object saved before thresholds existed. With a known threshold the counts are always ints,
    zero on an empty cohort, and a ratio is None only when its denominator is zero.
    """

    threshold: float | None = None
    true_positives: int | None = None
    false_positives: int | None = None
    true_negatives: int | None = None
    false_negatives: int | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    specificity: float | None = None
    accuracy: float | None = None
    balanced_accuracy: float | None = None
    predicted_positive_rate: float | None = None

    def as_dict(self, prefix: str = "") -> dict[str, int | float | None]:
        return {
            f"{prefix}classification_threshold": self.threshold,
            f"{prefix}true_positives": self.true_positives,
            f"{prefix}false_positives": self.false_positives,
            f"{prefix}true_negatives": self.true_negatives,
            f"{prefix}false_negatives": self.false_negatives,
            f"{prefix}precision": self.precision,
            f"{prefix}recall": self.recall,
            f"{prefix}f1": self.f1,
            f"{prefix}specificity": self.specificity,
            f"{prefix}accuracy": self.accuracy,
            f"{prefix}balanced_accuracy": self.balanced_accuracy,
            f"{prefix}predicted_positive_rate": self.predicted_positive_rate,
        }


UNKNOWN_THRESHOLD = ClassificationMetrics()


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def classification_metrics(outcomes: np.ndarray, scores: np.ndarray, threshold: float | None) -> ClassificationMetrics:
    """The metrics of `scores >= threshold` against `outcomes`. A score equal to the threshold is a
    positive prediction."""
    if threshold is None:
        return UNKNOWN_THRESHOLD
    actual = np.asarray(outcomes, dtype=bool)
    predicted = np.asarray(scores, dtype=float) >= threshold
    tp = int((predicted & actual).sum())
    fp = int((predicted & ~actual).sum())
    tn = int((~predicted & ~actual).sum())
    fn = int((~predicted & actual).sum())
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    specificity = _ratio(tn, tn + fp)
    return ClassificationMetrics(
        threshold=float(threshold),
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        # 2TP / (2TP + FP + FN) is the harmonic mean where precision and recall both exist, and
        # reads 0 rather than 0/0 when both are 0.
        f1=_ratio(2 * tp, 2 * tp + fp + fn) if precision is not None and recall is not None else None,
        specificity=specificity,
        accuracy=_ratio(tp + tn, len(actual)),
        balanced_accuracy=(recall + specificity) / 2 if recall is not None and specificity is not None else None,
        predicted_positive_rate=_ratio(tp + fp, len(actual)),
    )
