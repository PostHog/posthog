"""Daily serving publish and online grading for the Self-driving Inbox report-ranking models.

The models are trained by the `signals_ml` location (`nn/dag.py`). This dag fits nothing. Its
assets run on the same daily partition as the dataset dag and write under the dataset prefix:

    inbox_ranking_models/v1/served.json               pointer to the model key the scoring sweep serves
    inbox_ranking_served_scores/v1/dt=D/              the scoring sweep's scores of the reports born that day

`inbox_ranking_serving_manifest` publishes what the scoring sweep serves. The dataset bucket holds
the training history and the Temporal workers cannot reach it, so the asset copies the models the
sweep needs into the deployment's own object store and writes a manifest naming them
(`serving/manifest.json`, `serving/models/<key>/`). The manifest is the dag's serving decision:
which models a pass scores, and which of them the inbox would order on. Only
`inbox_ranking_promote_job` (`training/promote.py`) writes `served.json`, and a person runs it.
The `<name>/champion.json` objects that the retired automatic promotion wrote stay in place, and
the manifest still reads them for the cross-family role.

This module also holds the plumbing the `nn` trainer shares: snapshot loading, the recipe check
and `decide_family_champion`, which records each family's promotion decision against the served
model of its own name, graded on the candidate's holdout through the incumbent's train-only fit.

Two further assets grade the served models on data no example covers. `inbox_ranking_served_scores`
(`training/served.py`) reads the scoring sweep's live scores of every report born on D, one row set
per model key the manifest named (`unseen_pool` explains why no example can cover one);
`inbox_ranking_unseen_graded` evaluates saved scores daily against the dt=D labels until each
head's horizon, keeping provisional evaluations separate from mature grades. The holdout AUC
grades the recipe, because the shipped model is refit on train plus holdout; the baked online
AUC grades each model on reports it never saw. The two are comparable because both apply the
same `Head` cohort, label and horizon.
"""

import json
import datetime
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

import pandas as pd
import dagster
from botocore.exceptions import ClientError

from posthog import settings
from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.signals.backend.ranking.features import FEATURE_SETS
from products.signals.backend.ranking.model_contract import model_mismatch, trained_head_files
from products.signals.backend.ranking.overrides import read_ranking_overrides
from products.signals.backend.ranking.serving_manifest import (
    PROJECT_VECTORS_ENGAGEMENT_DATE_METADATA_KEY,
    PROJECT_VECTORS_SCHEMA_VERSION_METADATA_KEY,
    USER_VECTORS_SCHEMA_VERSION_METADATA_KEY,
    ServingManifest,
    model_key,
    serving_manifest_key,
    serving_project_vectors_key,
    serving_user_vectors_key,
)
from products.signals.dags.inbox_ranking.common import (
    DATASET_VERSION,
    S3_BUCKET_ENV,
    RunContext,
    dataset_bucket,
    dataset_unconfigured,
    owner_tags,
    partition_def,
    partition_object_key,
    read_parquet_if_exists,
    s3_client,
    serving_mirror_storage,
    skip_unconfigured,
)
from products.signals.dags.inbox_ranking.dataset.dag import (
    LABELS_TABLE,
    PROJECT_VECTORS_TABLE,
    STATE_TABLE,
    USER_VECTORS_TABLE,
)
from products.signals.dags.inbox_ranking.dataset.project_vectors import (
    PROJECT_VECTORS_SCHEMA_VERSION,
    USER_VECTORS_SCHEMA_VERSION,
)
from products.signals.dags.inbox_ranking.training.examples import (
    BASE_STATE_COLUMNS,
    PROVENANCE_LABEL_COLUMNS,
    PROVENANCE_STATE_COLUMNS,
    Snapshot,
    assemble_snapshot,
)
from products.signals.dags.inbox_ranking.training.families import (
    MODEL_FAMILIES,
    ModelFamily,
    experiment_names,
    serving_families,
)
from products.signals.dags.inbox_ranking.training.heads import (
    ACTION_LABEL_COLUMNS,
    HEADS,
    HEADS_BY_HORIZON,
    HEADS_BY_NAME,
)
from products.signals.dags.inbox_ranking.training.promotion import decide_promotion
from products.signals.dags.inbox_ranking.training.recipe import RECIPE_HASH_KEY, recipe_mismatch
from products.signals.dags.inbox_ranking.training.serving import FamilyModels, ManifestDecision, compose_manifest
from products.signals.dags.inbox_ranking.training.telemetry import (
    MirrorPublication,
    capture_training_events,
    promotion_event,
    serving_manifest_event,
    unseen_calibration_events,
    unseen_head_evaluated_events,
    unseen_head_graded_events,
    unseen_report_graded_events,
)
from products.signals.dags.inbox_ranking.training.train import HoldoutGrade
from products.signals.dags.inbox_ranking.training.unseen import (
    SERVED_SCORES_TABLE,
    HeadGrade,
    calibration_rows,
    graded_rows,
    head_grades,
    missing_label_columns,
    report_grade_rows,
    scored_pool,
    with_model_names,
)

