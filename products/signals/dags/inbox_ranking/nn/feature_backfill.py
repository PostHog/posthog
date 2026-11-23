"""The training side of the ML feature backfill: fill an experiment's late feature groups from one
frozen `inbox_report_feature_backfill` batch, and record how ready each head's rows are.

The `nn` examples carry each late group's state columns as their birth-day snapshot recorded them,
and a snapshot written before the columns existed leaves them null. A family with a
`feature_backfill` selection keeps every value its snapshot recorded, and takes the batch's value
only for a row whose snapshot recorded none, only from a batch row of the same report, birth day and
team, and only when that value's provenance is one the selection accepts. Any other row keeps its
unknown value, which the set reads as not recorded and never as zero. The provenance stays out of
the inputs: it is counted in the readiness block, and the network never reads it.

A set that reads the scored facts (`ReportEmbeddingsPriorityScoredFactsFeatureSet`) takes every value
of a row that has a scored-facts row at its moment from that row, before its snapshot and before the
batch. The readiness block counts such a row's late groups as `scored_facts`, and counts per head how
many rows read the scored facts and how many read the snapshot.

The labels, holdout flags and rows stay those of the examples object, apart from the rows of a team
that no longer allows AI training. Those are dropped for both arms of the comparison, because a
batch written before an opt-out keeps the team's rows.
"""

import datetime
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import (
    ALREADY_ADDRESSED_COLUMN,
    CONTENT_COLUMNS,
    Extras,
    FeatureSet,
    ReportEmbeddingsPriorityScoredFactsFeatureSet,
)
from products.signals.dags.inbox_ranking.common import read_parquet_if_exists, snapshot_bounds
from products.signals.dags.inbox_ranking.dataset.feature_backfill import (
    ALREADY_ADDRESSED_GROUP,
    CONTENT_GROUP,
    FEATURE_BACKFILL_SCHEMA_VERSION,
    Provenance,
    feature_backfill_object_key,
)
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable
from products.signals.dags.inbox_ranking.nn.examples import NN_HEAD_NAMES, subset
from products.signals.dags.inbox_ranking.training.families import FeatureBackfillSelection

# The state columns behind each late feature group of the ML-features set.
LATE_GROUP_STATE_COLUMNS: Mapping[str, tuple[str, ...]] = {
    CONTENT_GROUP: CONTENT_COLUMNS,
    ALREADY_ADDRESSED_GROUP: (ALREADY_ADDRESSED_COLUMN,),
}
# Where a row's late group value came from, beside the accepted `Provenance` values.
SNAPSHOT_SOURCE = "snapshot"
SCORED_FACTS_SOURCE = "scored_facts"
NOT_RECORDED_SOURCE = "not_recorded"
NOT_ACCEPTED_SUFFIX = "_not_accepted"

_BATCH_COLUMNS = [
    "snapshot_date",
    "report_id",
    "report_team_id",
    "backfill_schema_version",
    *CONTENT_COLUMNS,
    f"{CONTENT_GROUP}_provenance",
    ALREADY_ADDRESSED_COLUMN,
    f"{ALREADY_ADDRESSED_GROUP}_provenance",
]


@frozen
class BackfillBatchRows:
    selection: FeatureBackfillSelection
    rows: Sequence[Mapping[str, Any]]
    # The birth days of the examples, and those the batch holds an object for.
    birth_days: int
    days_read: int


@frozen
class BackfilledExamples:
    table: ExampleTable
    # Per late group, one source per row of `table`.
    sources: Mapping[str, np.ndarray]
    excluded_no_training_consent_rows: int


def birth_day(value: object) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    raise TypeError(f"{value!r} is not a snapshot day")


def read_backfill_batch(
    client, bucket: str, prefix: str, selection: FeatureBackfillSelection, days: Collection[datetime.date]
) -> BackfillBatchRows:
    """The rows `selection`'s batch holds for `days`. A day without an object adds none. A day
    written under another schema version raises, because the family's recipe names the version."""
    rows: list[dict[str, Any]] = []
    days_read = 0
    for day in sorted(days):
        table = read_parquet_if_exists(
            client, bucket, feature_backfill_object_key(prefix, selection.batch_id, day.isoformat()), _BATCH_COLUMNS
        )
        if table is None:
            continue
        days_read += 1
        versions = set(table.column("backfill_schema_version").to_pylist())
        if versions - {FEATURE_BACKFILL_SCHEMA_VERSION}:
            raise ValueError(
                f"feature backfill batch {selection.batch_id} holds dt={day.isoformat()} under schema "
                f"{sorted(versions, key=str)}; this build reads v{FEATURE_BACKFILL_SCHEMA_VERSION}"
            )
        rows.extend(table.to_pylist())
    return BackfillBatchRows(selection=selection, rows=rows, birth_days=len(days), days_read=days_read)


