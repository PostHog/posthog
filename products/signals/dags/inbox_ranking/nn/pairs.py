"""Report-user pair examples for the personal ranking lane, without torch.

One asset on the `signals_ml` location, on the dataset dag's daily partition:

    inbox_ranking_nn_pair_examples/v1/dt=D/   one row per (report example, impressed user)

The report rows are the `open` head's rows of the day's `inbox_ranking_nn_examples` object, so the
report inputs, the holdout split and the day windows are the report-grain lane's. A report born on
day B pairs with each user who was impressed with it within `PAIR_HORIZON_DAYS` of birth, read from
the dt=B+`PAIR_HORIZON_DAYS` `inbox_user_report_interactions` partition, the same later partition the
report's `open` label reads. The pair labels come from the same partition.

The user inputs are as of the start of day B, the moment the report examples' project vectors use.
So the target report and the reports born with it are outside the user's history by construction.
Like the report examples object, the pair object holds no vector: `pair_user_vectors` rebuilds the
user vectors from the dt=D interactions and embeddings snapshots through `user_vectors()`.
"""

import datetime
from collections.abc import Mapping

import numpy as np
import pandas as pd
import dagster
import pyarrow as pa
import pyarrow.compute as pc

from posthog import settings

from products.signals.backend.ranking.features import DAYS_SINCE_LAST_VIEW_CAP, EMBEDDING_DIMENSIONS
from products.signals.dags.inbox_ranking.common import (
    dataset_bucket,
    owner_tags,
    partition_object_key,
    read_parquet_if_exists,
    s3_client,
    skip_unconfigured,
    snapshot_bounds,
    write_parquet,
)
from products.signals.dags.inbox_ranking.consent import training_consent_team_ids
from products.signals.dags.inbox_ranking.dataset.dag import (
    EMBEDDINGS_TABLE,
    REVIEWERS_TABLE,
    USER_INTERACTIONS_TABLE,
    team_organizations,
)
from products.signals.dags.inbox_ranking.dataset.project_vectors import (
    EMBEDDING_COLUMNS,
    HISTORY_BUCKETS,
    UI_ACTION_FIRST_COLUMNS,
    USER_DISMISS,
    USER_INTERACTION_COLUMNS,
    USER_OPEN,
    USER_VECTOR_KINDS,
    OrganizationUser,
    known_before,
    prior_views,
    user_vectors,
)
from products.signals.dags.inbox_ranking.nn.dag import NN_ASSET_KWARGS, NN_EXAMPLES_TABLE
from products.signals.dags.inbox_ranking.training.dag import _LOOKBACK_MAPPING
from products.signals.dags.inbox_ranking.training.families import PAIR_HEAD_NAMES
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME

NN_PAIR_EXAMPLES_TABLE = "inbox_ranking_nn_pair_examples"
PAIR_EXAMPLES_SCHEMA_VERSION = 1

# The report head whose rows, holdout and later label partition the pairs share.
_REPORT_HEAD = HEADS_BY_NAME["open"]
PAIR_HORIZON_DAYS = _REPORT_HEAD.horizon_days
PAIR_HEADS = PAIR_HEAD_NAMES
DAYS_SINCE_VIEW_CAP = DAYS_SINCE_LAST_VIEW_CAP
REVIEWERS_SOURCE = "reviewers"
IMPRESSIONS_SOURCE = "impressions"

LABEL_INTERACTION_COLUMNS = (
    "report_id",
    "user_distinct_id",
    "first_impressed_at",
    "impressed_as_suggested_reviewer_count",
    "first_opened_at",
    *UI_ACTION_FIRST_COLUMNS,
)
REVIEWER_COLUMNS = ("report_id", "user_distinct_id")

_PAIR_EXAMPLES_FIELDS: list[tuple[str, pa.DataType]] = [
    ("snapshot_date", pa.date32()),
    ("report_id", pa.string()),
    ("report_team_id", pa.int64()),
    ("user_distinct_id", pa.string()),
    ("holdout", pa.bool_()),
    ("open_label", pa.float32()),
    ("action_label", pa.float32()),
    ("user_open_reports", pa.int32()),
    ("user_dismiss_reports", pa.int32()),
    ("prior_views", pa.int32()),
    ("days_since_last_view", pa.float32()),
    ("has_history", pa.bool_()),
    ("is_suggested_reviewer", pa.bool_()),
    ("suggested_reviewer_source", pa.string()),
]
PAIR_EXAMPLES_SCHEMA = pa.schema(_PAIR_EXAMPLES_FIELDS)