if TYPE_CHECKING:
    from posthog.storage.object_storage import ObjectStorageClient

MODELS_TABLE = "inbox_ranking_models"
CHAMPION_FILE = "champion.json"
SERVED_FILE = "served.json"
METADATA_FILE = "metadata.json"

# Label columns the heads read (plus the provenance inputs); everything else stays on disk.
_LABEL_COLUMNS = (
    "impression_unit_count",
    "open_count",
    "dismissal_reason",
    "wrong_dismissal_count",
    "fixed_count",
    "lowvalue_dismissal_count",
    "pr_created_count",
    "pr_merged_count",
    "refund_count",
    *ACTION_LABEL_COLUMNS,
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


def model_object_key(prefix: str, model_name: str, partition_key: str, filename: str) -> str:
    return f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/{model_name}/dt={partition_key}/{filename}"


def champion_object_key(prefix: str, model_name: str) -> str:
    return f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/{model_name}/{CHAMPION_FILE}"


def served_object_key(prefix: str) -> str:
    """The one served pointer. It sits above the family folders because it can name any family."""
    return f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/{SERVED_FILE}"


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


def read_served_pointer(client, bucket: str, prefix: str) -> dict[str, Any] | None:
    """The `served.json` record, or None before the first promotion."""
    return _read_json_if_exists(client, bucket, served_object_key(prefix))


def previous_recipe_metadata(
    client, bucket: str, prefix: str, model_name: str, partition_key: str
) -> dict[str, Any] | None:
    """The `metadata.json` of the newest version of `model_name` at or before `partition_key` that
    carries a recipe hash, or None. A re-run of a partition compares with that partition's own saved
    recipe, so a re-run cannot replace a version with another recipe. A version written before the
    hash existed is passed over.

    Every dataset version is searched, because a `DATASET_VERSION` bump moves the models to a new
    folder and would otherwise hide the recipe the name was trained with."""
    paginator = client.get_paginator("list_objects_v2")

    def folders(parent: str) -> list[str]:
        return [
            common["Prefix"]
            for page in paginator.paginate(Bucket=bucket, Prefix=parent, Delimiter="/")
            for common in page.get("CommonPrefixes", [])
        ]

    candidates: list[tuple[str, bool, str]] = []
    for dataset_folder in folders(f"{prefix}/{MODELS_TABLE}/"):
        version_folder = f"{dataset_folder}{model_name}/dt="
        is_current = dataset_folder == f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/"
        for folder in folders(version_folder):
            version = folder[len(version_folder) :].rstrip("/")
            if version <= partition_key:
                candidates.append((version, is_current, f"{folder}{METADATA_FILE}"))
    for _, _, key in sorted(candidates, reverse=True):
        metadata = _read_json_if_exists(client, bucket, key)
        if metadata is not None and metadata.get(RECIPE_HASH_KEY):
            return metadata
    return None


def check_recipe(
    client, bucket: str, prefix: str, model_name: str, partition_key: str, recipe: Mapping[str, Any]
) -> None:
    """Fail the run, without a retry, when `recipe` is not the recipe `model_name` was trained with."""
    mismatch = recipe_mismatch(
        model_name, recipe, previous_recipe_metadata(client, bucket, prefix, model_name, partition_key)
    )
    if mismatch is not None:
        raise dagster.Failure(description=mismatch, allow_retries=False)


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


# The `nn` examples for dt=D read every snapshot back to D-lookback. The default same-partition mapping
# would let an asset backfill run examples(D) as soon as state(D) and labels(D) exist, while the
# older days it needs are still pending. Partitions before the label epoch have no upstream to map to.
_LOOKBACK_MAPPING = dagster.TimeWindowPartitionMapping(
    start_offset=-settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS,
    end_offset=0,
    allow_nonexistent_upstream_partitions=True,
)


def served_incumbent(client, bucket: str, prefix: str, model_name: str) -> dict[str, Any] | None:
    """The metadata of the served model when it has `model_name`, else None. A candidate is graded
    only against a model of its own name: two names read different features, so a paired grade
    across them means nothing."""
    pointer = read_served_pointer(client, bucket, prefix)
    if pointer is None or pointer.get("model_name") != model_name:
        return None
    return _read_json_if_exists(
        client, bucket, model_object_key(prefix, model_name, pointer["model_version"], METADATA_FILE)
    )


def decide_family_champion(
    context: dagster.AssetExecutionContext,
    client,
    bucket: str,
    prefix: str,
    partition_key: str,
    family: ModelFamily,
    *,
    grade_champion: Callable[[Mapping[str, Any]], dict[str, HoldoutGrade]],
) -> dict[str, dagster.MetadataValue] | None:
    """One family's promotion decision against the served model of its name, or None when the
    family has no candidate for the partition. The decision is recorded and never written to a
    pointer.

    `grade_champion` grades the incumbent's train-only fit on the candidate's holdout, in the
    family's own learner. Every family shares the rest, so one rule decides every family.
    """
    candidate = _read_json_if_exists(
        client, bucket, model_object_key(prefix, family.name, partition_key, METADATA_FILE)
    )
    if candidate is None:
        context.log.warning(f"no {family.name} candidate metadata for dt={partition_key}; nothing to decide")
        return None
    champion = served_incumbent(client, bucket, prefix, family.name)
    champion_grades: dict[str, HoldoutGrade] = {}
    champion_aucs: dict[str, float] = {}
    champion_eces: dict[str, float] = {}
    if champion is not None:
        champion_grades = grade_champion(champion)
        champion_aucs = {head: grade.auc for head, grade in champion_grades.items() if grade.auc is not None}
        champion_eces = {
            head: grade.expected_calibration_error
            for head, grade in champion_grades.items()
            if grade.expected_calibration_error is not None
        }
        if champion_grades:
            context.log.info(
                f"{family.name} served model {champion['model_version']} on this holdout: "
                f"AUC {champion_aucs}, ECE {champion_eces}"
            )
    decision = decide_promotion(
        candidate,
        champion,
        champion_grades=champion_grades,
        min_holdout_positives={name: head.min_holdout_positives for name, head in HEADS_BY_NAME.items()},
    )
    context.log.info(
        f"{family.name} promotion decision for dt={partition_key}: would promote={decision.promote} "
        f"({decision.reason}); run inbox_ranking_promote_job to serve it"
    )

    incumbent_champion_version = (champion or {}).get("model_version", "none")
    capture_training_events(
        context,
        partition_key,
        [
            promotion_event(
                partition_key=partition_key,
                run_id=context.run_id,
                model_name=family.name,
                decision=decision,
                incumbent_champion_version=incumbent_champion_version,
                champion_aucs=champion_aucs,
                champion_eces=champion_eces,
                recipe_hash=candidate.get(RECIPE_HASH_KEY),
                incumbent_recipe_hash=(champion or {}).get(RECIPE_HASH_KEY),
            )
        ],
    )
    return {
        f"{family.name}_would_promote": dagster.MetadataValue.bool(decision.promote),
        f"{family.name}_gates_passed": dagster.MetadataValue.bool(decision.gates_passed),
        f"{family.name}_reason": dagster.MetadataValue.text(decision.reason),
        f"{family.name}_skipped_heads": dagster.MetadataValue.json(list(decision.skipped_heads)),
        **{
            f"{family.name}_champion_{head}_auc_on_this_holdout": dagster.MetadataValue.float(auc)
            for head, auc in champion_aucs.items()
        },
        **{
            f"{family.name}_champion_{head}_ece_on_this_holdout": dagster.MetadataValue.float(ece)
            for head, ece in champion_eces.items()
        },
        f"{family.name}_incumbent_champion_version": dagster.MetadataValue.text(incumbent_champion_version),
    }


SERVING_MANIFEST_ASSET = "inbox_ranking_serving_manifest"


@frozen
class _ServingStore:
    storage: "ObjectStorageClient"
    bucket: str
    # A cross-account bucket refuses a write that does not hand ownership to the bucket owner.
    acl: str | None = None

    def write(
        self,
        key: str,
        content: str | bytes,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        extras: dict[str, Any] = {}
        if content_type is not None:
            extras["ContentType"] = content_type
        if metadata is not None:
            extras["Metadata"] = metadata
        if self.acl is not None:
            extras["ACL"] = self.acl
        self.storage.write(bucket=self.bucket, key=key, content=content, extras=extras or None)


@dagster.asset(name=SERVING_MANIFEST_ASSET, deps=[PROJECT_VECTORS_TABLE, USER_VECTORS_TABLE], **COMMON_ASSET_KWARGS)
def inbox_ranking_serving_manifest(context: dagster.AssetExecutionContext) -> None:
    """Publish the models the scoring sweep serves, and the manifest naming them.

    The training history stays in the dataset bucket, which the Temporal workers cannot reach. What
    the sweep needs is copied into the deployment's own object store instead, so the serving path
    needs no credential for the dataset bucket. A model version is immutable, so a version already
    at the target is left alone, and the manifest is written last: a failed copy leaves the previous
    manifest, and the models it names, serving.

    When an entry reads project vectors, the dt=D `inbox_project_vectors` day is copied the same
    way, and the manifest names it. Its `as_of` is the end of dt=D, so it is never newer than a
    report the sweep scores after this publish.

    The dt=D `inbox_user_vectors` day is copied too, and the manifest names it in `user_vectors`. No
    model reads it yet, so a missing day leaves the key out and never blocks the publish.
    """
    if skip_unconfigured(context):
        return
    context.add_output_metadata(_publish_manifest(context, context.partition_key, context.run.run_id))


def _publish_manifest(context: RunContext, partition_key: str, run_id: str) -> dict[str, dagster.MetadataValue]:
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()
    served, served_reason = _served_model(client, bucket, prefix)
    served_family = served["model_name"] if served is not None else "none"
    overrides = read_ranking_overrides(datetime.datetime.now(datetime.UTC))
    pinned, dropped_pins = _pinned_models(client, bucket, prefix, overrides.pin)
    for key, reason in dropped_pins.items():
        context.log.warning(f"pinned model {key} dropped: {reason}")

    families = [
        FamilyModels(
            name=family.name,
            champion=_read_json_if_exists(client, bucket, champion_object_key(prefix, family.name)),
        )
        for family in serving_families(MODEL_FAMILIES)
    ]
    recent_versions = settings.INBOX_RANKING_SERVING_RECENT_VERSIONS
    recent = (
        _recent_models(context, client, bucket, prefix, served["model_name"], partition_key, recent_versions)
        if served is not None
        else []
    )
    # One version per other family, read from the last 2 days, because a `signals_ml` candidate can
    # land after this asset runs.
    challengers = (
        [
            metadata
            for family in serving_families(MODEL_FAMILIES)
            if family.name != served["model_name"]
            for metadata in _recent_models(context, client, bucket, prefix, family.name, partition_key, 1)
        ]
        if served is not None
        else []
    )
    decision = (
        compose_manifest(
            families,
            served=served,
            prefix=prefix,
            now=datetime.datetime.now(datetime.UTC),
            recent=recent,
            recent_versions=recent_versions,
            challengers=challengers,
            pinned=pinned,
        )
        if served_reason is None
        else ManifestDecision(manifest=None, reason=served_reason)
    )
    manifest_keys = {entry.key for entry in decision.manifest.models} if decision.manifest else set()
    if decision.manifest is not None:
        for key in overrides.pin:
            if key not in dropped_pins and key not in manifest_keys:
                dropped_pins[key] = "over the manifest entry cap"
    pin_metadata = {
        "pinned_keys": dagster.MetadataValue.json(sorted(set(overrides.pin) & manifest_keys)),
        "dropped_pins": dagster.MetadataValue.json(dropped_pins),
    }
    if decision.manifest is None:
        context.log.warning(f"no serving manifest for dt={partition_key}: {decision.reason}")
        capture_training_events(
            context,
            partition_key,
            [
                serving_manifest_event(
                    partition_key=partition_key,
                    run_id=run_id,
                    served_family=served_family,
                    manifest=None,
                    reason=decision.reason,
                )
            ],
        )
        return {"published": dagster.MetadataValue.bool(False), **pin_metadata}

    manifest = decision.manifest
    project_vectors_source = None
    if any(entry.reads_project_vectors for entry in manifest.models):
        project_vectors_source = partition_object_key(prefix, PROJECT_VECTORS_TABLE, partition_key)
        manifest = manifest.model_copy(update={"project_vectors": serving_project_vectors_key(prefix, partition_key)})
    manifest_key = serving_manifest_key(prefix)
    primary = _ServingStore(storage=object_storage.object_storage_client(), bucket=settings.OBJECT_STORAGE_BUCKET)
    user_vectors_key = serving_user_vectors_key(prefix, partition_key)
    user_vectors_bytes = _publish_user_vectors(
        context,
        client,
        bucket,
        partition_object_key(prefix, USER_VECTORS_TABLE, partition_key),
        user_vectors_key,
        primary,
    )
    if user_vectors_bytes is not None:
        manifest = manifest.model_copy(update={"user_vectors": user_vectors_key})
    publication = publish_serving_models(
        context, client, bucket, prefix, manifest, primary, project_vectors_source=project_vectors_source
    )
    context.log.info(f"published serving manifest {manifest.manifest_version} serving {manifest.served.key}")
    mirror = _publish_mirror(context, client, bucket, prefix, partition_key, manifest)
    capture_training_events(
        context,
        partition_key,
        [
            serving_manifest_event(
                partition_key=partition_key,
                run_id=run_id,
                served_family=served_family,
                manifest=manifest,
                reason=decision.reason,
                copied_keys=publication.copied,
                present_keys=publication.present,
                bytes_copied=publication.bytes_copied + (user_vectors_bytes or 0),
                mirror=mirror,
                recipe_hashes={
                    model_key(metadata["model_name"], metadata["model_version"]): metadata.get(RECIPE_HASH_KEY)
                    for metadata in (
                        *([served] if served is not None else []),
                        *recent,
                        *challengers,
                        *pinned,
                        *(family.champion for family in families if family.champion),
                    )
                },
            )
        ],
    )
    mirror_metadata = (
        {}
        if mirror is None
        else {
            "mirror_published": dagster.MetadataValue.bool(mirror.published),
            "mirror_project_vectors_key": dagster.MetadataValue.text(mirror.project_vectors_key or ""),
            "mirror_skip_reason": dagster.MetadataValue.text(mirror.skip_reason or ""),
        }
    )
    return {
        "published": dagster.MetadataValue.bool(True),
        "manifest_key": dagster.MetadataValue.text(manifest_key),
        "manifest_version": dagster.MetadataValue.text(manifest.manifest_version),
        "served_key": dagster.MetadataValue.text(manifest.served.key),
        "models": dagster.MetadataValue.json(
            [{"key": entry.key, "roles": entry.roles, "heads": entry.heads} for entry in manifest.models]
        ),
        "entries_copied": dagster.MetadataValue.int(len(publication.copied)),
        "entries_already_present": dagster.MetadataValue.int(len(publication.present)),
        "bytes_copied": dagster.MetadataValue.int(publication.bytes_copied + (user_vectors_bytes or 0)),
        "project_vectors_key": dagster.MetadataValue.text(manifest.project_vectors or ""),
        "user_vectors_key": dagster.MetadataValue.text(manifest.user_vectors or ""),
        **pin_metadata,
        **mirror_metadata,
    }


_ACCESS_DENIED_CODES = ("403", "AccessDenied")


def _object_exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    return True


def _served_model(client, bucket: str, prefix: str) -> tuple[dict[str, Any] | None, str | None]:
    """The metadata of the model `served.json` names, or None and the reason nothing is published.

    The served model passes the same check as a pin. A pointer to a model that cannot be served
    publishes nothing, so the previous manifest keeps serving.
    """
    pointer = read_served_pointer(client, bucket, prefix)
    if pointer is None:
        return None, f"no {SERVED_FILE}; run inbox_ranking_promote_job to choose the served model"
    key = str(pointer.get("model_key"))
    try:
        metadata, reason = _pin_metadata(client, bucket, prefix, key)
    except (ClientError, ValueError) as error:
        metadata, reason = None, f"could not read the model: {error!r}"
    if metadata is None:
        return None, f"served model {key} cannot be served: {reason}"
    return metadata, None


def _pinned_models(
    client, bucket: str, prefix: str, keys: Sequence[str]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The metadata of each pinned model this build can serve, and the reason each other pin is dropped.

    `publish_serving_models` fails the whole manifest when a file it copies is missing, so a pin
    is checked here, before composition. A bad pin then costs only itself.
    """
    pinned: list[dict[str, Any]] = []
    dropped: dict[str, str] = {}
    for key in keys:
        try:
            metadata, reason = _pin_metadata(client, bucket, prefix, key)
        # S3 answers 403, not 404, for a missing key when the role cannot list the prefix, and a
        # pin must cost only itself, so every read error drops the pin.
        except (ClientError, ValueError) as error:
            metadata, reason = None, f"could not read the model: {error!r}"
        if metadata is None:
            dropped[key] = reason or "unknown"
            continue
        pinned.append(metadata)
    return pinned, dropped


def _recent_models(
    context: RunContext, client, bucket: str, prefix: str, model_name: str, partition_key: str, versions: int
) -> list[dict[str, Any]]:
    """The metadata of each `model_name` version fit in the 2 * `versions` days up to the partition,
    newest first, that this build can serve.

    A family does not fit a model every day, so the window is wider than `versions`. A version
    passes the same check as a pin, because one missing file fails the whole publish.
    """
    end = datetime.date.fromisoformat(partition_key)
    recent: list[dict[str, Any]] = []
    for offset in range(2 * versions):
        key = model_key(model_name, (end - datetime.timedelta(days=offset)).isoformat())
        try:
            metadata, reason = _pin_metadata(client, bucket, prefix, key)
        except ValueError as error:
            metadata, reason = None, f"could not read the model: {error!r}"
        except ClientError as error:
            # S3 answers 403 for a missing key when the role cannot list the prefix. Any other error,
            # such as throttling, fails the publish so the retry policy runs instead of a smaller manifest.
            if error.response.get("Error", {}).get("Code") not in _ACCESS_DENIED_CODES:
                raise
            metadata, reason = None, f"could not read the model: {error!r}"
        if metadata is None:
            context.log.info(f"recent model {key} skipped: {reason}")
            continue
        recent.append(metadata)
    return recent


def _pin_metadata(client, bucket: str, prefix: str, key: str) -> tuple[dict[str, Any] | None, str | None]:
    """The metadata of one pinned model, or None and the reason it cannot be served.

    The promote job, the served pointer, the pins and the recent and challenger reads all pass this
    check, so an experiment family is refused here once for every path."""
    model_name, model_version = key.split("@", 1)
    if model_name in experiment_names(MODEL_FAMILIES):
        return None, (
            f"{model_name} is an experiment family, and an experiment never serves. To serve this "
            "recipe, register it as a serving family under a new model_name"
        )
    metadata = _read_json_if_exists(client, bucket, model_object_key(prefix, model_name, model_version, METADATA_FILE))
    if metadata is None:
        return None, f"no {METADATA_FILE} in the dataset bucket"
    if (metadata.get("model_name"), metadata.get("model_version")) != (model_name, model_version):
        return None, f"{METADATA_FILE} describes another model"
    mismatch = model_mismatch(metadata)
    if mismatch is not None:
        return None, mismatch
    files = sorted(set(trained_head_files(metadata, HEADS_BY_NAME).values()))
    missing = [
        name
        for name in files
        if not _object_exists(client, bucket, model_object_key(prefix, model_name, model_version, name))
    ]
    if not files or missing:
        return None, f"missing model files {missing}" if missing else "no trained head"
    return metadata, None


# How many days before the publish partition the mirror region's project vectors day, and the
# engagement export it was built from, may be. The mirror region builds day D after this region's
# 05:00 UTC publish, so a mirror that keeps up names D-1.
MIRROR_PROJECT_VECTORS_MAX_LAG_DAYS = 3

NO_FRESH_PROJECT_VECTORS = "no_fresh_project_vectors"
UNKNOWN_SCHEMA_VERSION = "unknown_schema_version"
STALE_ENGAGEMENT_EXPORT = "stale_engagement_export"
MIRROR_PUBLISH_FAILED = "publish_failed"


@frozen
class _MirrorProjectVectors:
    """The mirror region's project vectors day the mirror manifest names, or the newest day refused."""

    key: str | None
    date: str | None
    engagement_export_date: str | None
    # Why no day passes, or None when `key` names one.
    refusal: str | None


# The mirror region deploys apart from this one, so its day can carry the version before the
# current one. The scorer skips a model that reads a kind the day has no rows for.
_NAMEABLE_PROJECT_VECTORS_SCHEMA_VERSIONS = frozenset({"1", str(PROJECT_VECTORS_SCHEMA_VERSION)})


def _project_vectors_refusal(metadata: Mapping[str, str], oldest: datetime.date) -> str | None:
    if metadata.get(PROJECT_VECTORS_SCHEMA_VERSION_METADATA_KEY) not in _NAMEABLE_PROJECT_VECTORS_SCHEMA_VERSIONS:
        return UNKNOWN_SCHEMA_VERSION
    try:
        engagement_date = datetime.date.fromisoformat(metadata.get(PROJECT_VECTORS_ENGAGEMENT_DATE_METADATA_KEY, ""))
    except ValueError:
        return STALE_ENGAGEMENT_EXPORT
    return STALE_ENGAGEMENT_EXPORT if engagement_date < oldest else None


def _mirror_project_vectors(mirror: _ServingStore, prefix: str, partition_key: str) -> _MirrorProjectVectors:
    """The newest day within `MIRROR_PROJECT_VECTORS_MAX_LAG_DAYS` of the partition that the mirror
    region wrote its own project vectors for, and that this build can name.

    Only object metadata is read, never the body: this region must not hold the mirror region's
    per-team vectors. The mirror grant has no list permission, so a missing key answers 403, and
    `head_object` reads both as absent.
    """
    end = datetime.date.fromisoformat(partition_key)
    oldest = end - datetime.timedelta(days=MIRROR_PROJECT_VECTORS_MAX_LAG_DAYS)
    newest_refused: _MirrorProjectVectors | None = None
    for offset in range(MIRROR_PROJECT_VECTORS_MAX_LAG_DAYS + 1):
        day = (end - datetime.timedelta(days=offset)).isoformat()
        key = serving_project_vectors_key(prefix, day)
        head = mirror.storage.head_object(bucket=mirror.bucket, file_key=key)
        if head is None:
            continue
        metadata = head.get("Metadata") or {}
        refusal = _project_vectors_refusal(metadata, oldest)
        found = _MirrorProjectVectors(
            key=None if refusal else key,
            date=day,
            engagement_export_date=metadata.get(PROJECT_VECTORS_ENGAGEMENT_DATE_METADATA_KEY),
            refusal=refusal,
        )
        if refusal is None:
            return found
        newest_refused = newest_refused or found
    return newest_refused or _MirrorProjectVectors(
        key=None, date=None, engagement_export_date=None, refusal=NO_FRESH_PROJECT_VECTORS
    )


def _publish_mirror(
    context: RunContext, client, bucket: str, prefix: str, partition_key: str, manifest: ServingManifest
) -> MirrorPublication | None:
    """Copy the same publish into the mirror store, if one is set. Returns None when no mirror is
    set, otherwise what the mirror now serves.

    The primary publish has already succeeded, so a mirror failure only logs: the region that
    trains keeps serving, and the mirror keeps its previous manifest and models.

    Project vectors are per-team data of this deployment's teams, so they never go to another
    deployment's store. When an entry reads them, the mirror's manifest names the mirror region's
    own day instead (`_mirror_project_vectors`). That day is already in the mirror store, so
    `publish_serving_models` gets no source and copies none. Without such a day the mirror's
    manifest names none, and its sweep skips the models that read them. A served model that reads
    them could not score there, so then the mirror keeps its previous manifest.

    User vectors are per-user data of this deployment, so they never go to the mirror either, and
    the mirror's manifest names none.
    """
    if not settings.INBOX_RANKING_SERVING_MIRROR_BUCKET:
        return None
    vectors: _MirrorProjectVectors | None = None
    try:
        mirror = _ServingStore(
            storage=serving_mirror_storage(),
            bucket=settings.INBOX_RANKING_SERVING_MIRROR_BUCKET,
            acl="bucket-owner-full-control",
        )
        if manifest.project_vectors is not None:
            vectors = _mirror_project_vectors(mirror, prefix, partition_key)
        project_vectors_key = vectors.key if vectors else None
        if manifest.served.reads_project_vectors and vectors is not None and project_vectors_key is None:
            context.log.warning(
                f"serving manifest {manifest.manifest_version} not mirrored: its served model reads project "
                f"vectors and the mirror has no usable day ({vectors.refusal}, newest day {vectors.date})"
            )
            return _mirror_publication(vectors, skip_reason=vectors.refusal)
        publish_serving_models(
            context,
            client,
            bucket,
            prefix,
            manifest.model_copy(update={"project_vectors": project_vectors_key, "user_vectors": None}),
            mirror,
        )
    except Exception as error:
        context.log.exception(f"serving manifest {manifest.manifest_version} not mirrored: {error!r}")
        return _mirror_publication(vectors, skip_reason=MIRROR_PUBLISH_FAILED)
    context.log.info(
        f"mirrored serving manifest {manifest.manifest_version} to {mirror.bucket}"
        f" with project vectors {project_vectors_key}"
    )
    return _mirror_publication(vectors, skip_reason=None)


def _mirror_publication(vectors: _MirrorProjectVectors | None, skip_reason: str | None) -> MirrorPublication:
    return MirrorPublication(
        published=skip_reason is None,
        project_vectors_key=vectors.key if vectors and skip_reason is None else None,
        project_vectors_date=vectors.date if vectors else None,
        engagement_export_date=vectors.engagement_export_date if vectors else None,
        skip_reason=skip_reason,
    )


@frozen
class _ModelPublication:
    copied: list[str]
    present: list[str]
    bytes_copied: int


def publish_serving_models(
    context: RunContext,
    client,
    bucket: str,
    prefix: str,
    manifest: ServingManifest,
    target: _ServingStore,
    *,
    project_vectors_source: str | None = None,
) -> _ModelPublication:
    """Copy every model the manifest names from the dataset bucket into `target`, then the project
    vectors the manifest names from `project_vectors_source`, then write the manifest there.

    Returns the keys copied, the keys already there, and the bytes moved. A missing source object
    fails before the manifest is written, so the manifest can never name a model or a project
    vectors day the sweep cannot load.
    """
    copied: list[str] = []
    present: list[str] = []
    bytes_copied = 0
    for entry in manifest.models:
        target_metadata = f"{entry.prefix}/{METADATA_FILE}"
        # A version is immutable, so its metadata record standing in for the whole prefix is safe
        # and saves re-reading a 1536-column booster every day.
        if target.storage.head_object(bucket=target.bucket, file_key=target_metadata) is not None:
            present.append(entry.key)
            continue
        # Metadata marks a complete copy, so write it after every model file to make retries safe.
        for name in (*entry.files, METADATA_FILE):
            body = _read_bytes_if_exists(
                client, bucket, model_object_key(prefix, entry.model_name, entry.model_version, name)
            )
            if body is None:
                raise dagster.Failure(f"{entry.key} is missing {name} in the dataset bucket; manifest not written")
            target.write(f"{entry.prefix}/{name}", body)
            bytes_copied += len(body)
        copied.append(entry.key)
        context.log.info(f"copied {entry.key} to {target.bucket}/{entry.prefix}")
    if manifest.project_vectors is not None:
        bytes_copied += _publish_project_vectors(
            context, client, bucket, project_vectors_source, manifest.project_vectors, target
        )
    target.write(serving_manifest_key(prefix), manifest.model_dump_json(indent=2), content_type="application/json")
    return _ModelPublication(copied=copied, present=present, bytes_copied=bytes_copied)


def _publish_project_vectors(
    context: RunContext,
    client,
    bucket: str,
    source: str | None,
    target_key: str,
    target: _ServingStore,
) -> int:
    """Copy one day of project vectors to `target_key`, and return the bytes moved.

    A day is immutable once the manifest names it, so a copy already at the target is left alone.
    """
    if target.storage.head_object(bucket=target.bucket, file_key=target_key) is not None:
        return 0
    body = None if source is None else _read_bytes_if_exists(client, bucket, source)
    if body is None:
        raise dagster.Failure(f"project vectors {source} are missing in the dataset bucket; manifest not written")
    target.write(target_key, body)
    context.log.info(f"copied project vectors to {target.bucket}/{target_key}")
    return len(body)


def _publish_user_vectors(
    context: RunContext,
    client,
    bucket: str,
    source: str,
    target_key: str,
    target: _ServingStore,
) -> int | None:
    """Copy one day of user vectors to `target_key`, stamped with its schema version. Returns the
    bytes moved, or None when the day is not in `target` after the call.

    No model reads user vectors yet, so a missing day or a failed copy only logs, and the publish
    goes on without them. A day already at the target is left alone, like a project vectors day.
    """
    try:
        if target.storage.head_object(bucket=target.bucket, file_key=target_key) is not None:
            return 0
        body = _read_bytes_if_exists(client, bucket, source)
        if body is None:
            context.log.warning(f"user vectors {source} are missing in the dataset bucket; manifest names none")
            return None
        target.write(
            target_key,
            body,
            metadata={USER_VECTORS_SCHEMA_VERSION_METADATA_KEY: str(USER_VECTORS_SCHEMA_VERSION)},
        )
    except Exception as error:
        context.log.exception(f"user vectors {source} not copied: {error!r}")
        return None
    context.log.info(f"copied user vectors to {target.bucket}/{target_key}")
    return len(body)


# dt=D evaluates scores from birth through maturity, so the mapping reaches back as far as the
# longest head horizon. Partitions before the scores asset existed have no upstream to map to.
_HORIZON_MAPPING = dagster.TimeWindowPartitionMapping(
    start_offset=-max(HEADS_BY_HORIZON),
    end_offset=0,
    allow_nonexistent_upstream_partitions=True,
)


def grade_metadata(grades: Sequence[HeadGrade]) -> dict[str, dagster.MetadataValue]:
    """One metadata entry per (head, model version, role, metric). The family and the version are in
    the key, so two families graded on the same rows do not overwrite each other, and neither do two
    versions that a manifest change put in one scoring day. Counts stay ints: `MetadataValue.float`
    rejects them."""
    metadata: dict[str, dagster.MetadataValue] = {}
    for grade in grades:
        for name, value in grade.metrics().items():
            if value is None:
                continue
            key = f"{grade.head}_{grade.model_name}_{grade.model_version}_{grade.model_role}_{name}"
            metadata[key] = (
                dagster.MetadataValue.int(value) if isinstance(value, int) else dagster.MetadataValue.float(value)
            )
    return metadata


@dagster.asset(
    name="inbox_ranking_unseen_graded",
    deps=[
        dagster.AssetDep(SERVED_SCORES_TABLE, partition_mapping=_HORIZON_MAPPING),
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
    evaluations: list[HeadGrade] = []
    skipped: dict[str, str] = {}
    report_rows: list[dict[str, object]] = []
    # Read each saved scores object once, even when several heads are still maturing.
    for observed_days in range(max(HEADS_BY_HORIZON) + 1):
        heads = [head for head in HEADS if observed_days <= head.horizon_days]
        scoring_partition = (day - datetime.timedelta(days=observed_days)).isoformat()
        # Partitions before the served asset existed have no object, which is a logged skip.
        table = read_parquet_if_exists(
            client, bucket, partition_object_key(prefix, SERVED_SCORES_TABLE, scoring_partition)
        )
        if table is None:
            skipped[scoring_partition] = "no served scores"
            continue
        scores = with_model_names(table.to_pandas())
        if len(scores) < table.num_rows:
            context.log.warning(
                f"dropped {table.num_rows - len(scores)} score rows of {scoring_partition} with no model_name "
                "or a retired one"
            )
        pool = scored_pool(scores)
        graded_by_head: dict[str, pd.DataFrame] = {}
        for head in heads:
            head_key = f"{scoring_partition}/{head.name}"
            missing = missing_label_columns(labels, head)
            if missing:
                skipped[head_key] = f"dt={partition_key} labels lack {', '.join(missing)}"
                continue
            head_scores = scores[scores["head"] == head.name]
            if head_scores.empty:
                skipped[head_key] = "head was not scored"
                continue
            graded = graded_rows(head_scores, labels, head, pool=pool)
            evaluated = head_grades(graded, head, pool=pool, scoring_partition=scoring_partition, include_empty=True)
            evaluations.extend(evaluated)
            if observed_days == head.horizon_days:
                graded_by_head[head.name] = graded
                grades.extend(grade for grade in evaluated if grade.rows)
        report_rows.extend(
            report_grade_rows(
                graded_by_head, pool=pool, horizon_days=observed_days, scoring_partition=scoring_partition
            )
        )

    for grade in grades:
        context.log.info(f"unseen grade: {grade.as_dict()}")
    for head_name, reason in skipped.items():
        context.log.info(f"{head_name}: not graded, {reason}")

    context.add_output_metadata(
        {
            **grade_metadata(grades),
            "daily_evaluations": dagster.MetadataValue.int(len(evaluations)),
            "skipped_heads": dagster.MetadataValue.json(skipped),
        }
    )
    capture_training_events(
        context,
        partition_key,
        [
            *unseen_head_evaluated_events(
                run_id=context.run_id,
                grades=evaluations,
                evaluation_partition=partition_key,
                evaluated_at=datetime.datetime.now(datetime.UTC),
            ),
            *unseen_head_graded_events(run_id=context.run_id, grades=grades),
            *unseen_calibration_events(run_id=context.run_id, rows=calibration_rows(grades)),
            *unseen_report_graded_events(run_id=context.run_id, rows=report_rows),
        ],
    )


inbox_ranking_training_job = dagster.define_asset_job(
    name="inbox_ranking_training_job",
    selection=[
        SERVING_MANIFEST_ASSET,
        SERVED_SCORES_TABLE,
        "inbox_ranking_unseen_graded",
    ],
    tags={
        **owner_tags,
        # The job fits nothing: it copies models, reads one day of scoring events and grades the
        # scores objects back to the longest head horizon against one labels snapshot.
        "dagster/max_runtime": str(60 * 60),
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"memory": "2Gi"},
                    "limits": {"memory": "8Gi"},
                }
            }
        },
    },
)


# Runs after the dataset job's 2h budget (02:30 UTC start) so dt=D-1's snapshots exist.
@dagster.schedule(
    cron_schedule="0 5 * * *",
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
