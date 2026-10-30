"""Per-team context vectors for the inbox ranking model.

A team's engagement history carries ranking signal beyond a report's own vector: a report similar
to what the team opened or acted on before is more likely to get the same engagement. Each team
gets one vector per kind, as of a moment:

    typical  the mean of every report vector the team had
    open     the mean of the last `HISTORY_LIMIT` reports anyone on the team opened
    action   the same, over the reports anyone acted on through a UI intent action
    dismiss  the same, over the reports anyone dismissed from the UI
    fixed    the same, over the reports the team got fixed (`first_fixed_at`)

The open, action and dismiss moments come from the inbox app events, so only human UI engagement
counts there, and MCP reads and agent actions never reach those vectors. The fixed moment comes from
the status stream, so a fix through an agent or a merged PR counts. The stored table carries all five
kinds, and serving gives each model the kinds it reads. A family reads `PROJECT_VECTOR_KINDS` unless
it asks for others. A project is a team, not an organization.

`user_vectors` builds the same kind of vector for one person in one organization, from the
`inbox_user_report_interactions` rows of the reports that person viewed or dismissed:

    open     the mean of the last `USER_HISTORY_LIMIT` reports the user viewed (`first_viewed_at`)
    dismiss  the same, over the reports the user dismissed from the UI

Both functions take a report into a vector through the same as-of rule (`known_before`) and the same
embedding gate (`_usable_embeddings`).

`with_user_hashes` gives each (organization, user) one hash over its kinds, counts and vectors, so a
reader can tell a changed history from an unchanged one without a comparison of the vectors.
"""

import hashlib
import datetime
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import TypeGuard

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import (
    ALL_PROJECT_VECTOR_KINDS,
    EMBEDDING_DIMENSIONS,
    MIN_PROJECT_HISTORY_REPORTS,
    PROJECT_VECTOR_KINDS,
    USER_HISTORY_KINDS,
)
from products.signals.dags.inbox_ranking.dataset.queries import ACTION_TYPES
from products.signals.dags.inbox_ranking.training.heads import UI_ACTION_COLUMNS

# A leaf with its own columns, so its schema moves apart from FEATURE_SCHEMA_VERSION.
PROJECT_VECTORS_SCHEMA_VERSION = 2

HISTORY_LIMIT = 50
# The backend owns the kinds and the threshold, because the scoring sweep builds the same inputs.
MIN_HISTORY_REPORTS = MIN_PROJECT_HISTORY_REPORTS
VECTOR_KINDS = PROJECT_VECTOR_KINDS
CONTEXT_KINDS = ALL_PROJECT_VECTOR_KINDS
TYPICAL, OPEN, ACTION, DISMISS, FIXED = CONTEXT_KINDS

OPEN_COLUMN = "first_opened_at"
DISMISS_COLUMN = "first_ui_dismissed_at"
FIXED_COLUMN = "first_fixed_at"
UI_ACTION_FIRST_COLUMNS = tuple(first for _, count, first in ACTION_TYPES if count in UI_ACTION_COLUMNS)
# The UI engagement columns of the labels snapshot. `fixed` comes from the status stream instead.
LABEL_COLUMNS = ("report_id", OPEN_COLUMN, DISMISS_COLUMN, *UI_ACTION_FIRST_COLUMNS)
CONTEXT_LABEL_COLUMNS = (*LABEL_COLUMNS, FIXED_COLUMN)
# The engagement export carries exactly these columns to the other region.
ENGAGEMENT_EXPORT_COLUMNS = CONTEXT_LABEL_COLUMNS
EMBEDDING_COLUMNS = ("report_id", "report_team_id", "embedding_small", "embedding_inserted_at", "is_tombstone")

_PROJECT_VECTORS_FIELDS: list[tuple[str, pa.DataType]] = [
    ("team_id", pa.int64()),
    ("kind", pa.string()),
    ("vector", pa.list_(pa.float32())),
    ("n_reports", pa.int32()),
    ("as_of", pa.timestamp("us", tz="UTC")),
]
PROJECT_VECTORS_SCHEMA = pa.schema(_PROJECT_VECTORS_FIELDS)

