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
frozen champion. Every candidate is kept under `models/v1/dt=D/`; a re-run of a partition replaces
that prefix in full (stale head files are removed), and `champion.json` carries the `run_id` it
was promoted from so a loader can tell a re-run apart from the version it pinned. The champion is
graded on the candidate's holdout through its `<head>.holdout.ubj` (the train-only fit), so the
promotion rule compares both models on one set of reports.
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
    PROVENANCE_LABEL_COLUMNS,
    PROVENANCE_STATE_COLUMNS,
    STATE_COLUMNS,
    Snapshot,
    assemble_snapshot,
    build_examples,
    point_in_time_mask,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS, HEADS_BY_NAME
from products.signals.dags.inbox_ranking.training.promotion import decide_promotion
from products.signals.dags.inbox_ranking.training.train import XGB_PARAMS, TrainedHead, booster_holdout_auc, train_head

EXAMPLES_TABLE = "inbox_ranking_training_examples"
MODELS_TABLE = "inbox_ranking_models"
CHAMPION_FILE = "champion.json"
METADATA_FILE = "metadata.json"

# Label columns the heads read (plus the provenance inputs); everything else stays on disk.
_LABEL_COLUMNS = (
    "impression_unit_count",
    "open_count",
    "create_pr_click_count",
    "discuss_count",
    "dismissal_reason",
    "wrong_dismissal_count",
    "pr_created_count",
    *PROVENANCE_LABEL_COLUMNS,
)
_STATE_READ_COLUMNS = (*STATE_COLUMNS, *PROVENANCE_STATE_COLUMNS, "features_observed_at")

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


def _read_bytes_if_exists(client, bucket: str, key: str) -> bytes | None:
    try:
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def _read_json_if_exists(client, bucket: str, key: str) -> dict[str, Any] | None:
    body = _read_bytes_if_exists(client, bucket, key)
    return None if body is None else json.loads(body)


def _delete_other_objects(client, bucket: str, folder: str, keep: set[str]) -> list[str]:
    """Delete every object under `folder` whose key is not in `keep`; returns the deleted keys."""
    stale = [
        obj["Key"]
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=folder)
        for obj in page.get("Contents", [])
        if obj["Key"] not in keep
    ]
    if stale:
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": key} for key in stale]})
    return stale


def _put_json(client, bucket: str, key: str, payload: dict[str, Any]) -> None:
    client.put_object(
        Bucket=bucket, Key=key, Body=json.dumps(payload, indent=2).encode(), ContentType="application/json"
    )


def snapshot_dates(partition_key: str, lookback_days: int) -> list[datetime.date]:
    end = datetime.date.fromisoformat(partition_key)
    return [end - datetime.timedelta(days=offset) for offset in range(lookback_days, -1, -1)]


def load_snapshots(
    client, bucket: str, prefix: str, dates: list[datetime.date], *, required: datetime.date | None = None
) -> dict[datetime.date, Snapshot]:
    """The report-state and labels snapshots that exist for `dates`, indexed by report_id. Days
    missing either object are skipped: the example builder treats a gap as unknowable labels.
    `required` is the one day that must be present; the training job is scheduled independently
    of the dataset job, so without it a failed dataset run would yield a candidate named after a
    day it never saw."""
    snapshots: dict[datetime.date, Snapshot] = {}
    for date in dates:
        key = date.isoformat()
        state = read_parquet_if_exists(client, bucket, partition_object_key(prefix, STATE_TABLE, key))
        labels = read_parquet_if_exists(client, bucket, partition_object_key(prefix, LABELS_TABLE, key))
        if state is None or labels is None:
            continue
        state_columns = [column for column in _STATE_READ_COLUMNS if column in state.column_names]
        state_frame = state.select(["report_id", *state_columns]).to_pandas().set_index("report_id")
        label_columns = [column for column in _LABEL_COLUMNS if column in labels.column_names]
        labels_frame = labels.select(["report_id", *label_columns]).to_pandas().set_index("report_id")
        snapshots[date] = assemble_snapshot(date, state_frame, labels_frame)
    if required is not None and required not in snapshots:
        raise dagster.Failure(f"state and labels snapshots for {required.isoformat()} are required but missing")
    return snapshots


def examples_table(examples: pd.DataFrame) -> pa.Table:
    return pa.Table.from_pandas(examples[list(EXAMPLE_COLUMNS)], preserve_index=False)


# The examples for dt=D read every snapshot back to D-lookback. The default same-partition mapping
# would let an asset backfill run examples(D) as soon as state(D) and labels(D) exist, while the
# older days it needs are still pending. Partitions before the label epoch have no upstream to map to.
_LOOKBACK_MAPPING = dagster.TimeWindowPartitionMapping(
    start_offset=-settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS,
    end_offset=0,
    allow_nonexistent_upstream_partitions=True,
)


