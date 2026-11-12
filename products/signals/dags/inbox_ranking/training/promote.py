"""Manual promotion: a person chooses the model key the scoring sweep serves.

The daily serving publish already moves `served.json` to the newest passing version of the served
recipe once per auto-promotion interval (the `inbox-ranking-auto-promotion` flag payload, else
`INBOX_RANKING_AUTO_PROMOTE_INTERVAL_DAYS`). A person runs this job for what the automatic step never
does: a first promotion, a switch to another `model_name`, and a rollback.

`inbox_ranking_promote_job` writes `inbox_ranking_models/v1/served.json`, then publishes the serving
manifest for the newest dataset partition, so the change reaches the sweep without waiting for the
daily training run. Rollback is the same job with an older key, of any `model_name`: a person's
choice has no "newer than the incumbent" rule. The new `promoted_at` also restarts the automatic
interval, and `hold_auto_promotion` in the overrides payload keeps the automatic step from moving a
rollback forward again.

The job checks the model before it writes anything. A malformed key, a model that this build cannot
serve, a missing model file, or a model without every head in `HEADS` fails the run, and the
pointer and the manifest stay as they are.
"""

import datetime

import dagster
import pydantic

from posthog import settings

from products.signals.dags.inbox_ranking.common import (
    S3_BUCKET_ENV,
    dataset_bucket,
    dataset_unconfigured,
    owner_tags,
    partition_object_key,
    s3_client,
)
from products.signals.dags.inbox_ranking.dataset.dag import PROJECT_VECTORS_TABLE
from products.signals.dags.inbox_ranking.training.dag import (
    PromotionRefused,
    _object_exists,
    _publish_manifest,
    promotable_model,
    read_served_pointer,
    write_served_pointer,
)

# The dataset job writes a day's partitions the next morning, so the newest one is at least a day
# old. A gap longer than this means the dataset job is broken, and the publish waits for it.
MAX_PARTITION_AGE_DAYS = 7


class PromoteConfig(dagster.Config):
    model_key: str = pydantic.Field(description="The model key to serve, as `<model_name>@<YYYY-MM-DD>`.")
    reason: str = pydantic.Field(description="Why this model is served. Recorded in `served.json` and the event.")


def newest_partition(client, bucket: str, prefix: str, today: datetime.date) -> str:
    """The newest day whose project vectors exist. A served `nn` model reads that day, so the
    publish needs it, as the daily manifest does."""
    for offset in range(1, MAX_PARTITION_AGE_DAYS + 1):
        day = (today - datetime.timedelta(days=offset)).isoformat()
        if _object_exists(client, bucket, partition_object_key(prefix, PROJECT_VECTORS_TABLE, day)):
            return day
    raise PromotionRefused(f"no {PROJECT_VECTORS_TABLE} partition in the last {MAX_PARTITION_AGE_DAYS} days")


@dagster.op(tags=owner_tags)
def inbox_ranking_promote(context: dagster.OpExecutionContext, config: PromoteConfig) -> None:
    if dataset_unconfigured():
        raise dagster.Failure(f"{S3_BUCKET_ENV} is not set on this Cloud deployment; nothing to promote")
    reason = config.reason.strip()
    if not reason:
        raise dagster.Failure("reason is empty; say why this model is served")
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()
    now = datetime.datetime.now(datetime.UTC)
    try:
        metadata = promotable_model(client, bucket, prefix, config.model_key)
        partition_key = newest_partition(client, bucket, prefix, now.date())
    except PromotionRefused as error:
        raise dagster.Failure(f"not promoted: {error}") from error

    pointer = write_served_pointer(
        context,
        client,
        bucket,
        prefix,
        metadata,
        reason=reason,
        previous=read_served_pointer(client, bucket, prefix),
        partition_key=partition_key,
        run_id=context.run_id,
        promoted_at=now,
        auto=False,
    )

    published = _publish_manifest(context, partition_key, context.run_id)
    if not published["published"].value:
        raise dagster.Failure(
            f"served.json names {pointer['model_key']}, but no manifest was published for dt={partition_key}; "
            "the previous manifest keeps serving until the next training run publishes one"
        )
    context.log.info(f"published the serving manifest for dt={partition_key}: {published['served_key'].value}")


@dagster.job(name="inbox_ranking_promote_job", tags=owner_tags)
def inbox_ranking_promote_job() -> None:
    inbox_ranking_promote()
