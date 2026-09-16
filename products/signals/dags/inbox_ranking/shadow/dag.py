"""Shadow evaluation of the ranking model against the order the inbox serves.

One asset on the daily partition:

    inbox_ranking_shadow_eval/v1/dt=D/   one row per (model, outcome, order) graded on D's lists

The inbox still serves a fixed sort, and no list response carries a model rank, so the model
cannot be measured by what people clicked on it. What can be measured is the counterfactual: take
the lists that were actually served on D, take the score each report already had when its list was
served, and ask whether the model's order would have put the opened and acted-on reports higher
than the served order did. `shadow/metrics.py` holds the ranking metrics and the position-bias
caveat; this module reads the lists from the dogfood project, the scores from S3, and writes the
grades back.

The read grades a model that is not serving, so nothing here changes what anyone sees.
"""

import datetime

import pandas as pd
import dagster
import pyarrow as pa

from posthog import settings
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tag_queries
from posthog.dags.common import dagster_tags

from products.signals.dags.inbox_ranking.common import (
    S3_BUCKET_ENV,
    dataset_bucket,
    dataset_unconfigured,
    owner_tags,
    partition_def,
    partition_object_key,
    read_parquet_if_exists,
    s3_client,
    skip_unconfigured,
    snapshot_bounds,
    write_parquet,
)
from products.signals.dags.inbox_ranking.dataset.queries import LABELS_TEAM_ID, labels_team
from products.signals.dags.inbox_ranking.shadow.metrics import (
    ATTRIBUTION_WINDOW,
    OUTCOMES,
    SCORE_JOIN_COLUMNS,
    RankingGrade,
    deduplicate_lists,
    grade_lists,
    join_scores,
    score_available_at,
    score_coverage,
    with_outcomes,
)
from products.signals.dags.inbox_ranking.shadow.queries import (
    IMPRESSION_COLUMNS,
    IMPRESSION_LISTS_SQL,
    OUTCOME_COLUMNS,
    OUTCOMES_SQL,
    hogql_rows,
)
from products.signals.dags.inbox_ranking.shadow.telemetry import shadow_grade_events
from products.signals.dags.inbox_ranking.training.telemetry import capture_training_events
from products.signals.dags.inbox_ranking.training.unseen import UNSEEN_SCORES_TABLE, with_model_names

SHADOW_TABLE = "inbox_ranking_shadow_eval"

_GRADE_FIELDS: list[tuple[str, pa.DataType]] = [
    ("snapshot_date", pa.date32()),
    ("model_name", pa.string()),
    ("model_role", pa.string()),
    ("model_versions", pa.int32()),
    ("outcome", pa.string()),
    ("ranking_order", pa.string()),
    ("lists", pa.int64()),
    ("reports", pa.int64()),
    ("mean_list_size", pa.float64()),
    ("ndcg_5", pa.float64()),
    ("ndcg_10", pa.float64()),
    ("mrr", pa.float64()),
    ("ndcg_5_std", pa.float64()),
    ("ndcg_10_std", pa.float64()),
    ("mrr_std", pa.float64()),
    ("positive_served_rank_mean", pa.float64()),
    # This grade's own coverage; `run_score_coverage` is the same share over every grade of the day.
    ("score_coverage", pa.float64()),
    ("positive_coverage", pa.float64()),
    ("full_list_coverage", pa.float64()),
    ("served_rows", pa.int64()),
    ("served_lists", pa.int64()),
    ("run_score_coverage", pa.float64()),
]
GRADE_SCHEMA = pa.schema(_GRADE_FIELDS)

# The lists of dt=D are served by scores written on earlier partitions, back to the oldest report
# still being impressed. The default same-partition mapping would run this before any of them
# exist. Partitions before the label epoch have no upstream to map to.
_SCORE_LOOKBACK_MAPPING = dagster.TimeWindowPartitionMapping(
    start_offset=-settings.INBOX_RANKING_SHADOW_SCORE_LOOKBACK_DAYS,
    # dt=D's own scores are written the next morning, after every list of D was served, so they can
    # never be part of this read.
    end_offset=-1,
    allow_nonexistent_upstream_partitions=True,
)