def _recorded(values: Iterable[object]) -> bool:
    return all(value is not None and not pd.isna(value) for value in values)


def late_group_sources(rows: pd.DataFrame, groups: Iterable[str]) -> dict[str, np.ndarray]:
    """Per group, `snapshot` for each row whose own snapshot recorded every column of the group, and
    `not_recorded` for the others."""
    sources: dict[str, np.ndarray] = {}
    for group in groups:
        columns = LATE_GROUP_STATE_COLUMNS[group]
        recorded = np.ones(len(rows), dtype=bool)
        for column in columns:
            recorded &= rows[column].notna().to_numpy() if column in rows else False
        sources[group] = np.where(recorded, SNAPSHOT_SOURCE, NOT_RECORDED_SOURCE).astype(object)
    return sources


def _batch_source(batch_row: Mapping[str, Any], group: str, accepted: Collection[str]) -> str:
    provenance = batch_row[f"{group}_provenance"]
    if provenance == Provenance.MISSING or not _recorded(batch_row[name] for name in LATE_GROUP_STATE_COLUMNS[group]):
        return Provenance.MISSING.value
    return provenance if provenance in accepted else f"{provenance}{NOT_ACCEPTED_SUFFIX}"


def fill_from_backfill(
    table: ExampleTable, batch: BackfillBatchRows, groups: Iterable[str], consent_team_ids: Collection[int]
) -> BackfilledExamples:
    """`table` without the rows of teams outside `consent_team_ids`, with each of `groups` filled from
    `batch` on the rows whose snapshot did not record it."""
    consented = table.rows["report_team_id"].isin(consent_team_ids).to_numpy()
    table = subset(table, np.flatnonzero(consented))
    rows = table.rows.copy()
    by_key = {(str(row["report_id"]), birth_day(row["snapshot_date"])): row for row in batch.rows}
    keys = list(zip(rows["report_id"].astype(str), (birth_day(value) for value in rows["snapshot_date"])))
    teams = rows["report_team_id"].tolist()
    accepted = {provenance.value for provenance in batch.selection.provenances}
    sources = late_group_sources(rows, groups)
    for group, group_sources in sources.items():
        columns = LATE_GROUP_STATE_COLUMNS[group]
        values = {
            column: rows[column].astype(object).where(rows[column].notna(), None).tolist()
            if column in rows
            else [None] * len(rows)
            for column in columns
        }
        for position in np.flatnonzero(group_sources == NOT_RECORDED_SOURCE):
            batch_row = by_key.get(keys[position])
            if batch_row is None or batch_row["report_team_id"] != teams[position]:
                continue
            source = _batch_source(batch_row, group, accepted)
            group_sources[position] = source
            if source in accepted:
                for column in columns:
                    values[column][position] = batch_row[column]
        for column in columns:
            rows[column] = pd.Series(values[column], index=rows.index, dtype=object)
    return BackfilledExamples(
        table=ExampleTable(rows=rows, labels=table.labels, holdout=table.holdout, weights=table.weights),
        sources=sources,
        excluded_no_training_consent_rows=int((~consented).sum()),
    )


def scored_facts_rows(
    rows: pd.DataFrame, extras: Extras, feature_set: ReportEmbeddingsPriorityScoredFactsFeatureSet
) -> np.ndarray:
    """True for each row of `rows` that has a scored-facts row known at its moment, the end of its
    snapshot day, as `report_matrix` builds it. `rows` is positioned from zero."""
    scored = np.zeros(len(rows), dtype=bool)
    for day, group in rows.groupby("snapshot_date", sort=True):
        _, moment = snapshot_bounds(birth_day(day).isoformat())
        known = feature_set.scored_rows(pd.Index(group["report_id"]), extras, moment).index
        scored[group.index.to_numpy()] = group["report_id"].isin(known).to_numpy()
    return scored


