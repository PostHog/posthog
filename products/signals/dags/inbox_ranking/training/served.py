"""The scoring sweep's own birth-day scores, graded per model key.

The sweep scores each report with every model the serving manifest names: the served champion, the
served family's daily candidate, and the other families' champions. This module reads the sweep's
`inbox_ranking_report_scored` events for D's newborn pool and writes them in `SCORES_SCHEMA`, so
`inbox_ranking_unseen_graded` grades every model key on live scores through one path.

Caveats:

- The daily promotion can change the served model part of the way through D, so one day's cohort
  can split across two versions, and one key can carry two roles. Grades stay per
  `(model_name, model_version, model_role)` and are never pooled across versions.
- The sweep scores a candidate only after a manifest names it, so a candidate's cohort starts the
  day after it was trained, and a key added part of the way through D covers only part of D's pool.
  `pool_coverage_by_model` makes that visible.
- A report first scored after D ends, for example when its vector arrived late, is not in D's rows.
  `served_pool_coverage` makes that visible. A later score never fills it in.
- The sweep scores with the vector current at scoring time, so two keys that scored one report at
  different times did not always read the same vector.
- A deployment where the sweep is off writes an empty object with coverage 0 and grades nothing.
"""

import json
import datetime
from collections.abc import Collection, Mapping
from typing import Any

import numpy as np
import pandas as pd
import dagster

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog import settings
from posthog.models import Team

from products.signals.backend.ranking.serving_manifest import SERVED_ROLE, model_key
from products.signals.backend.ranking.sinks import REPORT_SCORED_EVENT
from products.signals.dags.inbox_ranking.common import (
    dataset_bucket,
    object_row_count,
    partition_object_key,
    read_parquet_if_exists,
    s3_client,
    skip_unconfigured,
    snapshot_bounds,
    write_parquet,
)
from products.signals.dags.inbox_ranking.dataset.dag import LABELS_TABLE, STATE_TABLE
from products.signals.dags.inbox_ranking.dataset.queries import etl_workload, labels_team, utc_bound
from products.signals.dags.inbox_ranking.training.dag import COMMON_ASSET_KWARGS, load_snapshots
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME
from products.signals.dags.inbox_ranking.training.unseen import (
    CANDIDATE_ROLE,
    POOL_NAME,
    SCORE_COLUMNS,
    SERVED_SCORES_TABLE,
    empty_scores_write_allowed,
    families_lost_by_rewrite,
    scores_table,
    unseen_pool,
)

# The status filter is repeated in `served_score_rows`, where a test can pin it.
SERVED_EVENTS_SQL = f"""
SELECT timestamp, properties
FROM events
WHERE event = '{REPORT_SCORED_EVENT}'
  AND timestamp >= toDateTime({{window_start}}) AND timestamp < toDateTime({{window_end}})
  AND ifNull(toString(properties.environment), '') = {{environment}}
  AND toString(properties.status) = 'scored'
  AND toString(properties.report_id) IN {{report_ids}}
"""


def served_events(
    team: Team,
    report_ids: Collection[str],
    *,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    environment: str,
) -> pd.DataFrame:
    """Every scored event of this deployment for `report_ids` inside the window, as
    `(scored_at, properties)` rows."""
    if not report_ids:
        return pd.DataFrame(columns=["scored_at", "properties"])
    response = execute_hogql_query(
        query=SERVED_EVENTS_SQL,
        team=team,
        query_type="inbox_ranking_served_scores",
        placeholders={
            "window_start": ast.Constant(value=utc_bound(window_start)),
            "window_end": ast.Constant(value=utc_bound(window_end)),
            "environment": ast.Constant(value=environment),
            "report_ids": ast.Tuple(exprs=[ast.Constant(value=report_id) for report_id in sorted(report_ids)]),
        },
        limit_context=LimitContext.SAVED_QUERY,
        workload=etl_workload(),
        settings=HogQLGlobalSettings(max_execution_time=600),
        # The dag runs without a user; the read is a trusted internal ETL over the dogfood project.
        bypass_warehouse_access_control=True,
    )
    return pd.DataFrame(
        [(scored_at, _properties(properties)) for scored_at, properties in response.results or []],
        columns=["scored_at", "properties"],
    )


