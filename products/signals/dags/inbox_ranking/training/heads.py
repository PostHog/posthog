"""The outcome heads the v0 ranking model predicts.

Each head is a cohort (which reports are scoreable examples), a binary label, and a horizon: the
label is "the outcome happened within `horizon_days` of the scoring moment", evaluated from the
cumulative label columns the dataset dag snapshots. Cohort and label are vectorized over a frame
of `inbox_report_labels` columns, so the same definitions read the snapshot at scoring time (label
must still be 0) and the snapshot `horizon_days` later (the label). The report's birth day is the
exception: it has no earlier scoring moment, so an outcome already visible there is a future
positive for that moment rather than an outcome of an earlier one, and the label may already be 1.

Every head reads the `everyone` cohort, so each `p_<head>` is a probability over the
same reports and the heads can be compared and combined. Impressions are not a label gate: only the
cloud inbox list emits them, and a report reached from Slack, the desktop app or MCP often has none.
The dataset keeps them for position bias.

`action` counts intent from any surface: the inbox UI, external coding agents over MCP, the CLI,
Slack and the desktop app. A thumbs up on the report counts too, and a thumbs down does not.
Self-driving's own `task` and `system` writes are excluded, because they are internal operational
work and not a person acting on the report.

Only the heads the inbox reads are trained: `open`, `action` and `fixed` (`HeadRanker` in
`products/signals/backend/ranking/inbox_sort.py`). The dataset dag still snapshots the label columns
of other outcomes, so a head can come back without a labels backfill.
"""

from collections.abc import Callable

import pandas as pd

from posthog.dataclasses import frozen


def _count(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].fillna(0).astype(int) if column in frame else pd.Series(0, index=frame.index)


def everyone(frame: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=frame.index)


def opened(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "open_count") > 0


# Intent actions from the inbox UI (`Inbox report action` events).
UI_ACTION_COLUMNS = (
    "create_pr_click_count",
    "implement_click_count",
    "copy_prompt_count",
    "discuss_count",
    "open_pr_click_count",
    "view_diff_count",
    "reviewer_add_count",
    "reviewer_remove_count",
    "restore_count",
)
# Intent actions recorded server-side, so they also cover the surfaces that emit no UI event. The
# artefact counts already exclude `task` and `system` writes (`HUMAN_ACTOR_KINDS`).
SERVER_ACTION_COLUMNS = (
    "claim_count",
    "linked_pr_count",
    "note_count",
    "slack_discussion_count",
    "reasoned_resolution_count",
)
# A thumbs up says a person found the report useful, often without any other action on it. It stays
# out of `UI_ACTION_COLUMNS`, because the `action` project vector reads only the `Inbox report
# action` stream. A thumbs down is a negative judgment, not intent, so it is not a label column.
FEEDBACK_ACTION_COLUMNS = ("feedback_positive_count",)
ACTION_LABEL_COLUMNS = UI_ACTION_COLUMNS + SERVER_ACTION_COLUMNS + FEEDBACK_ACTION_COLUMNS


def acted(frame: pd.DataFrame) -> pd.Series:
    any_action = pd.Series(False, index=frame.index)
    for column in ACTION_LABEL_COLUMNS:
        any_action |= _count(frame, column) > 0
    return any_action


def fixed(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "fixed_count") > 0


@frozen
class Head:
    name: str
    cohort: Callable[[pd.DataFrame], pd.Series]
    label: Callable[[pd.DataFrame], pd.Series]
    horizon_days: int
    # Below this many positives in the holdout the head's AUC is noise; the promotion gate ignores it.
    min_holdout_positives: int
    # Cumulative count columns the label reads. A scoring pair whose snapshot is missing one of these
    # cannot tell "outcome not yet observed" from "column absent", so the example builder skips it.
    # Empty when the label tolerates a missing column on its own.
    label_columns: tuple[str, ...] = ()
    # The label comes from the status-change stream, whose tenant provenance the dataset dag
    # cross-checks; rows that fail that check are unusable for this head.
    status_labels: bool = False


HEADS: tuple[Head, ...] = (
    # Which reports got opened by anyone? Cohort is every report: opens from a deeplink, the desktop
    # app or any other surface count, and those often have no list impression. Many opens land after
    # the first few days, so 7 days labels fewer late opens as negatives than 3 did.
    Head(name="open", cohort=everyone, label=opened, horizon_days=7, min_holdout_positives=50),
    # Which reports did someone act on, from any surface? The cohort is everyone, because a report
    # worked from Slack, the desktop app or an agent was often never impressed in the cloud list.
    # The label reads the status stream (a reasoned resolve), so it needs the provenance check.
    # Many actions land in the second week, so 14 days labels fewer late actions as negatives than 7 did.
    Head(
        name="action",
        cohort=everyone,
        label=acted,
        horizon_days=14,
        min_holdout_positives=30,
        label_columns=ACTION_LABEL_COLUMNS,
        status_labels=True,
    ),
    # Which reports flagged a real problem that then got fixed, by anyone and on any surface? Reads
    # only the status stream: a tracked PR merge, a hand-marked fix, or a dismissal as already
    # fixed all count. A one-click resolve counts after its grace window (`STATUS_SQL`). Fixes marked
    # by hand arrive about two weeks after birth and many land later, so 30 days labels fewer late
    # fixes as negatives than 21 did.
    Head(
        name="fixed",
        cohort=everyone,
        label=fixed,
        horizon_days=30,
        min_holdout_positives=30,
        label_columns=("fixed_count",),
        status_labels=True,
    ),
)

HEADS_BY_NAME: dict[str, Head] = {head.name: head for head in HEADS}
# Heads that share a horizon are labeled from the same later snapshot, so a reader that walks the
# horizons touches each snapshot once instead of once per head.
HEADS_BY_HORIZON: dict[int, tuple[Head, ...]] = {
    horizon: tuple(head for head in HEADS if head.horizon_days == horizon)
    for horizon in sorted({head.horizon_days for head in HEADS})
}
