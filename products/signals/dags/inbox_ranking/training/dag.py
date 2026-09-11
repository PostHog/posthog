"""Daily training for the Self-driving Inbox report-ranking model (v0: per-head XGBoost).

Three assets on the same daily partition as the dataset dag, each writing under the dataset prefix:

    inbox_ranking_training_examples/v1/dt=D/          scoring-moment examples over the trailing snapshots
    inbox_ranking_models/v1/<name>/dt=D/<head>.ubj    one booster per head + metadata.json (the candidate)
    inbox_ranking_models/v1/<name>/champion.json      pointer to the version the scoring sweep loads
    inbox_ranking_unseen_scores/v1/dt=D/              the day's models on the reports born that day

Partition dt=D trains on the report-state/labels snapshots dt=D-lookback..D (issue 13's
scoring-moment join, `training/examples.py`), grades each head on the last `holdout_days` of
reports, and refits on everything. The champion asset applies `promotion.decide_promotion`; it
rewrites the pointer only when `INBOX_RANKING_AUTO_PROMOTE` is on, otherwise it logs the decision
so the daily candidate series doubles as monitoring while the first shadow read runs against a
frozen champion. Every candidate is kept under `models/v1/<model_name>/dt=D/`; a re-run of a partition replaces
that prefix in full (stale head files are removed), and `champion.json` carries the `run_id` it
was promoted from so a loader can tell a re-run apart from the version it pinned. The champion is
graded on the candidate's holdout through its `<head>.holdout.ubj` (the train-only fit), so the
promotion rule compares both models on one set of reports. Every model object sits under its
family's `model_name`, and promotion stays inside a family: a richer family is a second candidate
graded on the same rows, not a competitor for the tabular family's pointer.

Two further assets grade the day's models on data no example covers. `inbox_ranking_unseen_scores`
scores every report born on D (`unseen_pool` explains why no example can cover one);
`inbox_ranking_unseen_graded` reads each head's scores from `D - horizon_days` and grades them
against the dt=D labels. The holdout AUC grades the recipe, because the shipped booster is refit on
train plus holdout; the unseen AUC grades the model on reports it never saw, and the two are
comparable because both apply the same `Head` cohort, label and horizon.
"""

import json
import datetime
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import dagster
import pyarrow as pa
from botocore.exceptions import ClientError

from posthog import settings

from products.signals.backend.ranking.features import FEATURE_SETS, TABULAR_FEATURE_SET, FeatureSet
from products.signals.dags.inbox_ranking.common import (
    DATASET_VERSION,
    PARQUET_PART_NAME,
    S3_BUCKET_ENV,
    dataset_bucket,
    dataset_unconfigured,
    object_row_count,
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
    BASE_STATE_COLUMNS,
    PROVENANCE_LABEL_COLUMNS,
    PROVENANCE_STATE_COLUMNS,
    Snapshot,
    assemble_snapshot,
    build_examples,
    example_columns,
    point_in_time_mask,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS, HEADS_BY_HORIZON, HEADS_BY_NAME
from products.signals.dags.inbox_ranking.training.promotion import decide_promotion
from products.signals.dags.inbox_ranking.training.telemetry import (
    HeadExampleCounts,
    candidate_events,
    capture_training_events,
    examples_events,
    promotion_event,
    unseen_head_graded_events,
    unseen_report_graded_events,
    unseen_score_events,
)
from products.signals.dags.inbox_ranking.training.train import XGB_PARAMS, TrainedHead, booster_holdout_auc, train_head
from products.signals.dags.inbox_ranking.training.unseen import (
    CANDIDATE_ROLE,
    CHAMPION_ROLE,
    MODEL_FAMILIES,
    TABULAR_MODEL_NAME,
    HeadGrade,
    UnseenModel,
    empty_scores_write_allowed,
    graded_rows,
    head_grades,
    leaked_report_ids,
    missing_label_columns,
    model_feature_set,
    model_mismatch,
    readable_head_files,
    report_grade_rows,
    score_event_rows,
    score_pool,
    scored_pool,
    scores_table,
    unseen_pool,
    with_model_names,
)

EXAMPLES_TABLE = "inbox_ranking_training_examples"
UNSEEN_SCORES_TABLE = "inbox_ranking_unseen_scores"
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
    "pr_merged_count",
    "refund_count",
    *PROVENANCE_LABEL_COLUMNS,
)
# Every registered feature set's columns in one read: the state snapshot is loaded once and every
# set builds its examples from it.
_STATE_READ_COLUMNS = tuple(
    dict.fromkeys(
        (
            *BASE_STATE_COLUMNS,
            *(column for feature_set in FEATURE_SETS.values() for column in feature_set.state_columns),
            *PROVENANCE_STATE_COLUMNS,
            "features_observed_at",
        )
    )
)

