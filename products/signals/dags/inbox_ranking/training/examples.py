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
A snapshot is assembled over the state spine (`assemble_snapshot`): a report with no label event
gets LABEL_DEFAULTS, so never-engaged reports are negatives rather than absent.
"""

import datetime
from collections.abc import Mapping

import pandas as pd

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import FEATURE_NAMES, feature_frame
from products.signals.dags.inbox_ranking.common import snapshot_bounds
from products.signals.dags.inbox_ranking.dataset.dag import label_provenance_ok
from products.signals.dags.inbox_ranking.dataset.queries import LABEL_DEFAULTS
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
# Inputs of the label provenance cross-check, read next to the features and labels.
PROVENANCE_STATE_COLUMNS = ("report_team_id", "status", "pg_updated_at")
PROVENANCE_LABEL_COLUMNS = ("latest_status_event", "status_event_team_id")
EXAMPLE_COLUMNS = ("head", "report_id", "snapshot_date", "report_created_at", *FEATURE_NAMES, "label")

# A forward run stamps features_observed_at a few hours after the snapshot end. Anything read later
# than this is a backfill that carries current Postgres state, not the state as of the snapshot.
STATE_LAG_LIMIT = datetime.timedelta(days=2)


@frozen
class Snapshot:
    """One day's report-state and labels, both indexed by report_id."""

    date: datetime.date
    state: pd.DataFrame
    labels: pd.DataFrame


def _none_if_missing(value: object) -> object:
    return None if value is None or value is pd.NaT or (isinstance(value, float) and pd.isna(value)) else value


def assemble_snapshot(date: datetime.date, state: pd.DataFrame, labels: pd.DataFrame) -> Snapshot:
    """Align `labels` to the state spine: every state report gets a label row (LABEL_DEFAULTS for
    reports that had no event) and a `label_provenance_ok` column from the dataset dag's
    cross-check when the provenance inputs are present. Label-only rows stay: a report deleted
    before a later snapshot keeps its horizon label there, while `build_examples` skips them as
    scoring moments because they carry no state."""
    aligned = labels.reindex(state.index.union(labels.index))
    state = state.reindex(aligned.index)
    for column, default in LABEL_DEFAULTS.items():
        if column in aligned and default is not None:
            aligned[column] = aligned[column].fillna(default)
    has_inputs = all(column in state for column in PROVENANCE_STATE_COLUMNS) and all(
        column in aligned for column in PROVENANCE_LABEL_COLUMNS
    )
    if has_inputs:
        _, snapshot_end = snapshot_bounds(date.isoformat())
        aligned["label_provenance_ok"] = [
            label_provenance_ok(
                _none_if_missing(status),  # type: ignore[arg-type]
                _none_if_missing(updated_at),  # type: ignore[arg-type]
                _none_if_missing(latest_event),  # type: ignore[arg-type]
                report_team_id=_none_if_missing(team_id),  # type: ignore[arg-type]
                status_event_team_id=_none_if_missing(event_team_id),  # type: ignore[arg-type]
                snapshot_end=snapshot_end,
            )
            for status, updated_at, latest_event, team_id, event_team_id in zip(
                state["status"],
                state["pg_updated_at"],
                aligned["latest_status_event"],
                state["report_team_id"],
                aligned["status_event_team_id"],
                strict=True,
            )
        ]
    return Snapshot(date=date, state=state, labels=aligned)


def point_in_time_mask(state: pd.DataFrame, date: datetime.date) -> pd.Series:
    """True for rows whose Postgres state was read close enough to the snapshot day to stand for
    the state as of that day. Rows without the stamp are kept."""
    if "features_observed_at" not in state:
        return pd.Series(True, index=state.index)
    _, snapshot_end = snapshot_bounds(date.isoformat())
    observed = pd.to_datetime(state["features_observed_at"], utc=True)
    return observed.isna() | (observed <= snapshot_end + STATE_LAG_LIMIT)


def _flag_or_true(labels: pd.DataFrame, column: str) -> pd.Series:
    return labels[column].fillna(False).astype(bool) if column in labels else pd.Series(True, index=labels.index)


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
        keep &= point_in_time_mask(state, date)
        if head.status_labels:
            keep &= _flag_or_true(labels_now, "label_provenance_ok") & _flag_or_true(
                labels_later, "label_provenance_ok"
            )
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
