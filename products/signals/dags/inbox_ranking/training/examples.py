"""Training examples at the grain the feature set asks for.

The default grain is a scoring moment: one example = one report as one daily snapshot saw it.
Its features are that snapshot's report-state columns (plus `age_hours`, the report's age at the
snapshot), and its label is whether the head's outcome happened within the head's horizon: the
label is 0 on the snapshot row and read from the snapshot `horizon_days` later. That is the serving
situation — a report gets scored, then users see it — replayed over the daily snapshots, and it
measured better than one row per report on the engagement heads (skill issue 13). Once the scoring
sweep's append-only score log has accrued it becomes this table's source; the snapshots are the
bootstrap.

Rows of one report are near-duplicates, so the holdout is cut BY REPORT (report_created_at),
never by row. Label-only rows (EU reports, hard-deleted rows) carry no state and are skipped.
A snapshot is assembled over the state spine (`assemble_snapshot`): a report with no label event
gets LABEL_DEFAULTS, so never-engaged reports are negatives rather than absent.

A wide set cannot afford that many rows, so a set may ask for the report grain instead (one
example per report, at its first usable scoring moment of the window) and cap the rows one head
keeps. Both knobs live on the `FeatureSet`, because the examples object is per set.
"""

import datetime
from collections.abc import Mapping

import pandas as pd

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import NO_EXTRAS, REPORT_GRAIN, Extras, FeatureSet
from products.signals.dags.inbox_ranking.common import snapshot_bounds
from products.signals.dags.inbox_ranking.dataset.dag import label_provenance_ok
from products.signals.dags.inbox_ranking.dataset.queries import LABEL_DEFAULTS
from products.signals.dags.inbox_ranking.training.heads import Head

# Report-state columns every example needs, whatever the feature set: the report's creation time
# (the holdout is cut on it), its age at the snapshot (`report_age_hours`, which becomes the
# `age_hours` every set may read), and `signal_count`, which marks a row that carries state at all.
BASE_STATE_COLUMNS = ("report_created_at", "report_age_hours", "signal_count")
# Inputs of the label provenance cross-check, read next to the features and labels.
PROVENANCE_STATE_COLUMNS = ("report_team_id", "status", "pg_updated_at")
PROVENANCE_LABEL_COLUMNS = ("latest_status_event", "status_event_team_id")


# A forward run stamps features_observed_at a few hours after the snapshot end. Anything read later
# than this is a backfill that carries current Postgres state, not the state as of the snapshot.
STATE_LAG_LIMIT = datetime.timedelta(days=2)

# Fixed, so a re-run of a partition keeps the same rows under a row budget and two candidates of the
# same day are fit on one example set.
EXAMPLE_SAMPLE_SEED = 0


def state_columns(feature_set: FeatureSet) -> tuple[str, ...]:
    """The report-state columns to read for `feature_set`: the base ones plus its own."""
    return (*BASE_STATE_COLUMNS, *(name for name in feature_set.state_columns if name not in BASE_STATE_COLUMNS))


# The moment spine, before any feature set's columns are added to it.
MOMENT_COLUMNS = ("head", "report_id", "snapshot_date", "report_created_at", "label")


def example_columns(feature_set: FeatureSet) -> tuple[str, ...]:
    """The examples Parquet columns for `feature_set`. One object per set, because two sets carry
    different feature columns."""
    return ("head", "report_id", "snapshot_date", "report_created_at", *feature_set.feature_names, "label")


def state_rows(state: pd.DataFrame, feature_set: FeatureSet) -> pd.DataFrame:
    """The `feature_set` slice of `state`, with the snapshot's `report_age_hours` as `age_hours`.

    Both the example builder and the unseen scorer go through this, so a report scored on the day
    it is born sees the vector it would have seen as a training example.
    """
    rows = state[list(state_columns(feature_set))].copy()
    rows["age_hours"] = rows.pop("report_age_hours").astype(float)
    return rows


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


def build_examples(
    snapshots: Mapping[datetime.date, Snapshot],
    head: Head,
    feature_set: FeatureSet,
    extras: Extras = NO_EXTRAS,
) -> pd.DataFrame:
    """Every scoring moment for `head` that `feature_set` asks for, as one frame with its example
    columns. Snapshots whose `horizon_days`-later snapshot is missing contribute no examples (the
    label is unknowable), so a gap in the partitions thins the data.

    The moments are chosen first and the features built second, so a set under a row budget builds
    1536 columns for the rows it keeps rather than for every row it then throws away.
    """
    moments = example_moments(snapshots, head, feature_set, extras)
    kept = cap_examples(moments, feature_set.max_examples_per_head)
    return _with_features(kept, snapshots, feature_set, extras)