COMMON_ASSET_KWARGS: dict[str, Any] = {
    "group_name": "inbox_ranking_training",
    "partitions_def": partition_def,
    "tags": owner_tags,
    "retry_policy": dagster.RetryPolicy(max_retries=1, delay=60),
    "pool": "inbox_ranking_etl",
}


def examples_object_key(prefix: str, feature_set_name: str, partition_key: str) -> str:
    """One examples object per feature set: two sets carry different feature columns, so they
    cannot share a Parquet, and a family trains on the object of the set it declares."""
    return f"{prefix}/{EXAMPLES_TABLE}/{DATASET_VERSION}/{feature_set_name}/dt={partition_key}/{PARQUET_PART_NAME}"


def model_object_key(prefix: str, model_name: str, partition_key: str, filename: str) -> str:
    return f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/{model_name}/dt={partition_key}/{filename}"


def champion_object_key(prefix: str, model_name: str) -> str:
    return f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/{model_name}/{CHAMPION_FILE}"


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


def examples_table(examples: pd.DataFrame, feature_set: FeatureSet) -> pa.Table:
    return pa.Table.from_pandas(examples[list(example_columns(feature_set))], preserve_index=False)


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

    metadata: dict[str, dagster.MetadataValue] = {
        "snapshots": dagster.MetadataValue.int(len(snapshots)),
        "backfilled_state_rows_excluded": dagster.MetadataValue.int(backfilled_rows),
    }
    for feature_set in FEATURE_SETS.values():
        metadata |= _write_examples(
            context, client, bucket, prefix, partition_key, feature_set, snapshots, backfilled_rows
        )
    context.add_output_metadata(metadata)


def _write_examples(
    context: dagster.AssetExecutionContext,
    client,
    bucket: str,
    prefix: str,
    partition_key: str,
    feature_set: FeatureSet,
    snapshots: Mapping[datetime.date, Snapshot],
    backfilled_rows: int,
) -> dict[str, dagster.MetadataValue]:
    """One feature set's examples for the partition, as its own object and its own events, with
    the asset metadata to record for it."""
    per_head = {head.name: build_examples(snapshots, head, feature_set) for head in HEADS}
    examples = (
        pd.concat(per_head.values(), ignore_index=True)
        if per_head
        else pd.DataFrame(columns=list(example_columns(feature_set)))
    )

    key = examples_object_key(prefix, feature_set.name, partition_key)
    write_parquet(client, bucket, key, examples_table(examples, feature_set), snapshot_date=partition_key)
    counts = {
        name: HeadExampleCounts(rows=len(frame), positives=int(frame["label"].sum()))
        for name, frame in per_head.items()
    }
    metadata: dict[str, dagster.MetadataValue] = {
        f"{feature_set.name}_rows": dagster.MetadataValue.int(len(examples)),
        **{
            f"{feature_set.name}_{name}_rows": dagster.MetadataValue.int(head_counts.rows)
            for name, head_counts in counts.items()
        },
        **{
            f"{feature_set.name}_{name}_positives": dagster.MetadataValue.int(head_counts.positives)
            for name, head_counts in counts.items()
        },
        f"{feature_set.name}_s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
    }
    capture_training_events(
        context,
        partition_key,
        examples_events(
            partition_key=partition_key,
            run_id=context.run.run_id,
            feature_set=feature_set.name,
            snapshots=len(snapshots),
            backfilled_rows=backfilled_rows,
            per_head=counts,
        ),
    )
    return metadata