def _users_history(history: pa.Table, users: list[str]) -> pa.Table:
    return history.filter(pc.is_in(history.column("user_distinct_id"), value_set=pa.array(users, pa.string())))


def pair_rows(
    reports: pd.DataFrame,
    impressions: pa.Table,
    history: pa.Table,
    embeddings: pa.Table,
    *,
    birth_day: datetime.date,
    reviewers: pa.Table | None,
    organizations: Mapping[int, str],
) -> list[dict[str, object]]:
    """The pair rows of the reports born on `birth_day`.

    `reports` holds the day's report example rows (`report_id`, `report_team_id`, `holdout`).
    `impressions` is the dt=`birth_day`+`PAIR_HORIZON_DAYS` interactions partition, and `history`
    and `embeddings` are the dt=D snapshots the user vectors read. `reviewers` is the dt=`birth_day`
    reviewers partition, or None when that day has none, and then a suggested-reviewer impression
    stands in for it.
    """
    as_of, _ = snapshot_bounds(birth_day.isoformat())
    _, horizon_end = snapshot_bounds((birth_day + datetime.timedelta(days=PAIR_HORIZON_DAYS)).isoformat())
    report_ids = [str(report_id) for report_id in reports["report_id"]]
    report_teams = dict(zip(report_ids, (int(team_id) for team_id in reports["report_team_id"]), strict=True))
    holdout = dict(zip(report_ids, (bool(flag) for flag in reports["holdout"]), strict=True))

    impressed = [
        row
        for row in impressions.filter(
            pc.is_in(impressions.column("report_id"), value_set=pa.array(report_ids, pa.string()))
        )
        .select(list(LABEL_INTERACTION_COLUMNS))
        .to_pylist()
        if row["user_distinct_id"] is not None and known_before(row["first_impressed_at"], horizon_end)
    ]
    if not impressed:
        return []

    users_history = _users_history(history, sorted({row["user_distinct_id"] for row in impressed}))
    vectors = {
        (row["organization_id"], row["user_distinct_id"], row["kind"]): row
        for row in user_vectors(users_history, embeddings, as_of, organizations=organizations)
        .drop_columns(["vector"])
        .to_pylist()
    }
    views = prior_views(users_history, as_of, organizations=organizations)
    suggested = (
        {(row["report_id"], row["user_distinct_id"]) for row in reviewers.select(list(REVIEWER_COLUMNS)).to_pylist()}
        if reviewers is not None
        else set()
    )

    rows: list[dict[str, object]] = []
    for row in impressed:
        report_id, user = str(row["report_id"]), row["user_distinct_id"]
        organization_id = organizations.get(report_teams[report_id])
        open_vector = vectors.get((organization_id, user, USER_OPEN))
        dismiss_vector = vectors.get((organization_id, user, USER_DISMISS))
        days_since_last_view = (
            min((as_of - open_vector["last_at"]).total_seconds() / 86400, DAYS_SINCE_VIEW_CAP)
            if open_vector is not None
            else DAYS_SINCE_VIEW_CAP
        )
        rows.append(
            {
                "snapshot_date": birth_day,
                "report_id": report_id,
                "report_team_id": report_teams[report_id],
                "user_distinct_id": user,
                "holdout": holdout[report_id],
                "open_label": float(known_before(row["first_opened_at"], horizon_end)),
                "action_label": float(
                    any(known_before(row[column], horizon_end) for column in UI_ACTION_FIRST_COLUMNS)
                ),
                "user_open_reports": open_vector["n_reports"] if open_vector is not None else 0,
                "user_dismiss_reports": dismiss_vector["n_reports"] if dismiss_vector is not None else 0,
                "prior_views": (
                    views[OrganizationUser(organization_id=organization_id, user_distinct_id=user)]
                    if organization_id is not None
                    else 0
                ),
                "days_since_last_view": days_since_last_view,
                "has_history": open_vector is not None or dismiss_vector is not None,
                "is_suggested_reviewer": (
                    (report_id, user) in suggested
                    if reviewers is not None
                    else (row["impressed_as_suggested_reviewer_count"] or 0) > 0
                ),
                "suggested_reviewer_source": REVIEWERS_SOURCE if reviewers is not None else IMPRESSIONS_SOURCE,
            }
        )
    return rows