def example_moments(
    snapshots: Mapping[datetime.date, Snapshot],
    head: Head,
    feature_set: FeatureSet,
    extras: Extras,
) -> pd.DataFrame:
    """The (report, snapshot) moments that are examples for `head`, with their labels and no
    features. One row per moment at the scoring-moment grain; at the report grain, only the first
    snapshot of the window where a report is a usable moment."""
    frames: list[pd.DataFrame] = []
    covered: set[object] = set()
    for date in sorted(snapshots):
        later = snapshots.get(date + datetime.timedelta(days=head.horizon_days))
        if later is None:
            continue
        now = snapshots[date]
        # A label column that is absent from a snapshot reads as zero, so a cumulative count present
        # only in the later snapshot (a column that entered the schema mid-window) would pass the
        # "not yet observed at now" guard below and mint an outcome from before `now` as a future
        # positive. Skip the pair when the head's label cannot be read from both snapshots.
        if any(column not in now.labels or column not in later.labels for column in head.label_columns):
            continue
        ids = now.state.index.intersection(now.labels.index).intersection(later.labels.index)
        if len(ids) == 0:
            continue
        state, labels_now, labels_later = now.state.loc[ids], now.labels.loc[ids], later.labels.loc[ids]
        _, snapshot_end = snapshot_bounds(date.isoformat())
        # The cohort reads the later snapshot on purpose. The sweep scores a report before users see
        # it, so the impression that puts a report in the cohort usually lands after `now`. A cohort
        # read at `now` would drop those pre-impression scoring moments, which are the serving case.
        keep = head.cohort(labels_later) & ~head.label(labels_now) & state["signal_count"].notna()
        keep &= point_in_time_mask(state, date)
        if head.status_labels:
            keep &= _flag_or_true(labels_now, "label_provenance_ok") & _flag_or_true(
                labels_later, "label_provenance_ok"
            )
        # A set whose side input has no row for a report, or only a value that landed after this
        # snapshot, cannot build the vector this moment had, so the report is not a moment here. At
        # the report grain the report then takes its example on the first snapshot where it can.
        keep &= feature_set.buildable(state, extras, as_of=snapshot_end)
        if feature_set.example_grain == REPORT_GRAIN:
            keep &= ~state.index.isin(covered)
        if not keep.any():
            continue
        kept_ids = state.index[keep.to_numpy()]
        covered.update(kept_ids)
        frames.append(
            pd.DataFrame(
                {
                    "head": head.name,
                    "report_id": kept_ids.to_numpy(),
                    "snapshot_date": date,
                    "report_created_at": pd.to_datetime(state.loc[kept_ids, "report_created_at"], utc=True).to_numpy(),
                    "label": head.label(labels_later.loc[kept_ids]).astype(int).to_numpy(),
                }
            )
        )
    if not frames:
        return pd.DataFrame(columns=list(MOMENT_COLUMNS))
    return pd.concat(frames, ignore_index=True)


def cap_examples(moments: pd.DataFrame, limit: int | None) -> pd.DataFrame:
    """`moments` within `limit` rows, keeping every positive and a seeded sample of the negatives.

    A row budget is how a wide set stays inside one partition's object and the training job's
    runtime. Positives are the scarce side of every head here and AUC is rank-based, so spending
    the budget on them costs the base rate the scores are calibrated to rather than the ranking read
    the family exists for. Positives are kept whole even past the budget: a head with that many
    positives is not the case the budget is for.
    """
    if limit is None or len(moments) <= limit:
        return moments
    positives = moments[moments["label"] == 1]
    negatives = moments[moments["label"] != 1]
    room = max(limit - len(positives), 0)
    sampled = negatives.sample(n=min(room, len(negatives)), random_state=EXAMPLE_SAMPLE_SEED)
    return pd.concat([positives, sampled]).sort_index().reset_index(drop=True)


def _with_features(
    moments: pd.DataFrame, snapshots: Mapping[datetime.date, Snapshot], feature_set: FeatureSet, extras: Extras
) -> pd.DataFrame:
    """`moments` with `feature_set`'s columns, built from the state of the snapshot each moment
    belongs to, so a moment carries the features that snapshot would have scored it with."""
    columns = list(example_columns(feature_set))
    if moments.empty:
        return pd.DataFrame(columns=columns)
    frames: list[pd.DataFrame] = []
    for date, group in moments.groupby("snapshot_date", sort=True):
        _, snapshot_end = snapshot_bounds(date.isoformat())
        rows = state_rows(snapshots[date].state.loc[group["report_id"]], feature_set)
        features = feature_set.build_matrix(rows, extras, as_of=snapshot_end)
        examples = group.reset_index(drop=True)
        for name in feature_set.feature_names:
            examples[name] = features[name].to_numpy()
        frames.append(examples)
    return pd.concat(frames, ignore_index=True)[columns]


def holdout_mask(examples: pd.DataFrame, holdout_days: int) -> pd.Series:
    """True for every row of the reports created in the last `holdout_days` of the example set.
    Cut by report so a report's snapshot rows never straddle train and holdout."""
    created = pd.to_datetime(examples["report_created_at"], utc=True)
    if created.empty:
        return pd.Series(False, index=examples.index)
    cutoff = created.max() - pd.Timedelta(days=holdout_days)
    return created >= cutoff