def candidate_metadata(
    partition_key: str,
    trained: list[TrainedHead],
    *,
    model_name: str,
    feature_set: FeatureSet,
    skipped: list[str],
    trained_at: datetime.datetime,
    run_id: str,
) -> dict[str, Any]:
    return {
        "model_name": model_name,
        "model_version": partition_key,
        "dataset_version": DATASET_VERSION,
        # The feature universe this model was fit on. The grader checks the model against this set
        # rather than against one global contract, so a second family is not rejected for reading
        # different features.
        "feature_set": feature_set.name,
        "feature_schema_version": feature_set.schema_version,
        "feature_names": list(feature_set.feature_names),
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
        # Heads with nothing to fit on this partition; recorded so the per-head series has no gap.
        "skipped_heads": skipped,
    }


def paired_champion_aucs(
    client,
    bucket: str,
    prefix: str,
    champion: dict[str, Any],
    examples: pd.DataFrame,
    *,
    feature_set: FeatureSet,
    holdout_days: int,
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
            client,
            bucket,
            model_object_key(prefix, champion["model_name"], champion["model_version"], entry["holdout_file"]),
        )
        if body is None:
            continue
        auc = booster_holdout_auc(
            body, examples, head, feature_names=feature_set.feature_names, holdout_days=holdout_days
        )
        if auc is not None:
            aucs[head.name] = auc
    return aucs


