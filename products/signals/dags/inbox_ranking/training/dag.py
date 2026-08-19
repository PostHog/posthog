"""Daily training for the Self-driving Inbox report-ranking model (v0: per-head XGBoost).

Three assets on the same daily partition as the dataset dag, each writing under the dataset prefix:

    inbox_ranking_training_examples/v1/dt=D/   scoring-moment examples over the trailing snapshots
    inbox_ranking_models/v1/dt=D/<head>.ubj    one booster per head + metadata.json (the candidate)
    inbox_ranking_models/v1/champion.json      pointer to the model version the scoring sweep loads

Partition dt=D trains on the report-state/labels snapshots dt=D-lookback..D (issue 13's
scoring-moment join, `training/examples.py`), grades each head on the last `holdout_days` of
reports, and refits on everything. The champion asset applies `promotion.decide_promotion`; it
rewrites the pointer only when `INBOX_RANKING_AUTO_PROMOTE` is on, otherwise it logs the decision
so the daily candidate series doubles as monitoring while the first shadow read runs against a
frozen champion. Every candidate is kept: `models/v1/dt=D/` is immutable history like the dataset
partitions, and the pointer is the only mutable object.
"""

import json
import datetime
from typing import Any

import pandas as pd
import dagster
import pyarrow as pa
from botocore.exceptions import ClientError

from posthog import settings

