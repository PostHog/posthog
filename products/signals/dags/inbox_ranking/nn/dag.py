"""Daily training for the `nn` model families: one multi-head network over the report vector and the
team's project vectors, exported to ONNX. `nn_v3` reads the vector only, and `nn_with_prio_v2` also
reads the report's priority levels.

One examples asset, and a candidate and a champion asset per family, on the dataset dag's daily
partition, registered by the `signals_ml` code location, which runs on the image that carries torch:

    inbox_ranking_nn_examples/v1/dt=D/                      rows, labels, holdout flags and priority (`nn/examples.py`)
    inbox_ranking_models/v1/<model_name>/dt=D/model.onnx    the refit that serves, + model.holdout.onnx and metadata.json
    (no object)                                             the champion asset grades the candidate and records the decision

The families' candidates run one after the other: each holds an embeddings snapshot and the project
vectors, and two at once can exceed the run's memory limit.

The main location's training job never fits these families, and this job never writes another
family's objects or any pointer. A person serves a version with `inbox_ranking_promote_job`. The
main job's serving manifest and online grader then publish and grade it as an `onnx` entry with no
change here. A candidate that lands after that day's manifest is paired by the next day's manifest.

All three assets read the dt=D dataset partitions from the dataset bucket, as the main training job
does. A partition whose snapshots are missing is logged and skipped, and the objects already under
it stay as they are.
"""

import datetime
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import dagster
import pyarrow as pa

from posthog import settings
from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import Extras
from products.signals.backend.ranking.serving_manifest import ONNX_MODEL_FILE, ONNX_MODEL_KIND
from products.signals.dags.inbox_ranking.common import (
    S3_BUCKET_ENV,
    dataset_bucket,
    dataset_unconfigured,
    owner_tags,
    partition_object_key,
    read_parquet_if_exists,
    s3_client,
    skip_unconfigured,
    write_parquet,
)
from products.signals.dags.inbox_ranking.consent import training_consent_team_ids
from products.signals.dags.inbox_ranking.dataset.dag import EMBEDDINGS_TABLE, LABELS_TABLE, STATE_TABLE
from products.signals.dags.inbox_ranking.dataset.project_vectors import EMBEDDING_COLUMNS, LABEL_COLUMNS
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkConfig
from products.signals.dags.inbox_ranking.multihead.local import report_vectors
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable
from products.signals.dags.inbox_ranking.nn.examples import (
    NN_HEADS,
    build_examples,
    examples_arrow,
    examples_from_arrow,
    network_inputs,
    subset,
)
from products.signals.dags.inbox_ranking.nn.model import (
    HOLDOUT_MODEL_FILE,
    candidate_metadata,
    champion_grades,
    network_recipe,
    network_vector_kinds,
)
from products.signals.dags.inbox_ranking.training.calibration import bucket_rows
from products.signals.dags.inbox_ranking.training.dag import (
    _LOOKBACK_MAPPING,
    COMMON_ASSET_KWARGS,
    METADATA_FILE,
    _delete_other_objects,
    _put_json,
    _read_bytes_if_exists,
    check_recipe,
    decide_family_champion,
    load_snapshots,
    model_object_key,
    snapshot_dates,
)
from products.signals.dags.inbox_ranking.training.examples import drop_without_training_consent
from products.signals.dags.inbox_ranking.training.telemetry import (
    candidate_events,
    capture_training_events,
    holdout_calibration_events,
)
from products.signals.dags.inbox_ranking.training.train import HoldoutGrade
from products.signals.dags.inbox_ranking.training.unseen import NN_FAMILY, NN_WITH_PRIO_FAMILY, ModelFamily

NN_EXAMPLES_TABLE = "inbox_ranking_nn_examples"
# The `nn_v3` assets keep the names they had as the only family, so their Dagster history continues.
NN_CANDIDATE_ASSET = "inbox_ranking_nn_model_candidate"
NN_CHAMPION_ASSET = "inbox_ranking_nn_model_champion"
NN_WITH_PRIO_CANDIDATE_ASSET = "inbox_ranking_nn_with_prio_model_candidate"
NN_WITH_PRIO_CHAMPION_ASSET = "inbox_ranking_nn_with_prio_model_champion"

# The settings the prototype compared against the champion recipe with.
NETWORK_CONFIG = NetworkConfig()

NN_ASSET_KWARGS: dict[str, Any] = {**COMMON_ASSET_KWARGS, "group_name": "inbox_ranking_nn"}


@frozen
class DayInputs:
    extras: Extras
    labels: pa.Table
    embeddings: pa.Table