@dagster.asset(name="inbox_ranking_model_candidate", deps=[EXAMPLES_TABLE], **COMMON_ASSET_KWARGS)
def inbox_ranking_model_candidate(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()

    feature_set = TABULAR_FEATURE_SET
    examples = read_parquet(client, bucket, examples_object_key(prefix, feature_set.name, partition_key)).to_pandas()
    trained: list[TrainedHead] = []
    skipped: list[str] = []
    for head in HEADS:
        result = train_head(
            examples,
            head,
            feature_names=feature_set.feature_names,
            holdout_days=settings.INBOX_RANKING_TRAINING_HOLDOUT_DAYS,
        )
        if result is None:
            context.log.warning(f"{head.name}: nothing to fit, skipped")
            skipped.append(head.name)
            continue
        context.log.info(f"{head.name}: {result.metrics.as_dict()}")
        trained.append(result)

    written: set[str] = set()
    for model in trained:
        files = {f"{model.head}.ubj": model.booster_ubj}
        if model.holdout_booster_ubj is not None:
            files[f"{model.head}.holdout.ubj"] = model.holdout_booster_ubj
        for filename, body in files.items():
            key = model_object_key(prefix, TABULAR_MODEL_NAME, partition_key, filename)
            client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/octet-stream")
            written.add(key)
    metadata = candidate_metadata(
        partition_key,
        trained,
        model_name=TABULAR_MODEL_NAME,
        feature_set=feature_set,
        skipped=skipped,
        trained_at=datetime.datetime.now(datetime.UTC),
        run_id=context.run.run_id,
    )
    metadata_key = model_object_key(prefix, TABULAR_MODEL_NAME, partition_key, METADATA_FILE)
    _put_json(client, bucket, metadata_key, metadata)
    written.add(metadata_key)
    # A re-run that trains fewer heads must not leave the previous run's files behind.
    stale = _delete_other_objects(
        client, bucket, model_object_key(prefix, TABULAR_MODEL_NAME, partition_key, ""), written
    )
    if stale:
        context.log.warning(f"removed {len(stale)} stale objects from a previous run of dt={partition_key}")
    capture_training_events(context, partition_key, candidate_events(metadata))
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

    candidate = _read_json_if_exists(
        client, bucket, model_object_key(prefix, TABULAR_MODEL_NAME, partition_key, METADATA_FILE)
    )
    if candidate is None:
        raise dagster.Failure(f"candidate metadata for dt={partition_key} is missing")
    champion_key = champion_object_key(prefix, TABULAR_MODEL_NAME)
    champion = _read_json_if_exists(client, bucket, champion_key)
    champion_aucs: dict[str, float] = {}
    if champion is not None:
        champion_feature_set = model_feature_set(champion)
        if champion_feature_set is None:
            context.log.warning(f"champion {champion['model_version']} reads a feature set this build cannot produce")
        else:
            # The champion is graded on the examples of its own feature set, the set the candidate
            # shares: promotion stays inside a family.
            examples = read_parquet(
                client, bucket, examples_object_key(prefix, champion_feature_set.name, partition_key)
            ).to_pandas()
            champion_aucs = paired_champion_aucs(
                client,
                bucket,
                prefix,
                champion,
                examples,
                feature_set=champion_feature_set,
                holdout_days=settings.INBOX_RANKING_TRAINING_HOLDOUT_DAYS,
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
                "metadata_key": model_object_key(prefix, TABULAR_MODEL_NAME, partition_key, METADATA_FILE),
            },
        )
        promoted = True
    elif decision.promote:
        context.log.info("INBOX_RANKING_AUTO_PROMOTE is off; candidate would have been promoted")

    # The paired AUCs belong to the incumbent: after a promotion `champion_version` names the
    # candidate, so the incumbent is recorded alongside to keep the scores attributable.
    incumbent_champion_version = (champion or {}).get("model_version", "none")
    champion_version = partition_key if promoted else incumbent_champion_version
    context.add_output_metadata(
        {
            "would_promote": dagster.MetadataValue.bool(decision.promote),
            "promoted": dagster.MetadataValue.bool(promoted),
            "reason": dagster.MetadataValue.text(decision.reason),
            **{
                f"champion_{head}_auc_on_this_holdout": dagster.MetadataValue.float(auc)
                for head, auc in champion_aucs.items()
            },
            "incumbent_champion_version": dagster.MetadataValue.text(incumbent_champion_version),
            "champion_version": dagster.MetadataValue.text(champion_version),
        }
    )
    capture_training_events(
        context,
        partition_key,
        [
            promotion_event(
                partition_key=partition_key,
                run_id=context.run.run_id,
                model_name=TABULAR_MODEL_NAME,
                decision=decision,
                promoted=promoted,
                champion_version=champion_version,
                incumbent_champion_version=incumbent_champion_version,
                champion_aucs=champion_aucs,
            )
        ],
    )


# dt=D grades the scores written on D - horizon_days, so the mapping reaches back as far as the
# longest head horizon. Partitions before the scores asset existed have no upstream to map to.
_HORIZON_MAPPING = dagster.TimeWindowPartitionMapping(
    start_offset=-max(HEADS_BY_HORIZON),
    end_offset=0,
    allow_nonexistent_upstream_partitions=True,
)


