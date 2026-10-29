"""Daily training for the experiment families (`experiment_families()` in `training/families.py`).

An experiment is a modeling idea under test. It trains in this job, apart from the `nn` training
job, so it never costs the serving families' runtime or memory budget. It reads the day's
`inbox_ranking_nn_examples` object that the `nn` job wrote and never rebuilds it:

    inbox_ranking_models/v1/<model_name>/dt=D/   the experiment's graphs and metadata.json, with a vs_baseline block

The `vs_baseline` block fits the experiment and its baseline with each of `EXPERIMENT_SEEDS` on the
same train rows, and grades both on the same holdout rows, so each seed gives a paired AUC gap.
An experiment never enters the serving manifest and cannot be promoted or pinned. It stops training
after its `expires` day, and a partition without examples is skipped and keeps what it holds.

A pair-grain experiment trains in the pair lane (`nn/pair_lane.py`) on the day's
`inbox_ranking_nn_pair_examples` object as well, and is graded within user against its pair baseline
and its report-level reference (`nn/pair_grade.py`). The job builds that object for the same
partition first, from the day's report examples, and the pair experiments asset depends on it. The
report and the pair experiments are two assets, so a failed pair examples step skips the pair
experiments only. The job runs its steps in one process, one after the other, so two vector-heavy
steps never share the pod's memory. A partition without pair examples skips the pair families only.
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
from products.signals.dags.inbox_ranking.nn.pair_lane import train_pair_candidate
from products.signals.dags.inbox_ranking.nn.pairs import NN_PAIR_EXAMPLES_TABLE
from products.signals.dags.inbox_ranking.training.dag import _object_exists
from products.signals.dags.inbox_ranking.training.families import (
    PAIR_GRAIN,
    REPORT_GRAIN,
    ModelFamily,
    experiment_families,
)

# The report-grain experiments keep the asset name they had before pair grain, so their Dagster
# history continues.
NN_EXPERIMENTS_ASSET = "inbox_ranking_nn_experiment_candidates"
NN_PAIR_EXPERIMENTS_ASSET = "inbox_ranking_nn_pair_experiment_candidates"


def live_experiments(families: tuple[ModelFamily, ...], day: datetime.date) -> tuple[ModelFamily, ...]:
    return tuple(family for family in families if not family.expired(day))


def grain_experiments(families: tuple[ModelFamily, ...], grain: str) -> tuple[ModelFamily, ...]:
    return tuple(family for family in families if family.grain == grain)


def experiment_selection(families: tuple[ModelFamily, ...], day: datetime.date) -> list[str]:
    """The assets a run for `day` materializes: the report experiments when one is live, and the pair
    examples with the pair experiments when a pair experiment is live. Empty when nothing is live."""
    live = live_experiments(families, day)
    selection: list[str] = []
    if grain_experiments(live, REPORT_GRAIN):
        selection.append(NN_EXPERIMENTS_ASSET)
    if grain_experiments(live, PAIR_GRAIN):
        selection += [NN_PAIR_EXAMPLES_TABLE, NN_PAIR_EXPERIMENTS_ASSET]
    return selection


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
        train = train_pair_candidate if family.grain == PAIR_GRAIN else train_candidate
        for name, value in train(context, client, bucket, partition_key, family).items():
            metadata[f"{family.name}_{name}"] = value
    return metadata


@dagster.asset(name=NN_EXPERIMENTS_ASSET, deps=[NN_EXAMPLES_TABLE], **NN_ASSET_KWARGS)
def inbox_ranking_nn_experiment_candidates(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    context.add_output_metadata(
        run_experiments(
            context,
            s3_client(),
            dataset_bucket(),
            context.partition_key,
            grain_experiments(experiment_families(), REPORT_GRAIN),
        )
    )


@dagster.asset(name=NN_PAIR_EXPERIMENTS_ASSET, deps=[NN_EXAMPLES_TABLE, NN_PAIR_EXAMPLES_TABLE], **NN_ASSET_KWARGS)
def inbox_ranking_nn_pair_experiment_candidates(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    context.add_output_metadata(
        run_experiments(
            context,
            s3_client(),
            dataset_bucket(),
            context.partition_key,
            grain_experiments(experiment_families(), PAIR_GRAIN),
        )
    )


inbox_ranking_nn_experiments_job = dagster.define_asset_job(
    name="inbox_ranking_nn_experiments_job",
    selection=[NN_EXPERIMENTS_ASSET, NN_PAIR_EXAMPLES_TABLE, NN_PAIR_EXPERIMENTS_ASSET],
    # One step at a time: the multiprocess default would run the report experiments beside the pair
    # examples, and the memory limit below covers one of them.
    executor_def=dagster.in_process_executor,
    tags={
        **owner_tags,
        # Per experiment: the five network fits of a candidate, then one fit per seed for each of
        # the experiment and its baseline. The experiments run one after the other. A pair
        # experiment adds one report-grain fit per seed for its reference, and its fits run over
        # the pair rows, a few times the report rows. The pair examples step comes before the pair
        # experiments and is bounded by its own job's 2h budget.
        "dagster/max_runtime": str(6 * 60 * 60),
        # As the nn job's candidate, plus the baseline's report matrix, held for the paired fits.
        # A pair experiment holds its own and its baseline's pair report matrices (pair rows x
        # 1536 floats each) and fits the reference before building them, so the reference's report
        # matrix is gone by then. Pair rows a few times the report rows stay well inside the limit.
        # The user offsets are one vector per (team, user, day), not per pair.
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
    selection = experiment_selection(experiment_families(), previous_day)
    if not selection:
        return dagster.SkipReason(f"no experiment family is live on {previous_day.isoformat()}")
    return dagster.RunRequest(
        partition_key=previous_day.isoformat(),
        run_key=f"nn-experiments-{previous_day.isoformat()}",
        asset_selection=[dagster.AssetKey(name) for name in selection],
    )