def _day_inputs(
    context: dagster.AssetExecutionContext, client, bucket: str, prefix: str, partition_key: str
) -> DayInputs | None:
    """The report vectors, and the labels and embeddings snapshots the project vectors read, all from
    dt=D; None when either snapshot is missing. One embeddings snapshot serves every moment of the
    window, as in the main training job: each vector carries the moment it landed."""
    embeddings = read_parquet_if_exists(
        client, bucket, partition_object_key(prefix, EMBEDDINGS_TABLE, partition_key), columns=list(EMBEDDING_COLUMNS)
    )
    labels = read_parquet_if_exists(
        client, bucket, partition_object_key(prefix, LABELS_TABLE, partition_key), columns=list(LABEL_COLUMNS)
    )
    if embeddings is None or labels is None:
        missing = [name for name, table in ((EMBEDDINGS_TABLE, embeddings), (LABELS_TABLE, labels)) if table is None]
        context.log.warning(f"no {', '.join(missing)} snapshot for dt={partition_key}; nn skips this partition")
        return None
    return DayInputs(extras=report_vectors(embeddings), labels=labels, embeddings=embeddings)


@dagster.asset(
    name=NN_EXAMPLES_TABLE,
    deps=[
        dagster.AssetDep(STATE_TABLE, partition_mapping=_LOOKBACK_MAPPING),
        dagster.AssetDep(LABELS_TABLE, partition_mapping=_LOOKBACK_MAPPING),
        EMBEDDINGS_TABLE,
    ],
    **NN_ASSET_KWARGS,
)
def inbox_ranking_nn_examples(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()

    dates = snapshot_dates(partition_key, settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS)
    snapshots = load_snapshots(client, bucket, prefix, dates)
    if dates[-1] not in snapshots:
        context.log.warning(f"no state and labels snapshots for dt={partition_key}; nn skips this partition")
        context.add_output_metadata({"skipped": dagster.MetadataValue.bool(True)})
        return
    day = _day_inputs(context, client, bucket, prefix, partition_key)
    if day is None:
        context.add_output_metadata({"skipped": dagster.MetadataValue.bool(True)})
        return
    snapshots, excluded = drop_without_training_consent(snapshots, training_consent_team_ids())
    examples = build_examples(snapshots, day.extras, holdout_days=settings.INBOX_RANKING_TRAINING_HOLDOUT_DAYS)
    if examples.rows_without_team:
        context.log.warning(f"{examples.rows_without_team} moments have no team and no project vectors; dropped")

    key = partition_object_key(prefix, NN_EXAMPLES_TABLE, partition_key)
    write_parquet(client, bucket, key, examples_arrow(examples), snapshot_date=partition_key)
    table = examples.table
    observed = ~np.isnan(table.labels)
    context.add_output_metadata(
        {
            "snapshots": dagster.MetadataValue.int(len(snapshots)),
            "rows": dagster.MetadataValue.int(len(table.rows)),
            "network_train_rows": dagster.MetadataValue.int(len(table.network_train_rows())),
            "rows_without_team": dagster.MetadataValue.int(examples.rows_without_team),
            "excluded_no_training_consent_reports": dagster.MetadataValue.int(excluded.reports),
            **{
                f"{head.name}_rows": dagster.MetadataValue.int(int(observed[:, index].sum()))
                for index, head in enumerate(NN_HEADS)
            },
            **{
                f"{head.name}_positives": dagster.MetadataValue.int(int(np.nansum(table.labels[:, index])))
                for index, head in enumerate(NN_HEADS)
            },
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


def _missing_state_columns(family: ModelFamily, table: ExampleTable) -> list[str]:
    """The state columns `family`'s set reads that the examples rows lack. An examples object written
    before a column existed lacks it, and building the set from it would raise."""
    return [column for column in family.feature_set.state_columns if column not in table.rows]


def train_candidate(
    context: dagster.AssetExecutionContext, client, bucket: str, partition_key: str, family: ModelFamily
) -> dict[str, dagster.MetadataValue]:
    """Fit the day's network for `family`, write its graphs and `metadata.json` under
    `<model_name>/dt=D/`, and return the asset metadata. A partition without examples or snapshots
    keeps the objects it already holds, because the served pointer can name them."""
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
    arrow = read_parquet_if_exists(client, bucket, partition_object_key(prefix, NN_EXAMPLES_TABLE, partition_key))
    if arrow is None:
        context.log.warning(f"no nn examples for dt={partition_key}; {family.name} keeps this partition as it stands")
        return {"skipped": dagster.MetadataValue.bool(True)}
    examples = examples_from_arrow(arrow)
    missing = _missing_state_columns(family, examples.table)
    if missing:
        # Zeros in place of the missing column would train a model that never saw the input.
        context.log.warning(
            f"the nn examples for dt={partition_key} have no {', '.join(missing)} column; {family.name} keeps this "
            f"partition as it stands. Re-run the {NN_EXAMPLES_TABLE} asset for dt={partition_key}"
        )
        return {"skipped": dagster.MetadataValue.bool(True)}
    day = _day_inputs(context, client, bucket, prefix, partition_key)
    if day is None:
        return {"skipped": dagster.MetadataValue.bool(True)}
    inputs = network_inputs(examples.table, day.extras, day.labels, day.embeddings, family.feature_set)
    del day
    check_recipe(
        client,
        bucket,
        prefix,
        family.name,
        partition_key,
        network_recipe(family, NETWORK_CONFIG, network_vector_kinds(inputs)),
    )

    from products.signals.dags.inbox_ranking.nn.train import (  # noqa: PLC0415 — keeps torch off the location's import path
        train_network,
    )

    trained = train_network(examples.table, inputs, NN_HEADS, NETWORK_CONFIG)
    for head in trained.heads:
        context.log.info(f"{family.name} {head.metrics.head}: {head.metrics.as_dict()}")
    for name in trained.skipped:
        context.log.warning(f"{family.name} {name}: nothing to fit, skipped")

    files = {ONNX_MODEL_FILE: trained.model_onnx, HOLDOUT_MODEL_FILE: trained.holdout_model_onnx}
    written: set[str] = set()
    for filename, body in files.items():
        if body is None:
            continue
        key = model_object_key(prefix, family.name, partition_key, filename)
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/octet-stream")
        written.add(key)
    metadata = candidate_metadata(
        partition_key,
        trained,
        family=family,
        config=NETWORK_CONFIG,
        windows=examples.windows,
        trained_at=datetime.datetime.now(datetime.UTC),
        run_id=context.run_id,
    )
    metadata_key = model_object_key(prefix, family.name, partition_key, METADATA_FILE)
    _put_json(client, bucket, metadata_key, metadata)
    written.add(metadata_key)
    stale = _delete_other_objects(client, bucket, model_object_key(prefix, family.name, partition_key, ""), written)
    if stale:
        context.log.warning(
            f"removed {len(stale)} stale {family.name} objects from a previous run of dt={partition_key}"
        )
    capture_training_events(
        context,
        partition_key,
        [
            *candidate_events(metadata),
            *holdout_calibration_events(
                partition_key=partition_key,
                run_id=context.run_id,
                model_name=family.name,
                rows=[
                    row for head in trained.heads for row in bucket_rows(head.calibration, {"head": head.metrics.head})
                ],
            ),
        ],
    )
    return {
        "stale_objects_removed": dagster.MetadataValue.int(len(stale)),
        "network_train_rows": dagster.MetadataValue.int(trained.network_train_rows),
        "heads_trained": dagster.MetadataValue.int(len(trained.heads)),
        "heads_readable": dagster.MetadataValue.int(sum(1 for head in trained.heads if head.metrics.readable)),
        **{
            f"{head.metrics.head}_holdout_auc": dagster.MetadataValue.float(head.metrics.holdout_auc)
            for head in trained.heads
            if head.metrics.holdout_auc is not None
        },
        **{
            f"{head.metrics.head}_{name}": (
                dagster.MetadataValue.int(value) if isinstance(value, int) else dagster.MetadataValue.float(value)
            )
            for head in trained.heads
            for name, value in head.metrics.holdout_within_team.as_dict(prefix="holdout_").items()
            if value is not None
        },
        "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{metadata_key}"),
    }


def decide_champion(
    context: dagster.AssetExecutionContext, client, bucket: str, partition_key: str, family: ModelFamily
) -> dict[str, dagster.MetadataValue] | None:
    """The `family` promotion decision, through the rule every family shares. Nothing is written:
    the decision is recorded for the person who runs `inbox_ranking_promote_job`."""
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX

    def grade_champion(champion: Mapping[str, Any]) -> dict[str, HoldoutGrade]:
        version = champion.get("model_version")
        if champion.get("model_kind") != ONNX_MODEL_KIND:
            context.log.warning(
                f"served {family.name} model {version} is not an {ONNX_MODEL_KIND} model; compared on its stored AUC"
            )
            return {}
        holdout_model = _read_bytes_if_exists(
            client, bucket, model_object_key(prefix, family.name, str(version), HOLDOUT_MODEL_FILE)
        )
        arrow = read_parquet_if_exists(client, bucket, partition_object_key(prefix, NN_EXAMPLES_TABLE, partition_key))
        if holdout_model is None or arrow is None:
            context.log.warning(
                f"no served {family.name} {HOLDOUT_MODEL_FILE} or no examples for dt={partition_key}; "
                f"the served {family.name} model is compared on its stored AUC"
            )
            return {}
        table = examples_from_arrow(arrow).table
        missing = _missing_state_columns(family, table)
        if missing:
            context.log.warning(
                f"the nn examples for dt={partition_key} have no {', '.join(missing)} column; "
                f"the served {family.name} model is compared on its stored AUC"
            )
            return {}
        day = _day_inputs(context, client, bucket, prefix, partition_key)
        if day is None:
            return {}
        holdout = subset(table, np.flatnonzero(table.holdout.any(axis=1)))
        return champion_grades(
            champion,
            holdout_model,
            holdout,
            network_inputs(holdout, day.extras, day.labels, day.embeddings, family.feature_set),
        )

    return decide_family_champion(context, client, bucket, prefix, partition_key, family, grade_champion=grade_champion)


@frozen
class FamilyAssets:
    candidate: dagster.AssetsDefinition
    champion: dagster.AssetsDefinition


def family_assets(
    family: ModelFamily, *, candidate_name: str, champion_name: str, after: Sequence[str] = ()
) -> FamilyAssets:
    """The candidate and champion assets of one `nn` family. `after` holds the assets the candidate
    waits for, for memory and not for data."""

    @dagster.asset(name=candidate_name, deps=[NN_EXAMPLES_TABLE, *after], **NN_ASSET_KWARGS)
    def candidate(context: dagster.AssetExecutionContext) -> None:
        if skip_unconfigured(context):
            return
        context.add_output_metadata(
            train_candidate(context, s3_client(), dataset_bucket(), context.partition_key, family)
        )

    @dagster.asset(name=champion_name, deps=[candidate_name], **NN_ASSET_KWARGS)
    def champion(context: dagster.AssetExecutionContext) -> None:
        if skip_unconfigured(context):
            return
        metadata = decide_champion(context, s3_client(), dataset_bucket(), context.partition_key, family)
        context.add_output_metadata(metadata or {"skipped": dagster.MetadataValue.bool(True)})

    return FamilyAssets(candidate=candidate, champion=champion)


_NN_ASSETS = family_assets(NN_FAMILY, candidate_name=NN_CANDIDATE_ASSET, champion_name=NN_CHAMPION_ASSET)
inbox_ranking_nn_model_candidate = _NN_ASSETS.candidate
inbox_ranking_nn_model_champion = _NN_ASSETS.champion
_NN_WITH_PRIO_ASSETS = family_assets(
    NN_WITH_PRIO_FAMILY,
    candidate_name=NN_WITH_PRIO_CANDIDATE_ASSET,
    champion_name=NN_WITH_PRIO_CHAMPION_ASSET,
    after=[NN_CHAMPION_ASSET],
)
inbox_ranking_nn_with_prio_model_candidate = _NN_WITH_PRIO_ASSETS.candidate
inbox_ranking_nn_with_prio_model_champion = _NN_WITH_PRIO_ASSETS.champion


inbox_ranking_nn_training_job = dagster.define_asset_job(
    name="inbox_ranking_nn_training_job",
    selection=[
        NN_EXAMPLES_TABLE,
        NN_CANDIDATE_ASSET,
        NN_CHAMPION_ASSET,
        NN_WITH_PRIO_CANDIDATE_ASSET,
        NN_WITH_PRIO_CHAMPION_ASSET,
    ],
    tags={
        **owner_tags,
        # Five network fits per family (the train-only fit, NULL_PERMUTATIONS permuted-label fits and
        # the refit that ships), on CPU, one family after the other.
        "dagster/max_runtime": str(3 * 60 * 60),
        # The examples asset holds the lookback window's snapshots in pandas, as the main training job
        # does. A candidate holds one embeddings snapshot twice (as Arrow for the project vectors
        # and as the report side input), the report matrix, and one set of project vectors per
        # (team, day). The candidates run in sequence, so the limit covers one of them.
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"memory": "8Gi"},
                    "limits": {"memory": "24Gi"},
                }
            }
        },
    },
)


# After the dataset job's 2h budget (02:30 UTC start), so the dt=D-1 snapshots exist, and before the
# main training job (05:00 UTC) where the run is short enough. A candidate that lands after that
# job's manifest is paired by the next day's manifest.
@dagster.schedule(
    cron_schedule="30 4 * * *",
    job=inbox_ranking_nn_training_job,
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING
    if settings.CLOUD_DEPLOYMENT == "US"
    else dagster.DefaultScheduleStatus.STOPPED,
    tags=owner_tags,
)
def inbox_ranking_nn_training_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> dagster.RunRequest | dagster.SkipReason:
    if dataset_unconfigured():
        return dagster.SkipReason(f"{S3_BUCKET_ENV} is not set; skipping until the dedicated bucket is provisioned")
    previous_day = context.scheduled_execution_time.date() - datetime.timedelta(days=1)
    return dagster.RunRequest(partition_key=previous_day.isoformat(), run_key=f"nn-training-{previous_day.isoformat()}")
