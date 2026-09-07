"""Per-head XGBoost training over the scoring-moment examples.

Deliberately plain: fixed hyperparameters, a time-based holdout by report, AUC plus a
label-permutation null per head. The booster is saved as UBJSON bytes with its feature names, so
the serving side can assert `booster.feature_names == FEATURE_NAMES` at load.
"""

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import FEATURE_NAMES
from products.signals.dags.inbox_ranking.training.examples import holdout_mask
from products.signals.dags.inbox_ranking.training.heads import Head

XGB_PARAMS: dict[str, object] = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "eval_metric": "auc",
    "n_jobs": 2,
}
# A readable head must also clear its own permutation null by this much; below it the AUC is
# within the noise of this many positives.
NULL_MARGIN = 0.05
# Each null is a full fit on permuted labels, so this multiplies the training cost per head. One
# draw swings with whichever feature the permuted fit happened to lean on (age_hours dominates),
# which put single-draw nulls at 0.38 on a 35k-row holdout; the mean of a few draws is the number
# the margin is compared against, and the spread is reported so a wide band is visible.
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

    def as_dict(self) -> dict[str, object]:
        return {
            "head": self.head,
            "train_rows": self.train_rows,
            "train_positives": self.train_positives,
            "holdout_rows": self.holdout_rows,
            "holdout_positives": self.holdout_positives,
            "holdout_auc": self.holdout_auc,
            "null_auc": self.null_auc,
            "null_auc_std": self.null_auc_std,
            "null_permutations": NULL_PERMUTATIONS,
            "readable": self.readable,
            "train_auc": self.train_auc,
            "holdout_average_precision": self.holdout_average_precision,
            "holdout_logloss": self.holdout_logloss,
            "holdout_positive_rate": self.holdout_positive_rate,
        }


@frozen
class TrainedHead:
    head: str
    booster_ubj: bytes
    # The train-only fit that produced the holdout metrics, kept so a later candidate can grade this
    # model on its own holdout; None when there were no holdout rows.
    holdout_booster_ubj: bytes | None
    metrics: HeadMetrics


def _ubj(model: xgb.XGBClassifier) -> bytes:
    return bytes(model.get_booster().save_raw("ubj"))


def _fit(x: pd.DataFrame, y: np.ndarray, seed: int) -> xgb.XGBClassifier:
    model = xgb.XGBClassifier(**XGB_PARAMS, random_state=seed)
    model.fit(x, y, verbose=False)
    return model


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


def train_head(examples: pd.DataFrame, head: Head, *, holdout_days: int, seed: int = 0) -> TrainedHead | None:
    """Fit one head; None when there is nothing to fit (no positive or no negative in train)."""
    rows = examples[examples["head"] == head.name]
    if rows.empty:
        return None
    test = holdout_mask(rows, holdout_days).to_numpy()
    x = rows[list(FEATURE_NAMES)].astype(float)
    y = rows["label"].to_numpy(dtype=int)
    x_train, y_train, x_test, y_test = x[~test], y[~test], x[test], y[test]
    if len(y_train) == 0 or y_train.sum() == 0 or y_train.sum() == len(y_train):
        return None

    model = _fit(x_train, y_train, seed)
    train_auc = _auc(y_train, model.predict_proba(x_train)[:, 1])
    holdout_scores = model.predict_proba(x_test)[:, 1] if len(y_test) else np.array([])
    holdout_auc = _auc(y_test, holdout_scores) if len(y_test) else None

    null_auc: float | None = None
    null_auc_std: float | None = None
    if holdout_auc is not None:
        rng = np.random.default_rng(seed)
        null_aucs = [
            auc
            for draw in range(NULL_PERMUTATIONS)
            if (auc := _auc(y_test, _fit(x_train, rng.permutation(y_train), seed + draw).predict_proba(x_test)[:, 1]))
            is not None
        ]
        if null_aucs:
            null_auc = float(np.mean(null_aucs))
            null_auc_std = float(np.std(null_aucs))

    readable = _head_readable(holdout_auc, null_auc, int(y_test.sum()), min_positives=head.min_holdout_positives)
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
        train_auc=train_auc,
        holdout_average_precision=(
            float(average_precision_score(y_test, holdout_scores)) if holdout_auc is not None else None
        ),
        # Logloss is defined on a single-class holdout, unlike AUC and average precision.
        holdout_logloss=float(log_loss(y_test, holdout_scores, labels=[0, 1])) if len(y_test) else None,
        holdout_positive_rate=float(y_test.mean()) if len(y_test) else None,
    )
    # Refit on everything before shipping: the holdout only exists to grade the recipe.
    final = _fit(x, y, seed)
    return TrainedHead(
        head=head.name,
        booster_ubj=_ubj(final),
        holdout_booster_ubj=_ubj(model) if len(y_test) else None,
        metrics=metrics,
    )


def booster_holdout_auc(booster_ubj: bytes, examples: pd.DataFrame, head: Head, *, holdout_days: int) -> float | None:
    """AUC of a saved booster on `head`'s holdout rows of `examples`: the same rows `train_head`
    grades a candidate on, so a champion and a candidate can be compared on one set."""
    rows = examples[examples["head"] == head.name]
    if rows.empty:
        return None
    test = holdout_mask(rows, holdout_days).to_numpy()
    if not test.any():
        return None
    booster = xgb.Booster()
    booster.load_model(bytearray(booster_ubj))
    # The booster's own names, not the current contract: a champion trained before an additive
    # schema bump is still scorable on its subset. A name the examples lack means the schemas are
    # incompatible, and the caller falls back to the stored AUC.
    names = list(booster.feature_names or FEATURE_NAMES)
    if any(name not in rows for name in names):
        return None
    x = rows.loc[test, names].astype(float)
    y = rows.loc[test, "label"].to_numpy(dtype=int)
    return _auc(y, booster.predict(xgb.DMatrix(x, feature_names=names)))
