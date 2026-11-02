"""Manual promotion: a person chooses the model key the scoring sweep serves.

`inbox_ranking_promote_job` writes `inbox_ranking_models/v1/served.json`, then publishes the serving
manifest for the newest dataset partition, so the change reaches the sweep without waiting for the
daily training run. Rollback is the same job with an older key, of any `model_name`: a person's
choice has no "newer than the incumbent" rule.

The job checks the model before it writes anything. A malformed key, a model that this build cannot
serve, a missing model file, or a model without every head in `HEADS` fails the run, and the
pointer and the manifest stay as they are.
"""

import datetime
from collections.abc import Mapping
from typing import Any

import dagster
import pydantic
from botocore.exceptions import ClientError

from posthog import settings

from products.signals.backend.ranking.model_contract import trained_head_files
from products.signals.backend.ranking.overrides import MODEL_KEY_PATTERN
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
    _object_exists,
    _pin_metadata,
    _publish_manifest,
    _put_json,
    read_served_pointer,
    served_object_key,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME
from products.signals.dags.inbox_ranking.training.telemetry import capture_training_events, model_promoted_event

# The dataset job writes a day's partitions the next morning, so the newest one is at least a day
# old. A gap longer than this means the dataset job is broken, and the publish waits for it.
MAX_PARTITION_AGE_DAYS = 7


class PromotionRefused(ValueError):
    pass


class PromoteConfig(dagster.Config):
    model_key: str = pydantic.Field(description="The model key to serve, as `<model_name>@<YYYY-MM-DD>`.")
    reason: str = pydantic.Field(description="Why this model is served. Recorded in `served.json` and the event.")


def promotable_model(client, bucket: str, prefix: str, model_key: str) -> dict[str, Any]:
    """The metadata of the model `model_key` names. Raises `PromotionRefused` when the sweep could
    not serve it with every head the inbox reads."""
    if not MODEL_KEY_PATTERN.match(model_key):
        raise PromotionRefused(f"{model_key!r} is not a `<model_name>@<YYYY-MM-DD>` model key")
    try:
        metadata, reason = _pin_metadata(client, bucket, prefix, model_key)
    except ClientError as error:
        raise PromotionRefused(f"could not read {model_key}: {error!r}") from error
    if metadata is None:
        raise PromotionRefused(f"{model_key} cannot be served: {reason}")
    missing_heads = sorted(set(HEADS_BY_NAME) - set(trained_head_files(metadata, HEADS_BY_NAME)))
    if missing_heads:
        raise PromotionRefused(f"{model_key} has no model for the heads {', '.join(missing_heads)}")
    return metadata


def newest_partition(client, bucket: str, prefix: str, today: datetime.date) -> str:
    """The newest day whose project vectors exist. A served `nn` model reads that day, so the
    publish needs it, as the daily manifest does."""
    for offset in range(1, MAX_PARTITION_AGE_DAYS + 1):
        day = (today - datetime.timedelta(days=offset)).isoformat()
        if _object_exists(client, bucket, partition_object_key(prefix, PROJECT_VECTORS_TABLE, day)):
            return day
    raise PromotionRefused(f"no {PROJECT_VECTORS_TABLE} partition in the last {MAX_PARTITION_AGE_DAYS} days")


def served_pointer(
    metadata: Mapping[str, Any],
    *,
    reason: str,
    previous: Mapping[str, Any] | None,
    run_id: str,
    promoted_at: datetime.datetime,
) -> dict[str, Any]:
    return {
        "model_key": f"{metadata['model_name']}@{metadata['model_version']}",
        "model_name": metadata["model_name"],
        "model_version": metadata["model_version"],
        "promoted_at": promoted_at.isoformat(),
        "reason": reason,
        "previous_key": (previous or {}).get("model_key"),
        "run_id": run_id,
    }


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

    previous = read_served_pointer(client, bucket, prefix)
    pointer = served_pointer(metadata, reason=reason, previous=previous, run_id=context.run_id, promoted_at=now)
    _put_json(client, bucket, served_object_key(prefix), pointer)
    context.log.info(f"served.json now names {pointer['model_key']} (was {pointer['previous_key']})")
    capture_training_events(
        context,
        partition_key,
        [
            model_promoted_event(
                model_key=pointer["model_key"],
                previous_key=pointer["previous_key"],
                reason=reason,
                run_id=context.run_id,
            )
        ],
        timestamp=now,
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