def _tag_dagster_queries(context: dagster.AssetExecutionContext) -> None:
    """Attribute every ClickHouse query this asset issues in system.query_log. The dogfood project
    owns the telemetry being read, so it is the team the queries are tagged with."""
    tag_queries(
        product=Product.SIGNALS,
        feature=Feature.DATA_MODELING,
        team_id=LABELS_TEAM_ID,
        query_type="inbox_ranking_shadow_eval",
    )
    get_query_tags().with_dagster(dagster_tags(context))


def impression_frame(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(IMPRESSION_COLUMNS))
    frame["impressed_at"] = pd.to_datetime(frame["impressed_at"], utc=True)
    frame["served_rank"] = pd.to_numeric(frame["served_rank"])
    return frame


def outcome_frame(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(OUTCOME_COLUMNS))
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


def load_scores(client, bucket: str, prefix: str, dates: list[datetime.date]) -> pd.DataFrame:
    """Every graded head's scores from the partitions in `dates`, with the instant each one became
    servable. Missing partitions are ordinary: a day the training job did not run scored nobody."""
    frames: list[pd.DataFrame] = []
    for date in dates:
        key = date.isoformat()
        # Read whole rather than by column list: an object written before `model_name` existed
        # has no such column, and `with_model_names` is what fills it in.
        table = read_parquet_if_exists(client, bucket, partition_object_key(prefix, UNSEEN_SCORES_TABLE, key))
        if table is None or table.num_rows == 0:
            continue
        # Down to the graded heads before the frame is kept: a partition holds a row per readable
        # head, this read grades two of the seven, and the whole lookback window is held at once.
        frame = with_model_names(table.to_pandas())[list(SCORE_JOIN_COLUMNS)]
        frames.append(frame.loc[frame["head"].isin(OUTCOMES)])
    if not frames:
        return pd.DataFrame(columns=[*SCORE_JOIN_COLUMNS, "available_at"])
    scores = pd.concat(frames, ignore_index=True)
    return scores.assign(available_at=score_available_at(scores["snapshot_date"]))


def grade_rows(
    grades: list[RankingGrade],
    *,
    partition_key: str,
    served_rows: int,
    served_lists: int,
    run_coverage: float | None,
) -> list[dict[str, object]]:
    return [
        {
            **grade.as_dict(),
            "snapshot_date": datetime.date.fromisoformat(partition_key),
            "served_rows": served_rows,
            "served_lists": served_lists,
            "run_score_coverage": run_coverage,
        }
        for grade in grades
    ]


def grade_metadata(grades: list[RankingGrade]) -> dict[str, dagster.MetadataValue]:
    """One entry per (model, outcome, order, metric), so the three orders of a day are readable
    side by side on the materialization."""
    metadata: dict[str, dagster.MetadataValue] = {}
    for grade in grades:
        for name, value in grade.metrics().items():
            if value is None:
                continue
            key = f"{grade.outcome}_{grade.model_name}_{grade.model_role}_{grade.ranking_order}_{name}"
            metadata[key] = (
                dagster.MetadataValue.int(value) if isinstance(value, int) else dagster.MetadataValue.float(value)
            )
    return metadata