def pair_user_vectors(
    pairs: pd.DataFrame, history: pa.Table, embeddings: pa.Table, *, organizations: Mapping[int, str]
) -> np.ndarray:
    """The user vectors of each pair row, one per kind of `USER_VECTOR_KINDS`, as of the start of
    its birth day. A kind without history is all zeros, and the row's `user_*_reports` tells it apart."""
    pairs = pairs.reset_index(drop=True)
    vectors = np.zeros((len(pairs), len(USER_VECTOR_KINDS), EMBEDDING_DIMENSIONS), dtype=np.float32)
    for birth_day, group in pairs.groupby("snapshot_date", sort=True):
        as_of, _ = snapshot_bounds(birth_day.isoformat())
        day = user_vectors(
            _users_history(history, sorted(set(group["user_distinct_id"]))),
            embeddings,
            as_of,
            organizations=organizations,
        )
        by_key = {
            (organization_id, user, kind): vector
            for organization_id, user, kind, vector in zip(
                day.column("organization_id").to_pylist(),
                day.column("user_distinct_id").to_pylist(),
                day.column("kind").to_pylist(),
                day.column("vector").to_numpy(zero_copy_only=False),
                strict=True,
            )
        }
        for position, team_id, user in zip(
            group.index, group["report_team_id"], group["user_distinct_id"], strict=True
        ):
            organization_id = organizations.get(int(team_id))
            for kind_index, kind in enumerate(USER_VECTOR_KINDS):
                vector = by_key.get((organization_id, user, kind))
                if vector is not None:
                    vectors[position, kind_index] = vector
    return vectors


def pair_metadata(table: pa.Table) -> dict[str, dagster.MetadataValue]:
    frame = table.select(
        [
            "report_id",
            "user_distinct_id",
            "prior_views",
            "is_suggested_reviewer",
            *(f"{head}_label" for head in PAIR_HEADS),
        ]
    ).to_pandas()
    metadata: dict[str, dagster.MetadataValue] = {
        "rows": dagster.MetadataValue.int(len(frame)),
        "users": dagster.MetadataValue.int(int(frame["user_distinct_id"].nunique())),
        "reports": dagster.MetadataValue.int(int(frame["report_id"].nunique())),
        **{f"{head}_positives": dagster.MetadataValue.int(int(frame[f"{head}_label"].sum())) for head in PAIR_HEADS},
        "suggested_reviewer_share": dagster.MetadataValue.float(
            float(frame["is_suggested_reviewer"].mean()) if len(frame) else 0.0
        ),
    }
    for name, lowest, highest in HISTORY_BUCKETS:
        in_bucket = frame["prior_views"] >= lowest
        if highest is not None:
            in_bucket &= frame["prior_views"] <= highest
        metadata[f"history_{name}_rows"] = dagster.MetadataValue.int(int(in_bucket.sum()))
        metadata[f"history_{name}_users"] = dagster.MetadataValue.int(
            int(frame.loc[in_bucket, "user_distinct_id"].nunique())
        )
    return metadata


