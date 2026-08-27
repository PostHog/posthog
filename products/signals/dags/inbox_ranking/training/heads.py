"""The outcome heads the v0 ranking model predicts.

Each head is a cohort (which reports are scoreable examples), a binary label, and a horizon: the
label is "the outcome happened within `horizon_days` of the scoring moment", evaluated from the
cumulative label columns the dataset dag snapshots. Cohort and label are vectorized over a frame
of `inbox_report_labels` columns, so the same definitions read the snapshot at scoring time (label
must still be 0) and the snapshot `horizon_days` later (the label).

Mirrors the workspace `heads.py` (random-dev-internal, `inbox-ranking/`) for the four heads with
enough positives to ship; the other ten stay workspace-only until they are readable.
"""

from collections.abc import Callable

import pandas as pd

from posthog.dataclasses import frozen

from products.signals.dags.inbox_ranking.common import WRONG_DISMISSAL_REASONS


def _count(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].fillna(0).astype(int) if column in frame else pd.Series(0, index=frame.index)


def impressed(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "impression_unit_count") > 0


def everyone(frame: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=frame.index)


def opened(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "open_count") > 0


def acted(frame: pd.DataFrame) -> pd.Series:
    return (_count(frame, "create_pr_click_count") + _count(frame, "discuss_count")) > 0


def dismissed_as_wrong(frame: pd.DataFrame) -> pd.Series:
    if "wrong_dismissal_count" in frame:
        return _count(frame, "wrong_dismissal_count") > 0
    # Partitions written before the cumulative count existed carry only the latest-wins reason,
    # which a later restore or re-dismissal can overwrite.
    if "dismissal_reason" not in frame:
        return pd.Series(False, index=frame.index)
    return frame["dismissal_reason"].isin(WRONG_DISMISSAL_REASONS)


def pr_created(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "pr_created_count") > 0


@frozen
class Head:
    name: str
    cohort: Callable[[pd.DataFrame], pd.Series]
    label: Callable[[pd.DataFrame], pd.Series]
    horizon_days: int
    # Below this many positives in the holdout the head's AUC is noise; the promotion gate ignores it.
    min_holdout_positives: int
    # The label comes from the status-change stream, whose tenant provenance the dataset dag
    # cross-checks; rows that fail that check are unusable for this head.
    status_labels: bool = False


HEADS: tuple[Head, ...] = (
    # Of the reports users saw, which got opened by anyone? Opens land within hours of impression.
    Head(name="open", cohort=impressed, label=opened, horizon_days=3, min_holdout_positives=50),
    # Of the reports users saw, which drew a create-PR click or a discuss?
    Head(name="action", cohort=impressed, label=acted, horizon_days=7, min_holdout_positives=30),
    # Of the reports users saw, which were dismissed as wrong / unclear / intentional - the
    # precision-failure negative. already_fixed and wontfix_irrelevant are deliberately not here.
    Head(
        name="dismiss_wrong",
        cohort=impressed,
        label=dismissed_as_wrong,
        horizon_days=7,
        min_holdout_positives=30,
        status_labels=True,
    ),
    # Which reports get a PR at all? Cohort is every report the sweep would score.
    Head(name="pr_created", cohort=everyone, label=pr_created, horizon_days=7, min_holdout_positives=30),
)

HEADS_BY_NAME: dict[str, Head] = {head.name: head for head in HEADS}