@dagster.asset(
    name=SHADOW_TABLE,
    deps=[dagster.AssetDep(UNSEEN_SCORES_TABLE, partition_mapping=_SCORE_LOOKBACK_MAPPING)],
    group_name="inbox_ranking_shadow",
    partitions_def=partition_def,
    tags=owner_tags,
    retry_policy=dagster.RetryPolicy(max_retries=2, delay=60),
    pool="inbox_ranking_etl",
)
def inbox_ranking_shadow_eval(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()
    day = datetime.date.fromisoformat(partition_key)
    window_start, window_end = snapshot_bounds(partition_key)

    _tag_dagster_queries(context)
    team = labels_team()
    impressions = impression_frame(
        hogql_rows(
            IMPRESSION_LISTS_SQL,
            team=team,
            query_type="inbox_ranking_shadow_impressions",
            window_start=window_start,
            window_end=window_end,
        )
    )
    outcomes = outcome_frame(
        hogql_rows(
            OUTCOMES_SQL,
            team=team,
            query_type="inbox_ranking_shadow_outcomes",
            window_start=window_start,
            # An engagement with a list served just before midnight lands on the next day, so the
            # outcome window runs one attribution window past the impression window.
            window_end=window_end + ATTRIBUTION_WINDOW,
        )
    )

    lists = deduplicate_lists(with_outcomes(impressions, outcomes))
    scores = load_scores(
        client,
        bucket,
        prefix,
        [
            day - datetime.timedelta(days=offset)
            for offset in range(settings.INBOX_RANKING_SHADOW_SCORE_LOOKBACK_DAYS, 0, -1)
        ],
    )
    joined = join_scores(lists, scores)
    served_rows = len(lists)
    coverage = score_coverage(served_rows, joined)
    grades = grade_lists(joined, served=lists)
    served_lists = int(lists["impression_id"].nunique()) if not lists.empty else 0

    rows = grade_rows(
        grades,
        partition_key=partition_key,
        served_rows=served_rows,
        served_lists=served_lists,
        run_coverage=coverage,
    )
    key = partition_object_key(prefix, SHADOW_TABLE, partition_key)
    write_parquet(client, bucket, key, pa.Table.from_pylist(rows, schema=GRADE_SCHEMA), snapshot_date=partition_key)

    for grade in grades:
        context.log.info(f"shadow grade: {grade.as_dict()}")
    if not grades:
        context.log.warning(
            f"dt={partition_key} graded nothing: {served_lists} lists, {served_rows} served rows, "
            f"{len(scores)} scores in the lookback window"
        )
    context.add_output_metadata(
        {
            "served_lists": dagster.MetadataValue.int(served_lists),
            "served_rows": dagster.MetadataValue.int(served_rows),
            # The number the read rests on. A day whose lists were mostly unscored says little
            # about either order; the residual is reports impressed on their birth day, which the
            # daily job cannot have scored yet. `grade_metadata` carries each grade's own share.
            "run_score_coverage": dagster.MetadataValue.float(coverage if coverage is not None else 0.0),
            **grade_metadata(grades),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )
    capture_training_events(
        context,
        partition_key,
        shadow_grade_events(
            run_id=context.run.run_id,
            served_rows=served_rows,
            served_lists=served_lists,
            run_score_coverage=coverage,
            grades=grades,
        ),
    )


inbox_ranking_shadow_job = dagster.define_asset_job(
    name="inbox_ranking_shadow_job",
    selection=[SHADOW_TABLE],
    partitions_def=partition_def,
    tags={**owner_tags, "dagster/max_runtime": str(60 * 60)},
)


# Runs after the training job's own budget, so dt=D-1's scores are written before the day that
# needs them next; this read itself only ever uses scores from before its own partition.
@dagster.schedule(
    cron_schedule="30 9 * * *",
    job=inbox_ranking_shadow_job,
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING
    if settings.CLOUD_DEPLOYMENT == "US"
    else dagster.DefaultScheduleStatus.STOPPED,
    tags=owner_tags,
)
def inbox_ranking_shadow_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> dagster.RunRequest | dagster.SkipReason:
    if dataset_unconfigured():
        return dagster.SkipReason(f"{S3_BUCKET_ENV} is not set; skipping until the dedicated bucket is provisioned")
    previous_day = context.scheduled_execution_time.date() - datetime.timedelta(days=1)
    return dagster.RunRequest(partition_key=previous_day.isoformat(), run_key=f"shadow-{previous_day.isoformat()}")