USER_HISTORY_LIMIT = 20


@frozen
class OrganizationUser:
    organization_id: str
    user_distinct_id: str


# The backend owns the user kinds too, because the pair network reads them in this order.
USER_OPEN, USER_DISMISS = USER_HISTORY_KINDS
# The durable VIEW action row dates an open, because the `Inbox report opened` event misses the
# surfaces that send no client event.
USER_HISTORY_COLUMNS: Mapping[str, str] = {USER_OPEN: "first_viewed_at", USER_DISMISS: DISMISS_COLUMN}
USER_VECTOR_KINDS = tuple(USER_HISTORY_COLUMNS)
USER_INTERACTION_COLUMNS = ("report_id", "report_team_id", "user_distinct_id", *USER_HISTORY_COLUMNS.values())

_USER_VECTORS_FIELDS: list[tuple[str, pa.DataType]] = [
    ("organization_id", pa.string()),
    ("user_distinct_id", pa.string()),
    ("kind", pa.string()),
    ("vector", pa.list_(pa.float32())),
    ("n_reports", pa.int32()),
    ("last_at", pa.timestamp("us", tz="UTC")),
    ("as_of", pa.timestamp("us", tz="UTC")),
]
USER_VECTORS_SCHEMA = pa.schema(_USER_VECTORS_FIELDS)

# A leaf with its own columns too, so its schema moves apart from the project vectors'.
USER_VECTORS_SCHEMA_VERSION = 1
USER_VECTORS_DAY_SCHEMA = USER_VECTORS_SCHEMA.append(pa.field("user_hash", pa.string()))
# (name, lowest, highest) prior views per bucket. The within-user grade needs enough rows in the
# buckets with real history to be readable.
HISTORY_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0", 0, 0),
    ("1_9", 1, 9),
    ("10_49", 10, 49),
    ("50_plus", 50, None),
)


def project_vectors(
    labels: pa.Table, embeddings: pa.Table, as_of: datetime.datetime, kinds: Sequence[str] = VECTOR_KINDS
) -> pa.Table:
    """One row per (team, kind of `kinds`) for every team with a report vector before `as_of`.

    `labels` is an `inbox_report_labels` snapshot and `embeddings` an `inbox_report_embeddings`
    snapshot, both at or after `as_of`. A later snapshot rebuilds an earlier day: a report enters a
    vector only when its vector landed and its engagement happened strictly before `as_of`. The
    snapshot keeps only the latest vector per report, so a report re-embedded after `as_of` is left
    out rather than read with text it did not have yet.

    A kind with fewer than `MIN_HISTORY_REPORTS` reports keeps its row, with its real `n_reports`
    and an all-zero vector, so a reader can tell a thin history from a missing team. `kinds` defaults
    to `PROJECT_VECTOR_KINDS`. Asking for `fixed` needs the `first_fixed_at` column in `labels`.
    """
    unknown = [kind for kind in kinds if kind not in CONTEXT_KINDS]
    if unknown:
        raise ValueError(f"unknown project vector kinds {unknown}; pick from {list(CONTEXT_KINDS)}")
    usable = _usable_embeddings(embeddings, as_of)
    matrix = _embedding_matrix(usable)
    report_ids = [str(report_id) for report_id in usable.column("report_id").to_pylist()]
    rows_by_team: dict[int, list[int]] = defaultdict(list)
    for index, team_id in enumerate(usable.column("report_team_id").to_pylist()):
        if team_id is not None:
            rows_by_team[team_id].append(index)
    engaged_at = _engaged_at(labels, with_fixed=FIXED in kinds)

    rows: list[dict[str, object]] = []
    for team_id in sorted(rows_by_team):
        team_rows = rows_by_team[team_id]
        for kind in kinds:
            if kind == TYPICAL:
                rows.append(_vector_row(team_id, TYPICAL, matrix, team_rows, as_of))
                continue
            moments = engaged_at[kind]
            engaged = [
                (moment, index) for index in team_rows if known_before(moment := moments.get(report_ids[index]), as_of)
            ]
            latest = [index for _, index in _latest(engaged, HISTORY_LIMIT)]
            rows.append(_vector_row(team_id, kind, matrix, latest, as_of))
    return pa.Table.from_pylist(rows, schema=PROJECT_VECTORS_SCHEMA)


