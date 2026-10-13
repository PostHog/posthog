"""Score calibration for the ranking heads.

AUC grades the ranking and nothing else, so a head that ranks every report correctly can still
predict 0.2 where the outcome happens on 2% of the reports. A threshold, and the composite score
the heads exist for (a merge probability against a weighted refund penalty), only mean something
when both sides read as probabilities. Both grading sides cut their deciles here, so the unseen
number and the holdout number are the same measurement on two sets of rows.
"""

from collections.abc import Mapping, Sequence

import numpy as np

from posthog.dataclasses import frozen

BUCKETS = 10


@frozen
class CalibrationBucket:
    """One decile of the scores, lowest first."""

    bucket: int
    rows: int
    positives: int
    mean_score: float
    realized_rate: float

    def as_dict(self) -> dict[str, object]:
        return {
            "bucket": self.bucket,
            "rows": self.rows,
            "positives": self.positives,
            "mean_score": self.mean_score,
            "realized_rate": self.realized_rate,
        }


def calibration_buckets(
    outcomes: np.ndarray, scores: np.ndarray, *, buckets: int = BUCKETS
) -> tuple[CalibrationBucket, ...]:
    """`scores` and `outcomes` split into at most `buckets` groups by score rank, lowest first.

    The split is on rank rather than on score value because these heads score a rare outcome: most
    reports land on a short run of near-identical low scores, and a value cut then puts most of the
    rows in one bucket and leaves others empty.

    One score can still hold more rows than a group, so every boundary moves to the end of the run
    of equal scores it falls inside. A run split across two groups would give each of them a
    realized rate that depends on the order the rows arrived in, and report a calibration gap that
    is not there. Merging the run costs groups instead: a head whose scores are one value reports a
    single bucket, and a head with fewer rows than buckets reports one bucket per row.
    """
    if not len(scores):
        return ()
    order = np.argsort(scores, kind="stable")
    ranked = scores[order]
    return tuple(
        CalibrationBucket(
            bucket=index + 1,
            rows=len(group),
            positives=int(outcomes[group].sum()),
            mean_score=float(scores[group].mean()),
            realized_rate=float(outcomes[group].mean()),
        )
        for index, group in enumerate(np.split(order, _bucket_edges(ranked, buckets)))
    )


def _bucket_edges(ranked: np.ndarray, buckets: int) -> np.ndarray:
    """The indexes to cut `ranked`, a score column in ascending order, into near-equal groups, with
    every cut that falls inside a run of equal scores moved to the end of that run."""
    rows = len(ranked)
    edges = np.unique(np.arange(1, buckets) * rows // buckets)
    edges = edges[(edges > 0) & (edges < rows)]
    inside_a_run = ranked[edges - 1] == ranked[edges]
    edges = np.where(inside_a_run, np.searchsorted(ranked, ranked[edges], side="right"), edges)
    edges = np.unique(edges)
    return edges[edges < rows]


def expected_calibration_error(buckets: Sequence[CalibrationBucket]) -> float | None:
    """The row-weighted mean absolute gap between a bucket's mean score and its realized rate.

    Row-weighted rather than a plain mean over buckets: the buckets are near-equal but not equal,
    and the last one absorbs the remainder. None when there are no rows to read, so the series has
    the same gaps as the AUC.
    """
    rows = sum(bucket.rows for bucket in buckets)
    if not rows:
        return None
    return float(sum(bucket.rows * abs(bucket.mean_score - bucket.realized_rate) for bucket in buckets) / rows)


def bucket_rows(buckets: Sequence[CalibrationBucket], identity: Mapping[str, object]) -> list[dict[str, object]]:
    """One dict per bucket: what was graded, how many buckets the table holds, and the bucket's own
    counts. Both grading sides emit these as one event per bucket, so the shape is defined once."""
    return [{**identity, "calibration_buckets": len(buckets), **bucket.as_dict()} for bucket in buckets]
