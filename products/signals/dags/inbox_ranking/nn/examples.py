"""The `nn` family's examples and network inputs, without torch.

The examples are the prototype's (`multihead/prototype.py`): one row per report moment, with a label
and a holdout flag for each of `open`, `action` and `fixed`. Each head's moments come from
`example_moments` over the `report_embeddings` set and are capped by `cap_examples`, so every head's
cohort, horizon, row budget and holdout are the ones its `report_embeddings` champion is graded on.

The examples object holds the rows, labels and holdout flags only, and each row's `priority` as of
its own snapshot. One object serves both `nn` families. The vectors are rebuilt from the dt=D
embeddings and labels snapshots by each asset that reads the object: the report vectors carry 1536
floats per row and the project vectors four times that per (team, day), and both are a pure function
of those two snapshots.
"""

import json
import datetime
from collections.abc import Mapping

import numpy as np
import pandas as pd
import pyarrow as pa

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import PRIORITY_COLUMN, Extras, FeatureSet
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkInputs
from products.signals.dags.inbox_ranking.multihead.prototype import (
    FEATURE_SET,
    PROTOTYPE_HEADS,
    ExampleTable,
    example_table,
    project_context,
    report_matrix,
)
from products.signals.dags.inbox_ranking.training.examples import Snapshot, cap_examples, example_moments

NN_HEADS = PROTOTYPE_HEADS
NN_HEAD_NAMES = tuple(head.name for head in NN_HEADS)

_ROW_COLUMNS = ("report_id", "snapshot_date", "report_team_id")
# Parquet schema metadata key that carries each head's example window.
EXAMPLE_WINDOWS_METADATA_KEY = b"inbox_ranking_example_windows"


@frozen
class NNExamples:
    table: ExampleTable
    # Per head, the `example_window_start` and `example_cap_bound` the per-head families record.
    windows: Mapping[str, Mapping[str, object]]
    # Moments without a team. They have no project vectors, so the network cannot read them.
    rows_without_team: int = 0


def _window(moments: pd.DataFrame, kept: pd.DataFrame) -> dict[str, object]:
    days = pd.to_datetime(kept["report_created_at"], utc=True).dt.floor("D").dropna()
    return {
        "example_window_start": days.min().date().isoformat() if len(days) else None,
        "example_cap_bound": len(kept) < len(moments),
    }


def subset(table: ExampleTable, rows: np.ndarray) -> ExampleTable:
    """The rows `rows` of `table`, positioned from zero."""
    return ExampleTable(
        rows=table.rows.iloc[rows].reset_index(drop=True), labels=table.labels[rows], holdout=table.holdout[rows]
    )


def build_examples(snapshots: Mapping[datetime.date, Snapshot], extras: Extras, *, holdout_days: int) -> NNExamples:
    moments = {head.name: example_moments(snapshots, head, FEATURE_SET, extras) for head in NN_HEADS}
    kept = {name: cap_examples(frame, FEATURE_SET.max_examples_per_head) for name, frame in moments.items()}
    table = example_table(snapshots, extras, holdout_days=holdout_days, head_moments=kept)
    with_team = table.rows["report_team_id"].notna().to_numpy()
    return NNExamples(
        table=subset(table, np.flatnonzero(with_team)),
        windows={name: _window(moments[name], kept[name]) for name in NN_HEAD_NAMES},
        rows_without_team=int((~with_team).sum()),
    )


def examples_arrow(examples: NNExamples) -> pa.Table:
    """The examples as one Parquet-ready table: the row identity, then `<head>_label` (NaN where the
    head has no example) and `<head>_holdout` per head."""
    table = examples.table
    frame = table.rows[list(_ROW_COLUMNS)].copy()
    frame["report_id"] = frame["report_id"].astype(str)
    frame["report_team_id"] = frame["report_team_id"].astype("int64")
    for index, name in enumerate(NN_HEAD_NAMES):
        frame[f"{name}_label"] = table.labels[:, index].astype(np.float32)
        frame[f"{name}_holdout"] = table.holdout[:, index]
    arrow = pa.Table.from_pandas(frame, preserve_index=False)
    if PRIORITY_COLUMN in table.rows:
        # Typed explicitly: a day where no row has a judgment would otherwise write a null column.
        arrow = arrow.append_column(
            pa.field(PRIORITY_COLUMN, pa.string()), pa.array(table.rows[PRIORITY_COLUMN].tolist(), type=pa.string())
        )
    return arrow.replace_schema_metadata(
        {**(arrow.schema.metadata or {}), EXAMPLE_WINDOWS_METADATA_KEY: json.dumps(examples.windows).encode()}
    )


def examples_from_arrow(arrow: pa.Table) -> NNExamples:
    """The examples an `examples_arrow` table holds. An object written before the `priority` column
    existed gives rows without it, so a family that reads priority can tell and skip."""
    frame = arrow.to_pandas()
    row_columns = [*_ROW_COLUMNS, *([PRIORITY_COLUMN] if PRIORITY_COLUMN in frame else [])]
    rows = frame[row_columns].reset_index(drop=True)
    labels = np.column_stack([frame[f"{name}_label"].to_numpy(dtype=np.float32) for name in NN_HEAD_NAMES])
    holdout = np.column_stack([frame[f"{name}_holdout"].to_numpy(dtype=bool) for name in NN_HEAD_NAMES])
    raw = (arrow.schema.metadata or {}).get(EXAMPLE_WINDOWS_METADATA_KEY)
    return NNExamples(
        table=ExampleTable(
            rows=rows,
            labels=labels.reshape(len(rows), len(NN_HEAD_NAMES)),
            holdout=holdout.reshape(len(rows), len(NN_HEAD_NAMES)),
        ),
        windows=json.loads(raw) if raw else {},
    )


def network_inputs(
    table: ExampleTable, extras: Extras, labels: pa.Table, embeddings: pa.Table, feature_set: FeatureSet = FEATURE_SET
) -> NetworkInputs:
    """The report input of each row as of its moment, built by `feature_set`, and its team's project
    vectors as of the start of its snapshot day, the ones serving would read for a report born that
    day."""
    return NetworkInputs(
        reports=report_matrix(table.rows, extras, feature_set),
        context=project_context(table.rows, labels, embeddings),
    )