def load_family_models(
    context: dagster.AssetExecutionContext, client, bucket: str, prefix: str, partition_key: str, model_name: str
) -> list[UnseenModel]:
    """One family's models worth an unseen read on dt=D: the day's candidate, plus that family's
    champion when its pointer names a different version. A model whose feature contract has moved
    on is logged and left out rather than failing the asset, because its boosters cannot take the
    current matrix."""
    candidate = _read_json_if_exists(client, bucket, model_object_key(prefix, model_name, partition_key, METADATA_FILE))
    champion = _read_json_if_exists(client, bucket, champion_object_key(prefix, model_name))
    records = [(CANDIDATE_ROLE, candidate)]
    if champion is not None and champion.get("model_version") != (candidate or {}).get("model_version"):
        records.append((CHAMPION_ROLE, champion))

    models: list[UnseenModel] = []
    for role, metadata in records:
        if metadata is None:
            context.log.warning(f"no {model_name} {role} metadata to score the unseen pool with")
            continue
        mismatch = model_mismatch(metadata)
        # A set the mismatch check accepted always resolves; the None arm is there to narrow it.
        feature_set = model_feature_set(metadata)
        if mismatch is not None or feature_set is None:
            context.log.warning(f"{model_name} {role} {metadata.get('model_version')} not scored: {mismatch}")
            continue
        boosters = {}
        for head_name, filename in readable_head_files(metadata).items():
            body = _read_bytes_if_exists(
                client, bucket, model_object_key(prefix, model_name, metadata["model_version"], filename)
            )
            if body is not None:
                boosters[head_name] = body
        if not boosters:
            context.log.warning(f"{model_name} {role} {metadata['model_version']} has no readable head to score")
            continue
        models.append(
            UnseenModel(
                model_name=model_name,
                model_version=metadata["model_version"],
                model_role=role,
                feature_set=feature_set,
                boosters=boosters,
            )
        )
    return models


def load_unseen_models(
    context: dagster.AssetExecutionContext, client, bucket: str, prefix: str, partition_key: str
) -> list[UnseenModel]:
    """Every registered family's models, so one grading run puts every family on the same rows. A
    family with nothing to score that day contributes nothing and does not stop the others: a
    family can be registered before its trainer's first run, and a broken one costs its own series
    rather than every family's."""
    return [
        model
        for model_name in MODEL_FAMILIES
        for model in load_family_models(context, client, bucket, prefix, partition_key, model_name)
    ]