def user_vectors(
    interactions: pa.Table,
    embeddings: pa.Table,
    as_of: datetime.datetime,
    *,
    organizations: Mapping[int, str],
) -> pa.Table:
    """One row per (organization, user, kind) for every user with a usable report of that kind.

    `interactions` is an `inbox_user_report_interactions` snapshot and `embeddings` an
    `inbox_report_embeddings` snapshot, both at or after `as_of`. `organizations` maps a report's
    team to its organization. A report enters the user's row of its own team's organization, so
    history from another organization never reaches the row. A report whose team has no entry in
    `organizations` is left out.

    `vector` is the plain mean of the user's last `USER_HISTORY_LIMIT` reports of the kind, by the
    kind's moment, that pass the `project_vectors` rules: the moment is strictly before `as_of`, and
    the report vector landed before `as_of` and is not a tombstone. `last_at` is the newest of those
    moments. A user with no such report gets no row for the kind.
    """
    histories: dict[tuple[str, str, str], list[tuple[datetime.datetime, str]]] = defaultdict(list)
    for row in interactions.select(list(USER_INTERACTION_COLUMNS)).to_pylist():
        organization_id = organizations.get(row["report_team_id"])
        if organization_id is None or row["user_distinct_id"] is None:
            continue
        for kind, column in USER_HISTORY_COLUMNS.items():
            if known_before(moment := row[column], as_of):
                histories[(organization_id, row["user_distinct_id"], kind)].append((moment, str(row["report_id"])))

    # Only the history's reports are gated and flattened, so a call costs the user set's history
    # rather than a copy of the whole embeddings snapshot.
    needed = pa.array(sorted({report_id for history in histories.values() for _, report_id in history}), pa.string())
    usable = _usable_embeddings(embeddings.filter(pc.is_in(embeddings.column("report_id"), value_set=needed)), as_of)
    matrix = _embedding_matrix(usable)
    index_of = {str(report_id): index for index, report_id in enumerate(usable.column("report_id").to_pylist())}

    rows: list[dict[str, object]] = []
    for (organization_id, user_distinct_id, kind), history in sorted(histories.items()):
        latest = _latest(
            [(moment, index_of[report_id]) for moment, report_id in history if report_id in index_of],
            USER_HISTORY_LIMIT,
        )
        if not latest:
            continue
        indices = [index for _, index in latest]
        rows.append(
            {
                "organization_id": organization_id,
                "user_distinct_id": user_distinct_id,
                "kind": kind,
                "vector": matrix[indices].mean(axis=0, dtype=np.float64).astype(np.float32),
                "n_reports": len(indices),
                "last_at": latest[0][0],
                "as_of": as_of,
            }
        )
    return pa.Table.from_pylist(rows, schema=USER_VECTORS_SCHEMA)


