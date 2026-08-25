"""Training examples at the scoring-moment grain.

One example = one report as one daily snapshot saw it. Its features are that snapshot's
report-state columns (plus `age_hours`, the report's age at the snapshot), and its label is
whether the head's outcome happened within the head's horizon: the label is 0 on the snapshot row
and read from the snapshot `horizon_days` later. That is the serving situation — a report gets
scored, then users see it — replayed over the daily snapshots, and it measured better than one
row per report on the engagement heads (skill issue 13). Once the scoring sweep's append-only
score log has accrued it becomes this table's source; the snapshots are the bootstrap.

Rows of one report are near-duplicates, so the holdout is cut BY REPORT (report_created_at),
never by row. Label-only rows (EU reports, hard-deleted rows) carry no state and are skipped.
"""

import datetime
from collections.abc import Mapping

import pandas as pd

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import FEATURE_NAMES, feature_frame
from products.signals.dags.inbox_ranking.training.heads import Head

# Report-state columns an example carries, besides the features. `report_age_hours` is the
# snapshot's own clock and becomes the `age_hours` feature.
STATE_COLUMNS = (
    "report_created_at",
    "report_age_hours",
    "signal_count",
    "total_weight",
    "run_count",
    "title_chars",
    "summary_chars",
    "priority",
    "actionability",
)
EXAMPLE_COLUMNS = ("head", "report_id", "snapshot_date", "report_created_at", *FEATURE_NAMES, "label")


@frozen
class Snapshot:
    """One day's report-state and labels, both indexed by report_id."""

    date: datetime.date
    state: pd.DataFrame
    labels: pd.DataFrame


def build_examples(snapshots: Mapping[datetime.date, Snapshot], head: Head) -> pd.DataFrame:
    """Every (report, snapshot) scoring moment for `head` whose label can be read, as one frame
    with EXAMPLE_COLUMNS. Snapshots whose `horizon_days`-later snapshot is missing contribute no
    examples (the label is unknowable), so a gap in the partitions simply thins the data."""
    frames: list[pd.DataFrame] = []
    for date in sorted(snapshots):
        later = snapshots.get(date + datetime.timedelta(days=head.horizon_days))
        if later is None:
            continue
        now = snapshots[date]
        ids = now.state.index.intersection(now.labels.index).intersection(later.labels.index)
        if len(ids) == 0:
            continue
        state, labels_now, labels_later = now.state.loc[ids], now.labels.loc[ids], later.labels.loc[ids]
        # The cohort reads the later snapshot on purpose. The sweep scores a report before users see
        # it, so the impression that puts a report in the cohort usually lands after `now`. A cohort
        # read at `now` would drop those pre-impression scoring moments, which are the serving case.
        keep = head.cohort(labels_later) & ~head.label(labels_now) & state["signal_count"].notna()
        if not keep.any():
            continue
        rows = state.loc[keep, list(STATE_COLUMNS)].copy()
        rows["age_hours"] = rows.pop("report_age_hours").astype(float)
        features = feature_frame(rows)
        examples = pd.DataFrame(
            {
                "head": head.name,
                "report_id": rows.index.to_numpy(),
                "snapshot_date": date,
                "report_created_at": pd.to_datetime(rows["report_created_at"], utc=True).to_numpy(),
            }
        )
        for name in FEATURE_NAMES:
            examples[name] = features[name].to_numpy()
        examples["label"] = head.label(labels_later.loc[keep]).astype(int).to_numpy()
        frames.append(examples)
    if not frames:
        return pd.DataFrame(columns=list(EXAMPLE_COLUMNS))
    return pd.concat(frames, ignore_index=True)[list(EXAMPLE_COLUMNS)]


def holdout_mask(examples: pd.DataFrame, holdout_days: int) -> pd.Series:
    """True for every row of the reports created in the last `holdout_days` of the example set.
    Cut by report so a report's snapshot rows never straddle train and holdout."""
    created = pd.to_datetime(examples["report_created_at"], utc=True)
    if created.empty:
        return pd.Series(False, index=examples.index)
    cutoff = created.max() - pd.Timedelta(days=holdout_days)
    return created >= cutoff