def build_pair_examples(
    context: dagster.AssetExecutionContext,
    client,
    bucket: str,
    partition_key: str,
    *,
    consent_team_ids: frozenset[int],
    organizations: Mapping[int, str],
) -> dict[str, dagster.MetadataValue]:
    """Write the dt=`partition_key` pair examples and return the asset metadata. A partition without
    the report examples or the dt=D snapshots keeps the object it already holds."""
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
    examples = read_parquet_if_exists(client, bucket, partition_object_key(prefix, NN_EXAMPLES_TABLE, partition_key))
    history = read_parquet_if_exists(
        client,
        bucket,
        partition_object_key(prefix, USER_INTERACTIONS_TABLE, partition_key),
        columns=list(USER_INTERACTION_COLUMNS),
    )
    embeddings = read_parquet_if_exists(
        client, bucket, partition_object_key(prefix, EMBEDDINGS_TABLE, partition_key), columns=list(EMBEDDING_COLUMNS)
    )
    missing = [
        name
        for name, table in (
            (NN_EXAMPLES_TABLE, examples),
            (USER_INTERACTIONS_TABLE, history),
            (EMBEDDINGS_TABLE, embeddings),
        )
        if table is None
    ]
    if examples is None or history is None or embeddings is None:
        context.log.warning(f"no {', '.join(missing)} for dt={partition_key}; pair examples skip this partition")
        return {"skipped": dagster.MetadataValue.bool(True)}

    consented = pa.array(sorted(consent_team_ids), pa.int64())
    history = history.filter(pc.is_in(history.column("report_team_id"), value_set=consented))
    reports = examples.select(
        ["report_id", "snapshot_date", "report_team_id", f"{_REPORT_HEAD.name}_label", f"{_REPORT_HEAD.name}_holdout"]
    ).to_pandas()
    reports = reports[reports[f"{_REPORT_HEAD.name}_label"].notna()]
    with_consent = reports["report_team_id"].isin(consent_team_ids)
    excluded_reports = int((~with_consent).sum())
    reports = reports[with_consent].rename(columns={f"{_REPORT_HEAD.name}_holdout": "holdout"})

    rows: list[dict[str, object]] = []
    days_without_impressions = 0
    days_with_reviewers = 0
    for birth_day, group in reports.groupby("snapshot_date", sort=True):
        label_day = (birth_day + datetime.timedelta(days=PAIR_HORIZON_DAYS)).isoformat()
        impressions = read_parquet_if_exists(
            client,
            bucket,
            partition_object_key(prefix, USER_INTERACTIONS_TABLE, label_day),
            columns=list(LABEL_INTERACTION_COLUMNS),
        )
        if impressions is None:
            days_without_impressions += 1
            continue
        reviewers = read_parquet_if_exists(
            client,
            bucket,
            partition_object_key(prefix, REVIEWERS_TABLE, birth_day.isoformat()),
            columns=list(REVIEWER_COLUMNS),
        )
        days_with_reviewers += reviewers is not None
        rows.extend(
            pair_rows(
                group,
                impressions,
                history,
                embeddings,
                birth_day=birth_day,
                reviewers=reviewers,
                organizations=organizations,
            )
        )
    if days_without_impressions:
        context.log.warning(
            f"{days_without_impressions} birth days have no {USER_INTERACTIONS_TABLE} label partition; their reports have no pairs"
        )

    table = pa.Table.from_pylist(rows, schema=PAIR_EXAMPLES_SCHEMA)
    key = partition_object_key(prefix, NN_PAIR_EXAMPLES_TABLE, partition_key)
    write_parquet(client, bucket, key, table, snapshot_date=partition_key, schema_version=PAIR_EXAMPLES_SCHEMA_VERSION)
    return {
        **pair_metadata(table),
        "birth_days": dagster.MetadataValue.int(int(reports["snapshot_date"].nunique())),
        "birth_days_without_impressions": dagster.MetadataValue.int(days_without_impressions),
        "birth_days_with_reviewers": dagster.MetadataValue.int(days_with_reviewers),
        "excluded_no_training_consent_reports": dagster.MetadataValue.int(excluded_reports),
        "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
    }


@dagster.asset(
    name=NN_PAIR_EXAMPLES_TABLE,
    deps=[
        NN_EXAMPLES_TABLE,
        dagster.AssetDep(USER_INTERACTIONS_TABLE, partition_mapping=_LOOKBACK_MAPPING),
        dagster.AssetDep(REVIEWERS_TABLE, partition_mapping=_LOOKBACK_MAPPING),
        EMBEDDINGS_TABLE,
    ],
    **NN_ASSET_KWARGS,
)
def inbox_ranking_nn_pair_examples(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    consent_team_ids = training_consent_team_ids()
    context.add_output_metadata(
        build_pair_examples(
            context,
            s3_client(),
            dataset_bucket(),
            context.partition_key,
            consent_team_ids=consent_team_ids,
            organizations=team_organizations(consent_team_ids),
        )
    )


# No schedule: the pair lane is an offline experiment, and the object of any past day can be rebuilt
# from the cumulative interactions partitions. Its own job keeps its memory apart from the nn job's.
inbox_ranking_nn_pair_examples_job = dagster.define_asset_job(
    name="inbox_ranking_nn_pair_examples_job",
    selection=[NN_PAIR_EXAMPLES_TABLE],
    tags={
        **owner_tags,
        "dagster/max_runtime": str(2 * 60 * 60),
        # One embeddings snapshot as Arrow, the dt=D interactions snapshot, and one label partition
        # at a time.
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"memory": "4Gi"},
                    "limits": {"memory": "16Gi"},
                }
            }
        },
    },
)