@dagster.asset(
    name=EXAMPLES_TABLE,
    deps=[
        dagster.AssetDep(STATE_TABLE, partition_mapping=_LOOKBACK_MAPPING),
        dagster.AssetDep(LABELS_TABLE, partition_mapping=_LOOKBACK_MAPPING),
    ],
    **COMMON_ASSET_KWARGS,
)
def inbox_ranking_training_examples(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()

    dates = snapshot_dates(partition_key, settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS)
    snapshots = load_snapshots(client, bucket, prefix, dates, required=dates[-1])
    context.log.info(f"{len(snapshots)} of {len(dates)} snapshots present")
    backfilled_rows = sum(int((~point_in_time_mask(snap.state, snap.date)).sum()) for snap in snapshots.values())
    if backfilled_rows:
        context.log.warning(f"{backfilled_rows} state rows read after the snapshot window are excluded (backfill)")

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
            "backfilled_state_rows_excluded": dagster.MetadataValue.int(backfilled_rows),
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
        "heads": [
            head.metrics.as_dict()
            | {
                "file": f"{head.head}.ubj",
                "holdout_file": f"{head.head}.holdout.ubj" if head.holdout_booster_ubj is not None else None,
            }
            for head in trained
        ],
    }


def paired_champion_aucs(
    client, bucket: str, prefix: str, champion: dict[str, Any], examples: pd.DataFrame, *, holdout_days: int
) -> dict[str, float]:
    """The champion's readable heads graded on the candidate's holdout, through the champion's saved
    holdout boosters. Heads without a saved holdout booster are left out and fall back to the
    champion's stored AUC in `decide_promotion`."""
    aucs: dict[str, float] = {}
    for entry in champion.get("heads", []):
        head = HEADS_BY_NAME.get(entry.get("head"))
        if head is None or not entry.get("readable") or not entry.get("holdout_file"):
            continue
        body = _read_bytes_if_exists(
            client, bucket, model_object_key(prefix, champion["model_version"], entry["holdout_file"])
        )
        if body is None:
            continue
        auc = booster_holdout_auc(body, examples, head, holdout_days=holdout_days)
        if auc is not None:
            aucs[head.name] = auc
    return aucs


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

    written: set[str] = set()
    for model in trained:
        files = {f"{model.head}.ubj": model.booster_ubj}
        if model.holdout_booster_ubj is not None:
            files[f"{model.head}.holdout.ubj"] = model.holdout_booster_ubj
        for filename, body in files.items():
            key = model_object_key(prefix, partition_key, filename)
            client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/octet-stream")
            written.add(key)
    metadata = candidate_metadata(
        partition_key, trained, trained_at=datetime.datetime.now(datetime.UTC), run_id=context.run.run_id
    )
    metadata_key = model_object_key(prefix, partition_key, METADATA_FILE)
    _put_json(client, bucket, metadata_key, metadata)
    written.add(metadata_key)
    # A re-run that trains fewer heads must not leave the previous run's files behind.
    stale = _delete_other_objects(client, bucket, model_object_key(prefix, partition_key, ""), written)
    if stale:
        context.log.warning(f"removed {len(stale)} stale objects from a previous run of dt={partition_key}")
    context.add_output_metadata(
        {
            "stale_objects_removed": dagster.MetadataValue.int(len(stale)),
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
    champion_aucs: dict[str, float] = {}
    if champion is not None:
        examples = read_parquet(client, bucket, partition_object_key(prefix, EXAMPLES_TABLE, partition_key)).to_pandas()
        champion_aucs = paired_champion_aucs(
            client, bucket, prefix, champion, examples, holdout_days=settings.INBOX_RANKING_TRAINING_HOLDOUT_DAYS
        )
        context.log.info(f"champion {champion['model_version']} on this holdout: {champion_aucs}")
    decision = decide_promotion(
        candidate,
        champion,
        now=datetime.datetime.now(datetime.UTC),
        min_days_between=settings.INBOX_RANKING_PROMOTION_MIN_DAYS,
        champion_aucs=champion_aucs,
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
            **{
                f"champion_{head}_auc_on_this_holdout": dagster.MetadataValue.float(auc)
                for head, auc in champion_aucs.items()
            },
            "champion_version": dagster.MetadataValue.text(
                partition_key if promoted else (champion or {}).get("model_version", "none")
            ),
        }
    )


inbox_ranking_training_job = dagster.define_asset_job(
    name="inbox_ranking_training_job",
    selection=[EXAMPLES_TABLE, "inbox_ranking_model_candidate", "inbox_ranking_model_champion"],
    partitions_def=partition_def,
    tags={
        **owner_tags,
        "dagster/max_runtime": str(2 * 60 * 60),
        # The examples asset holds every snapshot of the lookback window in pandas at once (state
        # plus labels per day) before the per-head builders run, so the peak grows with the
        # lookback and the inventory. Sized like the dataset job rather than left at the 8Gi
        # default so growth surfaces as a slow run, not an OOMKilled pod.
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"memory": "8Gi"},
                    "limits": {"memory": "16Gi"},
                }
            }
        },
    },
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