def with_user_hashes(table: pa.Table) -> pa.Table:
    """`table`, a `user_vectors` table, with the `user_hash` of each row's (organization, user).

    The hash reads each kind's name, `n_reports` and vector bytes, in kind order. `last_at` and
    `as_of` stay out, so a day that adds no report to a user's history keeps the user's hash.
    """
    rows = table.select(["organization_id", "user_distinct_id", "kind", "n_reports"]).to_pylist()
    vectors = table.column("vector").to_numpy(zero_copy_only=False)
    parts: dict[tuple[str, str], list[bytes]] = defaultdict(list)
    for index in sorted(range(len(rows)), key=lambda i: rows[i]["kind"]):
        row = rows[index]
        parts[(row["organization_id"], row["user_distinct_id"])] += [
            row["kind"].encode(),
            int(row["n_reports"]).to_bytes(4, "little"),
            np.asarray(vectors[index], dtype="<f4").tobytes(),
        ]
    hashes = {user: hashlib.sha256(b"".join(user_parts)).hexdigest() for user, user_parts in parts.items()}
    return table.append_column(
        "user_hash",
        pa.array([hashes[(row["organization_id"], row["user_distinct_id"])] for row in rows], pa.string()),
    )


def prior_views(
    interactions: pa.Table, as_of: datetime.datetime, *, organizations: Mapping[int, str]
) -> Counter[OrganizationUser]:
    """The views before `as_of` of each (organization, user) in `interactions`. A user with
    interaction rows and no such view counts 0."""
    view_column = USER_HISTORY_COLUMNS[USER_OPEN]
    views: Counter[OrganizationUser] = Counter()
    for row in interactions.select(["report_team_id", "user_distinct_id", view_column]).to_pylist():
        organization_id = organizations.get(row["report_team_id"])
        if organization_id is not None and row["user_distinct_id"] is not None:
            user = OrganizationUser(organization_id=organization_id, user_distinct_id=row["user_distinct_id"])
            views[user] += int(known_before(row[view_column], as_of))
    return views


def history_buckets(views: Counter[OrganizationUser]) -> dict[str, int]:
    """How many users of `views` fall in each of `HISTORY_BUCKETS`."""
    return {
        name: sum(1 for count in views.values() if count >= lowest and (highest is None or count <= highest))
        for name, lowest, highest in HISTORY_BUCKETS
    }


def known_before(moment: datetime.datetime | None, as_of: datetime.datetime) -> TypeGuard[datetime.datetime]:
    """The as-of rule of every context vector: a moment counts only when it is strictly before `as_of`."""
    return moment is not None and moment < as_of


def teams_with_history(table: pa.Table, kinds: Sequence[str] = VECTOR_KINDS) -> dict[str, int]:
    """How many teams of a `project_vectors` table have enough history for a real vector, per kind."""
    counts = table.select(["kind", "n_reports"]).to_pylist()
    return {
        kind: sum(1 for row in counts if row["kind"] == kind and row["n_reports"] >= MIN_HISTORY_REPORTS)
        for kind in kinds
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


def _embedding_matrix(usable: pa.Table) -> np.ndarray:
    return (
        pc.list_flatten(usable.column("embedding_small").combine_chunks())
        .to_numpy(zero_copy_only=False)
        .reshape(-1, EMBEDDING_DIMENSIONS)
    )


def _latest(engaged: list[tuple[datetime.datetime, int]], limit: int) -> list[tuple[datetime.datetime, int]]:
    """The `limit` newest (moment, row) pairs, newest first."""
    return sorted(engaged, reverse=True)[:limit]


def _engaged_at(labels: pa.Table, *, with_fixed: bool) -> dict[str, dict[str, datetime.datetime]]:
    """The first engagement moment of each kind per report: the UI kinds, and `fixed` when asked."""
    engaged_at: dict[str, dict[str, datetime.datetime]] = {OPEN: {}, ACTION: {}, DISMISS: {}, FIXED: {}}
    columns = CONTEXT_LABEL_COLUMNS if with_fixed else LABEL_COLUMNS
    for row in labels.select(list(columns)).to_pylist():
        report_id = row["report_id"]
        if row[OPEN_COLUMN] is not None:
            engaged_at[OPEN][report_id] = row[OPEN_COLUMN]
        if row[DISMISS_COLUMN] is not None:
            engaged_at[DISMISS][report_id] = row[DISMISS_COLUMN]
        if with_fixed and row[FIXED_COLUMN] is not None:
            engaged_at[FIXED][report_id] = row[FIXED_COLUMN]
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