def with_scored_facts_sources(sources: Mapping[str, np.ndarray], scored: np.ndarray) -> dict[str, np.ndarray]:
    """`sources` with each late group of a row in `scored` read from the scored facts."""
    return {group: np.where(scored, SCORED_FACTS_SOURCE, group_sources) for group, group_sources in sources.items()}


def late_group_fit_stats(
    reports: np.ndarray, fit_rows: np.ndarray, feature_set: FeatureSet
) -> dict[str, dict[str, Any]]:
    """Per late group, read from the report input before training zeroes any group: the share of the
    network's fit rows that carry it, which the zeroing gate reads, and how many of its columns take
    more than one value on those rows. A constant column is reported here, not refused."""
    position = {name: index for index, name in enumerate(feature_set.feature_names)}
    stats: dict[str, dict[str, Any]] = {}
    for group, names in feature_set.late_feature_groups.items():
        block = reports[fit_rows][:, [position[name] for name in names]]
        stats[group] = {
            "carried_share": float(np.any(block != 0, axis=1).mean()) if len(fit_rows) else 0.0,
            "columns": len(names),
            "varying_columns": int((block.min(axis=0) != block.max(axis=0)).sum()) if len(fit_rows) else 0,
        }
    return stats


def _days(table: ExampleTable, rows: np.ndarray) -> dict[str, str | None]:
    days = [birth_day(value) for value in table.rows["snapshot_date"].iloc[rows]]
    return {
        "first_day": min(days).isoformat() if days else None,
        "last_day": max(days).isoformat() if days else None,
    }


def _counts(values: np.ndarray, rows: np.ndarray) -> dict[str, int]:
    return dict(sorted(Counter(values[rows].tolist()).items()))


def _source_counts(sources: Mapping[str, np.ndarray], rows: np.ndarray) -> dict[str, dict[str, int]]:
    return {group: _counts(group_sources, rows) for group, group_sources in sources.items()}


def _facts_counts(facts_sources: np.ndarray | None, rows: np.ndarray) -> dict[str, Any]:
    return {} if facts_sources is None else {"facts_sources": _counts(facts_sources, rows)}


def readiness_block(
    table: ExampleTable,
    sources: Mapping[str, np.ndarray],
    fit_stats: Mapping[str, Mapping[str, Any]],
    zeroed_groups: Sequence[str],
    *,
    batch: BackfillBatchRows | None,
    excluded_no_training_consent_rows: int,
    facts_sources: np.ndarray | None = None,
) -> dict[str, Any]:
    """How ready a late-feature fit is: per head and split, its rows, positives, birth-day range and
    the source of each late group's values, and the same for the network's fit rows with the groups
    training read and zeroed. Each group's source counts add up to its rows. `facts_sources` holds,
    for a set that reads the scored facts, whether each row read them or its snapshot."""
    fit_rows = table.network_train_rows()
    heads: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(NN_HEAD_NAMES):
        # A head's train rows are the fit rows it has a label on. A row in another head's holdout is
        # in no fit, so it counts in neither split.
        splits = {
            "train": fit_rows[~np.isnan(table.labels[fit_rows, index])],
            "holdout": table.head_rows(index, holdout=True),
        }
        heads[name] = {
            split: {
                "rows": len(rows),
                "positives": int(np.nansum(table.labels[rows, index])),
                **_days(table, rows),
                "sources": _source_counts(sources, rows),
                **_facts_counts(facts_sources, rows),
            }
            for split, rows in splits.items()
        }
    return {
        "feature_backfill": (
            {
                "batch_id": batch.selection.batch_id,
                "provenances": [provenance.value for provenance in batch.selection.provenances],
                "approximate": batch.selection.approximate,
                "birth_days": batch.birth_days,
                "days_read": batch.days_read,
            }
            if batch is not None
            else None
        ),
        "excluded_no_training_consent_rows": excluded_no_training_consent_rows,
        "network_fit": {
            "rows": len(fit_rows),
            **_days(table, fit_rows),
            "sources": _source_counts(sources, fit_rows),
            **_facts_counts(facts_sources, fit_rows),
            "groups": {group: dict(stats) for group, stats in fit_stats.items()},
        },
        "heads": heads,
        "enabled_feature_groups": [group for group in fit_stats if group not in zeroed_groups],
        "zeroed_feature_groups": list(zeroed_groups),
    }