from products.signals.backend.ranking.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from products.signals.dags.inbox_ranking.common import (
    DATASET_VERSION,
    S3_BUCKET_ENV,
    dataset_bucket,
    dataset_unconfigured,
    owner_tags,
    partition_def,
    partition_object_key,
    read_parquet,
    read_parquet_if_exists,
    s3_client,
    skip_unconfigured,
    write_parquet,
)
from products.signals.dags.inbox_ranking.dataset.dag import LABELS_TABLE, STATE_TABLE
from products.signals.dags.inbox_ranking.training.examples import (
    EXAMPLE_COLUMNS,
    STATE_COLUMNS,
    Snapshot,
    build_examples,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS
from products.signals.dags.inbox_ranking.training.promotion import decide_promotion
from products.signals.dags.inbox_ranking.training.train import XGB_PARAMS, TrainedHead, train_head

EXAMPLES_TABLE = "inbox_ranking_training_examples"
MODELS_TABLE = "inbox_ranking_models"
CHAMPION_FILE = "champion.json"
METADATA_FILE = "metadata.json"

# Label columns the heads read; everything else in the labels snapshot stays on disk.
_LABEL_COLUMNS = (
    "impression_unit_count",
    "open_count",
    "create_pr_click_count",
    "discuss_count",
    "dismissal_reason",
    "pr_created_count",
)

COMMON_ASSET_KWARGS: dict[str, Any] = {
    "group_name": "inbox_ranking_training",
    "partitions_def": partition_def,
    "tags": owner_tags,
    "retry_policy": dagster.RetryPolicy(max_retries=1, delay=60),
    "pool": "inbox_ranking_etl",
}


def model_object_key(prefix: str, partition_key: str, filename: str) -> str:
    return f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/dt={partition_key}/{filename}"


def champion_object_key(prefix: str) -> str:
    return f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/{CHAMPION_FILE}"


def _read_json_if_exists(client, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return json.loads(body)


def _put_json(client, bucket: str, key: str, payload: dict[str, Any]) -> None:
    client.put_object(
        Bucket=bucket, Key=key, Body=json.dumps(payload, indent=2).encode(), ContentType="application/json"
    )


def snapshot_dates(partition_key: str, lookback_days: int) -> list[datetime.date]:
    end = datetime.date.fromisoformat(partition_key)
    return [end - datetime.timedelta(days=offset) for offset in range(lookback_days, -1, -1)]


def load_snapshots(client, bucket: str, prefix: str, dates: list[datetime.date]) -> dict[datetime.date, Snapshot]:
    """The report-state and labels snapshots that exist for `dates`, indexed by report_id. Days
    missing either object are skipped: the example builder treats a gap as unknowable labels."""
    snapshots: dict[datetime.date, Snapshot] = {}
    for date in dates:
        key = date.isoformat()
        state = read_parquet_if_exists(client, bucket, partition_object_key(prefix, STATE_TABLE, key))
        labels = read_parquet_if_exists(client, bucket, partition_object_key(prefix, LABELS_TABLE, key))
        if state is None or labels is None:
            continue
        state_frame = state.select(["report_id", *STATE_COLUMNS]).to_pandas().set_index("report_id")
        label_columns = [column for column in _LABEL_COLUMNS if column in labels.column_names]
        labels_frame = labels.select(["report_id", *label_columns]).to_pandas().set_index("report_id")
        snapshots[date] = Snapshot(date=date, state=state_frame, labels=labels_frame)
    return snapshots


def examples_table(examples: pd.DataFrame) -> pa.Table:
    return pa.Table.from_pandas(examples[list(EXAMPLE_COLUMNS)], preserve_index=False)


@dagster.asset(name=EXAMPLES_TABLE, deps=[STATE_TABLE, LABELS_TABLE], **COMMON_ASSET_KWARGS)
def inbox_ranking_training_examples(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()

    dates = snapshot_dates(partition_key, settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS)
    snapshots = load_snapshots(client, bucket, prefix, dates)
    context.log.info(f"{len(snapshots)} of {len(dates)} snapshots present")

    per_head = {head.name: build_examples(snapshots, head) for head in HEADS}
    examples = (
        pd.concat(per_head.values(), ignore_index=True) if per_head else pd.DataFrame(columns=list(EXAMPLE_COLUMNS))
    )

    key = partition_object_key(prefix, EXAMPLES_TABLE, partition_key)
    write_parquet(client, bucket, key, examples_table(examples), snapshot_date=partition_key)
    context.add_output_metadata(
        {
            "rows": dagster.MetadataValue.int(len(examples)),
            "snapshots": dagster.MetadataValue.int(len(snapshots)),
            **{f"{name}_rows": dagster.MetadataValue.int(len(frame)) for name, frame in per_head.items()},
            **{
                f"{name}_positives": dagster.MetadataValue.int(int(frame["label"].sum()))
                for name, frame in per_head.items()
            },
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


def candidate_metadata(
    partition_key: str, trained: list[TrainedHead], *, trained_at: datetime.datetime, run_id: str
) -> dict[str, Any]:
    return {
        "model_version": partition_key,
        "dataset_version": DATASET_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "trained_at": trained_at.isoformat(),
        "run_id": run_id,
        "lookback_days": settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS,
        "holdout_days": settings.INBOX_RANKING_TRAINING_HOLDOUT_DAYS,
        "xgb_params": XGB_PARAMS,
        "heads": [head.metrics.as_dict() | {"file": f"{head.head}.ubj"} for head in trained],
    }


@dagster.asset(name="inbox_ranking_model_candidate", deps=[EXAMPLES_TABLE], **COMMON_ASSET_KWARGS)
def inbox_ranking_model_candidate(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()

    examples = read_parquet(client, bucket, partition_object_key(prefix, EXAMPLES_TABLE, partition_key)).to_pandas()
    trained: list[TrainedHead] = []
    for head in HEADS:
        result = train_head(examples, head, holdout_days=settings.INBOX_RANKING_TRAINING_HOLDOUT_DAYS)
        if result is None:
            context.log.warning(f"{head.name}: nothing to fit, skipped")
            continue
        context.log.info(f"{head.name}: {result.metrics.as_dict()}")
        trained.append(result)

    for model in trained:
        client.put_object(
            Bucket=bucket,
            Key=model_object_key(prefix, partition_key, f"{model.head}.ubj"),
            Body=model.booster_ubj,
            ContentType="application/octet-stream",
        )
    metadata = candidate_metadata(
        partition_key, trained, trained_at=datetime.datetime.now(datetime.UTC), run_id=context.run.run_id
    )
    metadata_key = model_object_key(prefix, partition_key, METADATA_FILE)
    _put_json(client, bucket, metadata_key, metadata)
    context.add_output_metadata(
        {
            "heads_trained": dagster.MetadataValue.int(len(trained)),
            "heads_readable": dagster.MetadataValue.int(sum(1 for head in trained if head.metrics.readable)),
            **{
                f"{head.head}_holdout_auc": dagster.MetadataValue.float(head.metrics.holdout_auc)
                for head in trained
                if head.metrics.holdout_auc is not None
            },
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{metadata_key}"),
        }
    )


@dagster.asset(name="inbox_ranking_model_champion", deps=["inbox_ranking_model_candidate"], **COMMON_ASSET_KWARGS)
def inbox_ranking_model_champion(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()

    candidate = _read_json_if_exists(client, bucket, model_object_key(prefix, partition_key, METADATA_FILE))
    if candidate is None:
        raise dagster.Failure(f"candidate metadata for dt={partition_key} is missing")
    champion_key = champion_object_key(prefix)
    champion = _read_json_if_exists(client, bucket, champion_key)
    decision = decide_promotion(
        candidate,
        champion,
        now=datetime.datetime.now(datetime.UTC),
        min_days_between=settings.INBOX_RANKING_PROMOTION_MIN_DAYS,
    )
    context.log.info(f"promotion decision for dt={partition_key}: promote={decision.promote} ({decision.reason})")

    promoted = False
    if decision.promote and settings.INBOX_RANKING_AUTO_PROMOTE:
        _put_json(
            client,
            bucket,
            champion_key,
            {
                **candidate,
                "promoted_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "metadata_key": model_object_key(prefix, partition_key, METADATA_FILE),
            },
        )
        promoted = True
    elif decision.promote:
        context.log.info("INBOX_RANKING_AUTO_PROMOTE is off; candidate would have been promoted")

    context.add_output_metadata(
        {
            "would_promote": dagster.MetadataValue.bool(decision.promote),
            "promoted": dagster.MetadataValue.bool(promoted),
            "reason": dagster.MetadataValue.text(decision.reason),
            "champion_version": dagster.MetadataValue.text(
                partition_key if promoted else (champion or {}).get("model_version", "none")
            ),
        }
    )


inbox_ranking_training_job = dagster.define_asset_job(
    name="inbox_ranking_training_job",
    selection=[EXAMPLES_TABLE, "inbox_ranking_model_candidate", "inbox_ranking_model_champion"],
    partitions_def=partition_def,
    tags={**owner_tags, "dagster/max_runtime": str(2 * 60 * 60)},
)


# Runs after the dataset job's 3h budget (02:30 UTC start) so dt=D-1's snapshots exist.
@dagster.schedule(
    cron_schedule="0 6 * * *",
    job=inbox_ranking_training_job,
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING
    if settings.CLOUD_DEPLOYMENT == "US"
    else dagster.DefaultScheduleStatus.STOPPED,
    tags=owner_tags,
)
def inbox_ranking_training_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> dagster.RunRequest | dagster.SkipReason:
    if dataset_unconfigured():
        return dagster.SkipReason(f"{S3_BUCKET_ENV} is not set; skipping until the dedicated bucket is provisioned")
    previous_day = context.scheduled_execution_time.date() - datetime.timedelta(days=1)
    return dagster.RunRequest(partition_key=previous_day.isoformat(), run_key=f"training-{previous_day.isoformat()}")