@dagster.asset(
    name=UNSEEN_SCORES_TABLE,
    deps=["inbox_ranking_model_champion", STATE_TABLE, LABELS_TABLE],
    **COMMON_ASSET_KWARGS,
)
def inbox_ranking_unseen_scores(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()
    day = datetime.date.fromisoformat(partition_key)

    snapshot = load_snapshots(client, bucket, prefix, [day], required=day)[day]
    # Only the ids, from every feature set: the examples table is one row per (report, snapshot,
    # head) over the lookback, and a report is leaked if any set trained on it.
    example_ids: set[object] = set()
    for feature_set in FEATURE_SETS.values():
        ids = read_parquet(
            client, bucket, examples_object_key(prefix, feature_set.name, partition_key), columns=["report_id"]
        )
        example_ids.update(ids.column("report_id").unique().to_pylist())
    pool = unseen_pool(snapshot.state, day)
    leaked = leaked_report_ids(pool, example_ids)
    if leaked:
        raise dagster.Failure(
            f"{len(leaked)} reports created on {partition_key} already appear in that day's training examples, "
            f"so the unseen read would grade a model on its own data: {leaked[:10]}"
        )
    models = load_unseen_models(context, client, bucket, prefix, partition_key)
    scores = score_pool(pool, snapshot.labels, models, snapshot_date=day)
    key = partition_object_key(prefix, UNSEEN_SCORES_TABLE, partition_key)
    if scores.empty:
        existing_rows = object_row_count(client, bucket, key)
        if not empty_scores_write_allowed(existing_rows):
            raise dagster.Failure(
                f"{UNSEEN_SCORES_TABLE} dt={partition_key} already holds {existing_rows} rows and this run scored "
                f"none, so writing would destroy the scores the dt=D+horizon grade reads. Candidates are loaded "
                f"from {MODELS_TABLE}/{DATASET_VERSION}/<model_name>/, so a partition trained before that layout "
                f"has no model to score with. To replace the object deliberately, delete it by hand first."
            )
        context.log.warning(f"nothing scored for dt={partition_key}: {len(pool)} newborn reports, {len(models)} models")

    write_parquet(client, bucket, key, scores_table(scores), snapshot_date=partition_key)
    context.add_output_metadata(
        {
            "unseen_pool": dagster.MetadataValue.int(len(pool)),
            "models_scored": dagster.MetadataValue.int(len(models)),
            **{
                f"{model.model_name}_{model.model_role}_heads_scored": dagster.MetadataValue.int(len(model.boosters))
                for model in models
            },
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )
    capture_training_events(
        context,
        partition_key,
        unseen_score_events(run_id=context.run.run_id, rows=score_event_rows(scores, pool)),
    )


def grade_metadata(grades: Sequence[HeadGrade]) -> dict[str, dagster.MetadataValue]:
    """One metadata entry per (head, model, metric). The family is in the key, so two families
    graded on the same rows do not overwrite each other. Counts stay ints: `MetadataValue.float`
    rejects them."""
    metadata: dict[str, dagster.MetadataValue] = {}
    for grade in grades:
        for name, value in grade.metrics().items():
            if value is None:
                continue
            key = f"{grade.head}_{grade.model_name}_{grade.model_role}_{name}"
            metadata[key] = (
                dagster.MetadataValue.int(value) if isinstance(value, int) else dagster.MetadataValue.float(value)
            )
    return metadata


@dagster.asset(
    name="inbox_ranking_unseen_graded",
    deps=[
        dagster.AssetDep(UNSEEN_SCORES_TABLE, partition_mapping=_HORIZON_MAPPING),
        LABELS_TABLE,
    ],
    **COMMON_ASSET_KWARGS,
)
def inbox_ranking_unseen_graded(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()
    day = datetime.date.fromisoformat(partition_key)

    labels = load_snapshots(client, bucket, prefix, [day], required=day)[day].labels
    grades: list[HeadGrade] = []
    skipped: dict[str, str] = {}
    report_rows: list[dict[str, object]] = []
    # Walk the horizons, not the heads: heads that share a horizon read the same scores object.
    for horizon_days, heads in HEADS_BY_HORIZON.items():
        scoring_partition = (day - datetime.timedelta(days=horizon_days)).isoformat()
        table = read_parquet_if_exists(
            client, bucket, partition_object_key(prefix, UNSEEN_SCORES_TABLE, scoring_partition)
        )
        if table is None:
            skipped.update({head.name: f"no unseen scores for dt={scoring_partition}" for head in heads})
            continue
        scores = with_model_names(table.to_pandas())
        pool = scored_pool(scores)
        graded_by_head: dict[str, pd.DataFrame] = {}
        for head in heads:
            missing = missing_label_columns(labels, head)
            if missing:
                skipped[head.name] = f"dt={partition_key} labels lack {', '.join(missing)}"
                continue
            head_scores = scores[scores["head"] == head.name]
            if head_scores.empty:
                skipped[head.name] = f"dt={scoring_partition} scored no {head.name} row"
                continue
            graded = graded_rows(head_scores, labels, head)
            graded_by_head[head.name] = graded
            grades.extend(head_grades(graded, head, pool=pool, scoring_partition=scoring_partition))
        report_rows.extend(
            report_grade_rows(graded_by_head, pool=pool, horizon_days=horizon_days, scoring_partition=scoring_partition)
        )

    for grade in grades:
        context.log.info(f"unseen grade: {grade.as_dict()}")
    for head_name, reason in skipped.items():
        context.log.info(f"{head_name}: not graded, {reason}")

    context.add_output_metadata({**grade_metadata(grades), "skipped_heads": dagster.MetadataValue.json(skipped)})
    capture_training_events(
        context,
        partition_key,
        [
            *unseen_head_graded_events(run_id=context.run.run_id, grades=grades),
            *unseen_report_graded_events(run_id=context.run.run_id, rows=report_rows),
        ],
    )


inbox_ranking_training_job = dagster.define_asset_job(
    name="inbox_ranking_training_job",
    selection=[
        EXAMPLES_TABLE,
        "inbox_ranking_model_candidate",
        "inbox_ranking_model_champion",
        UNSEEN_SCORES_TABLE,
        "inbox_ranking_unseen_graded",
    ],
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