def _properties(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value or {})


def event_model_key(properties: Mapping[str, Any]) -> str:
    """The model key the sweep scored with. An event written before `model_key` existed falls back
    to the key the manifest derives from the same identity."""
    key = properties.get("model_key")
    return str(key) if key else model_key(str(properties.get("model_name")), str(properties.get("model_version")))


def event_model_role(properties: Mapping[str, Any]) -> str:
    """One role per scored row: `served` when the model served the score, else the first role the
    manifest gave it, else `candidate`."""
    roles = list(properties.get("roles") or ())
    if SERVED_ROLE in roles:
        return SERVED_ROLE
    return str(roles[0]) if roles else CANDIDATE_ROLE


def served_score_rows(
    events: pd.DataFrame, pool: pd.DataFrame, labels: pd.DataFrame, *, snapshot_date: datetime.date
) -> pd.DataFrame:
    """One row per (newborn report, model key, head) in SCORE_COLUMNS order, from the earliest score
    of that report by that model key in `events`.

    `model_role` comes from the event's roles (`event_model_role`). `classification_threshold` is
    the scoring model's own `threshold_<head>`, null when the event carries none, so every later
    grade of the row uses the cut that model saved. `label_at_scoring` reads D's snapshot labels.
    """
    records = [
        (scored_at, properties)
        for scored_at, properties in zip(events["scored_at"], events["properties"])
        if properties.get("status") == "scored" and str(properties.get("report_id")) in pool.index
    ]
    earliest: dict[tuple[str, str], tuple[pd.Timestamp, Mapping[str, Any]]] = {}
    for scored_at, properties in sorted(records, key=lambda record: pd.Timestamp(record[0])):
        earliest.setdefault(
            (str(properties["report_id"]), event_model_key(properties)), (pd.Timestamp(scored_at), properties)
        )

    aligned = labels.reindex(pool.index)
    labels_by_head = {name: head.label(aligned) for name, head in HEADS_BY_NAME.items()}
    rows: list[dict[str, object]] = []
    for (report_id, _), (scored_at, properties) in earliest.items():
        created_at = pd.Timestamp(pool.at[report_id, "report_created_at"])
        readable = properties.get("readable_heads")
        role = event_model_role(properties)
        for head_name in sorted(HEADS_BY_NAME):
            score = properties.get(f"p_{head_name}")
            if score is None:
                continue
            threshold = properties.get(f"threshold_{head_name}")
            rows.append(
                {
                    "report_id": report_id,
                    "team_id": properties.get("team_id"),
                    "report_created_at": created_at,
                    "snapshot_date": snapshot_date,
                    "pool": POOL_NAME,
                    "model_name": properties.get("model_name"),
                    "model_version": properties.get("model_version"),
                    "model_role": role,
                    # The event does not carry the feature contract version.
                    "feature_schema_version": None,
                    "head": head_name,
                    "score": float(score),
                    "age_hours": (_utc(scored_at) - _utc(created_at)).total_seconds() / 3600,
                    "label_at_scoring": bool(labels_by_head[head_name].at[report_id]),
                    # An event written before the property existed reads as unknown.
                    "head_readable": None if readable is None else head_name in readable,
                    "classification_threshold": np.nan if threshold is None else float(threshold),
                }
            )
    if not rows:
        return pd.DataFrame(columns=list(SCORE_COLUMNS))
    frame = pd.DataFrame(rows)[list(SCORE_COLUMNS)]
    frame["team_id"] = pd.to_numeric(frame["team_id"], errors="coerce").astype("Int64")
    frame["feature_schema_version"] = frame["feature_schema_version"].astype("Int64")
    frame["head_readable"] = frame["head_readable"].astype("boolean")
    return frame


