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
The dataset keeps them for position bias and the shadow grades.

`action` counts intent from any surface: the inbox UI, external coding agents over MCP, the CLI,
Slack and the desktop app. Self-driving's own `task` and `system` writes are excluded, because
they are internal operational work and not a person acting on the report.

Mirrors the workspace `heads.py` (random-dev-internal, `inbox-ranking/`). Nine heads are dense
enough to read on the holdout. `thumbs_up` and `reviewer_fix` are the explicit human-feedback pair:
they are rare, so they are carried for the pooled newborn grade and as scorer inputs rather than
for a holdout AUC. The rest stay workspace-only.
"""

from collections.abc import Callable

import pandas as pd

from posthog.dataclasses import frozen

from products.signals.dags.inbox_ranking.common import WRONG_DISMISSAL_REASONS


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
ACTION_LABEL_COLUMNS = UI_ACTION_COLUMNS + SERVER_ACTION_COLUMNS


def acted(frame: pd.DataFrame) -> pd.Series:
    any_action = pd.Series(False, index=frame.index)
    for column in ACTION_LABEL_COLUMNS:
        any_action |= _count(frame, column) > 0
    return any_action


def dismissed_as_wrong(frame: pd.DataFrame) -> pd.Series:
    if "wrong_dismissal_count" in frame:
        return _count(frame, "wrong_dismissal_count") > 0
    # Partitions written before the cumulative count existed carry only the latest-wins reason,
    # which a later restore or re-dismissal can overwrite.
    if "dismissal_reason" not in frame:
        return pd.Series(False, index=frame.index)
    return frame["dismissal_reason"].isin(WRONG_DISMISSAL_REASONS)


def fixed(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "fixed_count") > 0


def dismissed_as_low_value(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "lowvalue_dismissal_count") > 0


def pr_created(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "pr_created_count") > 0


def pr_merged(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "pr_merged_count") > 0


def discussed(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "discuss_count") > 0


def refunded(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "refund_count") > 0


def thumbed_up(frame: pd.DataFrame) -> pd.Series:
    return _count(frame, "feedback_positive_count") > 0


def reviewer_fixed(frame: pd.DataFrame) -> pd.Series:
    return (_count(frame, "reviewer_add_count") + _count(frame, "reviewer_remove_count")) > 0


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
    # Empty when the label tolerates a missing column on its own (dismiss_wrong falls back to a reason).
    label_columns: tuple[str, ...] = ()
    # The label comes from the status-change stream, whose tenant provenance the dataset dag
    # cross-checks; rows that fail that check are unusable for this head.
    status_labels: bool = False


HEADS: tuple[Head, ...] = (
    # Which reports got opened by anyone? Cohort is every report: opens from a deeplink, the desktop
    # app or any other surface count, and those often have no list impression.
    Head(name="open", cohort=everyone, label=opened, horizon_days=3, min_holdout_positives=50),
    # Which reports did someone act on, from any surface? The cohort is everyone, because a report
    # worked from Slack, the desktop app or an agent was often never impressed in the cloud list.
    # The label reads the status stream (a reasoned resolve), so it needs the provenance check.
    Head(
        name="action",
        cohort=everyone,
        label=acted,
        horizon_days=7,
        min_holdout_positives=30,
        label_columns=ACTION_LABEL_COLUMNS,
        status_labels=True,
    ),
    # Which reports were dismissed as wrong / unclear / intentional - the precision-failure negative.
    # already_fixed and wontfix_irrelevant are deliberately not here. Cohort is every report: a
    # dismissal from another surface often has no list impression. A dismissal with a reason lands
    # late, so 21 days labels fewer late dismissals as negatives than 14 did.
    Head(
        name="dismiss_wrong",
        cohort=everyone,
        label=dismissed_as_wrong,
        horizon_days=21,
        min_holdout_positives=30,
        status_labels=True,
    ),
    # Which reports get a PR at all? Cohort is every report the sweep would score.
    Head(name="pr_created", cohort=everyone, label=pr_created, horizon_days=7, min_holdout_positives=30),
    # Which reports end up with a merged PR? The cohort is everyone, so the label carries the whole
    # report-to-merge path rather than conditioning on a PR that does not exist yet at birth.
    Head(
        name="pr_merged",
        cohort=everyone,
        label=pr_merged,
        horizon_days=14,
        min_holdout_positives=30,
        label_columns=("pr_merged_count",),
    ),
    # Which reports flagged a real problem that then got fixed, by anyone and on any surface? Reads
    # only the status stream: a tracked PR merge, a hand-marked fix, or a dismissal as already
    # fixed all count. 21 days because fixes marked by hand arrive about two weeks after birth.
    Head(
        name="fixed",
        cohort=everyone,
        label=fixed,
        horizon_days=21,
        min_holdout_positives=30,
        label_columns=("fixed_count",),
        status_labels=True,
    ),
    # Which reports drew a discuss? Cohort is every report: a discuss from Slack, the desktop app or
    # MCP often has no list impression. A subset of the action head, which is fine - each head trains
    # independently.
    Head(
        name="discuss",
        cohort=everyone,
        label=discussed,
        horizon_days=7,
        min_holdout_positives=30,
        label_columns=("discuss_count",),
    ),
    # Which reports led to a refund? Cohort is everyone, not pr_created: a minority of refunded reports
    # carry no pr_created event, since the refund stream is minted server-side on its own event.
    # refund_count entered the labels schema after the epoch, so pre-existing partitions lack it; the
    # label_columns guard keeps its cumulative count from leaking stale refunds as future positives.
    Head(
        name="refund",
        cohort=everyone,
        label=refunded,
        horizon_days=14,
        min_holdout_positives=20,
        label_columns=("refund_count",),
    ),
    # Which reports drew a thumbs up at the end of the body? Cohort is every report, so the
    # probability is on the same population as the other heads. Every thumbed report was opened,
    # so this loses no positives and only adds negatives. The label is rare, so the holdout AUC
    # stays noise for weeks and the pooled newborn grade is the read.
    Head(
        name="thumbs_up",
        cohort=everyone,
        label=thumbed_up,
        horizon_days=7,
        min_holdout_positives=10,
        label_columns=("feedback_positive_count",),
    ),
    # Which reports had their suggested reviewers corrected? Cohort is every report: a correction
    # from another surface often has no list impression. An add and a remove are one label: a
    # removal alone is housekeeping that usually follows a PR, while the pair reads as "a person
    # corrected the reviewers". Slow to land, hence the 14 days.
    Head(
        name="reviewer_fix",
        cohort=everyone,
        label=reviewer_fixed,
        horizon_days=14,
        min_holdout_positives=20,
        label_columns=("reviewer_add_count", "reviewer_remove_count"),
    ),
    # Which reports get dismissed as real but not worth fixing - the relevance-failure negative.
    # dismiss_wrong says the report was wrong; this head says it was right but not worth anyone's
    # time. Cohort is everyone, because agents over MCP dismiss reports that no list ever showed.
    # Many of these dismissals land after 14 days, hence the 21 days.
    Head(
        name="dismiss_lowvalue",
        cohort=everyone,
        label=dismissed_as_low_value,
        horizon_days=21,
        min_holdout_positives=30,
        label_columns=("lowvalue_dismissal_count",),
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
