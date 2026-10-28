"""Daily training for the experiment families (`experiment_families()` in `training/families.py`).

An experiment is a modeling idea under test. It trains in this job, apart from the `nn` training
job, so it never costs the serving families' runtime or memory budget. It reads the day's
`inbox_ranking_nn_examples` object that the `nn` job wrote and never rebuilds it:

    inbox_ranking_models/v1/<model_name>/dt=D/   the experiment's graphs and metadata.json, with a vs_baseline block

The `vs_baseline` block fits the experiment and its baseline with each of `EXPERIMENT_SEEDS` on the
same train rows, and grades both on the same holdout rows, so each seed gives a paired AUC gap.
An experiment never enters the serving manifest and cannot be promoted or pinned. It stops training
after its `expires` day, and a partition without examples is skipped and keeps what it holds.
"""

import datetime

import dagster

from posthog import settings

from products.signals.dags.inbox_ranking.common import (
    S3_BUCKET_ENV,
    dataset_bucket,
    dataset_unconfigured,
    owner_tags,
    partition_object_key,
    s3_client,
    skip_unconfigured,
)
from products.signals.dags.inbox_ranking.nn.dag import NN_ASSET_KWARGS, NN_EXAMPLES_TABLE, train_candidate
from products.signals.dags.inbox_ranking.training.dag import _object_exists
from products.signals.dags.inbox_ranking.training.families import ModelFamily, experiment_families

NN_EXPERIMENTS_ASSET = "inbox_ranking_nn_experiment_candidates"


def live_experiments(families: tuple[ModelFamily, ...], day: datetime.date) -> tuple[ModelFamily, ...]:
    return tuple(family for family in families if not family.expired(day))


def run_experiments(
    context: dagster.AssetExecutionContext, client, bucket: str, partition_key: str, families: tuple[ModelFamily, ...]
) -> dict[str, dagster.MetadataValue]:
    """Train each live experiment in `families` for dt=`partition_key`, one after the other, and
    return the asset metadata. An expired experiment and a partition without examples write nothing."""
    day = datetime.date.fromisoformat(partition_key)
    metadata: dict[str, dagster.MetadataValue] = {}
    for family in families:
        if family.expired(day):
            context.log.info(f"{family.name} expired on {family.expires}; skipped for dt={partition_key}")
            metadata[f"{family.name}_skipped"] = dagster.MetadataValue.text(f"expired on {family.expires}")
    live = live_experiments(families, day)
    if not live:
        return {**metadata, "skipped": dagster.MetadataValue.bool(True)}
    examples_key = partition_object_key(settings.INBOX_RANKING_DATASET_S3_PREFIX, NN_EXAMPLES_TABLE, partition_key)
    if not _object_exists(client, bucket, examples_key):
        context.log.warning(f"no nn examples for dt={partition_key}; every experiment skips this partition")
        return {**metadata, "skipped": dagster.MetadataValue.bool(True)}
    for family in live:
        for name, value in train_candidate(context, client, bucket, partition_key, family).items():
            metadata[f"{family.name}_{name}"] = value
    return metadata


@dagster.asset(name=NN_EXPERIMENTS_ASSET, deps=[NN_EXAMPLES_TABLE], **NN_ASSET_KWARGS)
def inbox_ranking_nn_experiment_candidates(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    context.add_output_metadata(
        run_experiments(context, s3_client(), dataset_bucket(), context.partition_key, experiment_families())
    )


inbox_ranking_nn_experiments_job = dagster.define_asset_job(
    name="inbox_ranking_nn_experiments_job",
    selection=[NN_EXPERIMENTS_ASSET],
    tags={
        **owner_tags,
        # Per experiment: the five network fits of a candidate, then one fit per seed for each of
        # the experiment and its baseline. The experiments run one after the other.
        "dagster/max_runtime": str(4 * 60 * 60),
        # As the nn job's candidate, plus the baseline's report matrix, held for the paired fits.
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"memory": "8Gi"},
                    "limits": {"memory": "32Gi"},
                }
            }
        },
    },
)


# After the nn job's 3h budget (04:30 UTC start), so the dt=D-1 examples exist.
@dagster.schedule(
    cron_schedule="0 8 * * *",
    job=inbox_ranking_nn_experiments_job,
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING
    if settings.CLOUD_DEPLOYMENT == "US"
    else dagster.DefaultScheduleStatus.STOPPED,
    tags=owner_tags,
)
def inbox_ranking_nn_experiments_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> dagster.RunRequest | dagster.SkipReason:
    if dataset_unconfigured():
        return dagster.SkipReason(f"{S3_BUCKET_ENV} is not set; skipping until the dedicated bucket is provisioned")
    previous_day = context.scheduled_execution_time.date() - datetime.timedelta(days=1)
    if not live_experiments(experiment_families(), previous_day):
        return dagster.SkipReason(f"no experiment family is live on {previous_day.isoformat()}")
    return dagster.RunRequest(
        partition_key=previous_day.isoformat(), run_key=f"nn-experiments-{previous_day.isoformat()}"
    )