def _utc(value: pd.Timestamp) -> pd.Timestamp:
    return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")


def served_metadata(pool: pd.DataFrame, scores: pd.DataFrame) -> dict[str, dagster.MetadataValue]:
    """Coverage of the pool by the served model and by each model key, rows per model version, and
    the heads whose model saved no threshold."""
    covered = scores.loc[scores["model_role"] == SERVED_ROLE, "report_id"].nunique()
    versions = scores.groupby(["model_name", "model_version"]).size()
    coverage_by_model = scores.groupby(["model_name", "model_version", "model_role"])["report_id"].nunique()
    missing = scores.loc[scores["classification_threshold"].isna(), "head"]
    return {
        "unseen_pool": dagster.MetadataValue.int(len(pool)),
        "served_reports": dagster.MetadataValue.int(int(covered)),
        "served_pool_coverage": dagster.MetadataValue.float(covered / len(pool) if len(pool) else 0.0),
        "pool_coverage_by_model": dagster.MetadataValue.json(
            {
                f"{name}@{version}/{role}": int(count) / len(pool)
                for (name, version, role), count in coverage_by_model.items()
            }
        ),
        "rows_by_model_version": dagster.MetadataValue.json(
            {f"{name}@{version}": int(count) for (name, version), count in versions.items()}
        ),
        "heads_without_threshold": dagster.MetadataValue.json(sorted(missing.unique().tolist())),
    }


@dagster.asset(name=SERVED_SCORES_TABLE, deps=[STATE_TABLE, LABELS_TABLE], **COMMON_ASSET_KWARGS)
def inbox_ranking_served_scores(context: dagster.AssetExecutionContext) -> None:
    """D's newborn pool with each report's earliest score of D per model key. See the module
    docstring for the caveats every reader of these grades must keep."""
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()
    day = datetime.date.fromisoformat(partition_key)
    window_start, window_end = snapshot_bounds(partition_key)

    snapshot = load_snapshots(client, bucket, prefix, [day], required=day)[day]
    pool = unseen_pool(snapshot.state, day)
    events = served_events(
        labels_team(),
        [str(report_id) for report_id in pool.index],
        window_start=window_start,
        window_end=window_end,
        environment=settings.CLOUD_DEPLOYMENT or "",
    )
    scores = served_score_rows(events, pool, snapshot.labels, snapshot_date=day)

    key = partition_object_key(prefix, SERVED_SCORES_TABLE, partition_key)
    # The dt=D+horizon grade reads these rows. The events can be read again, but D's labels cannot.
    if scores.empty:
        existing_rows = object_row_count(client, bucket, key)
        if not empty_scores_write_allowed(existing_rows):
            raise dagster.Failure(
                f"{SERVED_SCORES_TABLE} dt={partition_key} already holds {existing_rows} rows and this run read "
                f"none, so writing would destroy the scores the dt=D+horizon grade reads. To replace the object "
                f"deliberately, delete it by hand first."
            )
        context.log.warning(f"no scored event for dt={partition_key}: {len(pool)} newborn reports")
    existing = read_parquet_if_exists(client, bucket, key)
    lost = families_lost_by_rewrite(existing.to_pandas(), scores) if existing is not None else []
    if lost:
        raise dagster.Failure(
            f"{SERVED_SCORES_TABLE} dt={partition_key} already holds rows for {', '.join(lost)} and this run read "
            f"none of them, so writing would destroy the scores the dt=D+horizon grade reads. Delete the object "
            f"by hand to replace it deliberately."
        )
    write_parquet(client, bucket, key, scores_table(scores), snapshot_date=partition_key)
    context.add_output_metadata(
        {**served_metadata(pool, scores), "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}")}
    )
