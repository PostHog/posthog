"""Per-team context vectors for the inbox ranking model.

A team's engagement history carries ranking signal beyond a report's own vector: a report similar
to what the team opened or acted on before is more likely to get the same engagement. Each team
gets one vector per kind, as of a moment:

    typical  the mean of every report vector the team had
    open     the mean of the last `HISTORY_LIMIT` reports anyone on the team opened
    action   the same, over the reports anyone acted on through a UI intent action
    dismiss  the same, over the reports anyone dismissed from the UI

Only human UI engagement counts: the open, action and dismiss moments come from the inbox app
events, so MCP reads and agent actions never reach a vector. A project is a team, not an
organization.
"""

import datetime
from collections import defaultdict
from collections.abc import Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from products.signals.backend.ranking.features import (
    EMBEDDING_DIMENSIONS,
    MIN_PROJECT_HISTORY_REPORTS,
    PROJECT_VECTOR_KINDS,
)
from products.signals.dags.inbox_ranking.dataset.queries import ACTION_TYPES
from products.signals.dags.inbox_ranking.training.heads import UI_ACTION_COLUMNS

# A leaf with its own columns, so its schema moves apart from FEATURE_SCHEMA_VERSION.
PROJECT_VECTORS_SCHEMA_VERSION = 1

HISTORY_LIMIT = 50
# The backend owns the kinds and the threshold, because the scoring sweep builds the same inputs.
MIN_HISTORY_REPORTS = MIN_PROJECT_HISTORY_REPORTS
VECTOR_KINDS = PROJECT_VECTOR_KINDS
TYPICAL, OPEN, ACTION, DISMISS = VECTOR_KINDS

OPEN_COLUMN = "first_opened_at"
DISMISS_COLUMN = "first_ui_dismissed_at"
UI_ACTION_FIRST_COLUMNS = tuple(first for _, count, first in ACTION_TYPES if count in UI_ACTION_COLUMNS)
LABEL_COLUMNS = ("report_id", OPEN_COLUMN, DISMISS_COLUMN, *UI_ACTION_FIRST_COLUMNS)
EMBEDDING_COLUMNS = ("report_id", "report_team_id", "embedding_small", "embedding_inserted_at", "is_tombstone")

_PROJECT_VECTORS_FIELDS: list[tuple[str, pa.DataType]] = [
    ("team_id", pa.int64()),
    ("kind", pa.string()),
    ("vector", pa.list_(pa.float32())),
    ("n_reports", pa.int32()),
    ("as_of", pa.timestamp("us", tz="UTC")),
]
PROJECT_VECTORS_SCHEMA = pa.schema(_PROJECT_VECTORS_FIELDS)


def project_vectors(labels: pa.Table, embeddings: pa.Table, as_of: datetime.datetime) -> pa.Table:
    """One row per (team, kind) for every team with a report vector before `as_of`.

    `labels` is an `inbox_report_labels` snapshot and `embeddings` an `inbox_report_embeddings`
    snapshot, both at or after `as_of`. A later snapshot rebuilds an earlier day: a report enters a
    vector only when its vector landed and its engagement happened strictly before `as_of`. The
    snapshot keeps only the latest vector per report, so a report re-embedded after `as_of` is left
    out rather than read with text it did not have yet.

    A kind with fewer than `MIN_HISTORY_REPORTS` reports keeps its row, with its real `n_reports`
    and an all-zero vector, so a reader can tell a thin history from a missing team.
    """
    usable = _usable_embeddings(embeddings, as_of)
    matrix = (
        pc.list_flatten(usable.column("embedding_small").combine_chunks())
        .to_numpy(zero_copy_only=False)
        .reshape(-1, EMBEDDING_DIMENSIONS)
    )
    report_ids = [str(report_id) for report_id in usable.column("report_id").to_pylist()]
    rows_by_team: dict[int, list[int]] = defaultdict(list)
    for index, team_id in enumerate(usable.column("report_team_id").to_pylist()):
        if team_id is not None:
            rows_by_team[team_id].append(index)
    engaged_at = _engaged_at(labels)

    rows: list[dict[str, object]] = []
    for team_id in sorted(rows_by_team):
        team_rows = rows_by_team[team_id]
        rows.append(_vector_row(team_id, TYPICAL, matrix, team_rows, as_of))
        for kind in (OPEN, ACTION, DISMISS):
            moments = engaged_at[kind]
            engaged = [
                (moment, index)
                for index in team_rows
                if (moment := moments.get(report_ids[index])) is not None and moment < as_of
            ]
            latest = [index for _, index in sorted(engaged, reverse=True)[:HISTORY_LIMIT]]
            rows.append(_vector_row(team_id, kind, matrix, latest, as_of))
    return pa.Table.from_pylist(rows, schema=PROJECT_VECTORS_SCHEMA)


def teams_with_history(table: pa.Table) -> dict[str, int]:
    """How many teams of a `project_vectors` table have enough history for a real vector, per kind."""
    counts = table.select(["kind", "n_reports"]).to_pylist()
    return {
        kind: sum(1 for row in counts if row["kind"] == kind and row["n_reports"] >= MIN_HISTORY_REPORTS)
        for kind in VECTOR_KINDS
    }


def _usable_embeddings(embeddings: pa.Table, as_of: datetime.datetime) -> pa.Table:
    """The rows with a full-width, live vector that landed before `as_of`.

    Only the narrow columns are pulled into Python; the vectors stay in Arrow."""
    widths = pc.list_value_length(embeddings.column("embedding_small")).to_pylist()
    mask = pa.array(
        [
            team_id is not None
            and not is_tombstone
            and width == EMBEDDING_DIMENSIONS
            and inserted_at is not None
            and inserted_at < as_of
            for team_id, is_tombstone, width, inserted_at in zip(
                embeddings.column("report_team_id").to_pylist(),
                embeddings.column("is_tombstone").to_pylist(),
                widths,
                embeddings.column("embedding_inserted_at").to_pylist(),
                strict=True,
            )
        ],
        type=pa.bool_(),
    )
    return embeddings.filter(mask).select(["report_id", "report_team_id", "embedding_small"])


def _engaged_at(labels: pa.Table) -> dict[str, dict[str, datetime.datetime]]:
    """The first UI engagement moment of each kind per report."""
    engaged_at: dict[str, dict[str, datetime.datetime]] = {OPEN: {}, ACTION: {}, DISMISS: {}}
    for row in labels.select(list(LABEL_COLUMNS)).to_pylist():
        report_id = row["report_id"]
        if row[OPEN_COLUMN] is not None:
            engaged_at[OPEN][report_id] = row[OPEN_COLUMN]
        if row[DISMISS_COLUMN] is not None:
            engaged_at[DISMISS][report_id] = row[DISMISS_COLUMN]
        actions = [row[column] for column in UI_ACTION_FIRST_COLUMNS if row[column] is not None]
        if actions:
            engaged_at[ACTION][report_id] = min(actions)
    return engaged_at


def _vector_row(
    team_id: int, kind: str, matrix: np.ndarray, indices: Sequence[int], as_of: datetime.datetime
) -> dict[str, object]:
    if len(indices) < MIN_HISTORY_REPORTS:
        vector = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)
    else:
        vector = matrix[list(indices)].mean(axis=0, dtype=np.float64).astype(np.float32)
    return {"team_id": team_id, "kind": kind, "vector": vector, "n_reports": len(indices), "as_of": as_of}
