"""Dagster job that queues a product push campaign for a list of organizations.

Growth names an organization list and one product; the job queues a SCHEDULED,
TAM-sourced `ProductPushCampaign` per organization. The daily
`product_push_campaigns_job` then starts each one when the organization has no
active campaign, so a bulk push joins the normal campaign lifecycle instead of
bypassing it.

Cadence: by default the campaign is queued without a date, so the daily sweep
still applies the signup grace period and the between-campaigns cooldown, and an
organization pushed this product recently is left alone. `bypass_cadence` pins
the campaign to today, which overrides all three — use it only when the push is
time-critical.

Re-running with the same organization list creates nothing new: an organization
that already holds a scheduled or active campaign for the product is counted and
skipped.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from django.conf import settings
from django.db import connections

import dagster
import pydantic

from posthog.clickhouse.query_tagging import get_query_tags
from posthog.dags.common import JobOwners, dagster_tags
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.schema_enums import ProductKey

from products.growth.backend.product_push.selection import (
    BLESSED_PRODUCT_ORDER,
    FALLBACK_PRODUCT_ORDER,
    PUSH_PRODUCT_PATHS,
)
from products.growth.backend.product_push.service import ScheduleBatchResult, schedule_campaigns_for_org_batch

BULK_BATCH_SIZE = 500

_BATCH_OP_RETRY_POLICY = dagster.RetryPolicy(
    max_retries=3,
    delay=30,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.FULL,
)


@dataclass(kw_only=True)
class ScheduleBatchSpec:
    organization_ids: list[str]
    product_key: str
    scheduled_for: date | None
    reason_text: str | None
    skip_recently_pushed: bool
    dry_run: bool


class BulkProductPushConfig(dagster.Config):
    """Config for the bulk product push campaign job."""

    organization_ids: list[str] = pydantic.Field(
        description="Organization ids (UUIDs) to queue the campaign for.",
        min_length=1,
    )
    product_key: str = pydantic.Field(
        description="ProductKey value of the product to push, e.g. 'session_replay'.",
    )
    scheduled_for: str | None = pydantic.Field(
        default=None,
        description="Start the campaign on or after this date (YYYY-MM-DD). A dated campaign overrides "
        "the signup grace period and the between-campaigns cooldown.",
    )
    bypass_cadence: bool = pydantic.Field(
        default=False,
        description="Push regardless of cadence: date the campaign today so the next daily sweep starts it, "
        "and include organizations that were pushed this product recently. Leave off to let the daily "
        "sweep apply the normal cadence.",
    )
    reason_text: str | None = pydantic.Field(
        default=None,
        description="Custom promo copy shown on the card. Empty uses the product's default copy.",
    )
    batch_size: int = pydantic.Field(default=BULK_BATCH_SIZE, gt=0)
    max_campaigns: int | None = pydantic.Field(
        default=None,
        description="Cap on how many campaigns this run may queue (herd control for large lists).",
        gt=0,
    )
    dry_run: bool = pydantic.Field(
        default=False,
        description="Log what would be queued without writing campaigns or emitting events.",
    )


def _parse_scheduled_for(config: BulkProductPushConfig, today: date) -> date | None:
    if config.scheduled_for:
        try:
            return date.fromisoformat(config.scheduled_for)
        except ValueError:
            raise dagster.Failure(f"scheduled_for must be a YYYY-MM-DD date, got {config.scheduled_for!r}")
    return today if config.bypass_cadence else None


@dagster.op(out=dagster.DynamicOut(ScheduleBatchSpec))
def get_bulk_push_batches_op(context: dagster.OpExecutionContext, config: BulkProductPushConfig):
    """Validate the config and fan out the organization list as batches."""
    try:
        product_key = ProductKey(config.product_key)
    except ValueError:
        raise dagster.Failure(f"product_key must be a valid ProductKey value, got {config.product_key!r}")

    if product_key not in PUSH_PRODUCT_PATHS:
        context.log.warning(
            f"{product_key.value} has no curated catalog path — the card falls back to intent inference, "
            "which resolves to the wrong product for several keys. Add it to PUSH_PRODUCT_PATHS first."
        )
    if product_key not in BLESSED_PRODUCT_ORDER and product_key not in FALLBACK_PRODUCT_ORDER:
        context.log.warning(
            f"{product_key.value} is outside the automatic push lists, so it may be feature-flag gated or "
            "unreleased. The card is hidden for users without the flag, and this run will still report "
            "the campaigns as queued."
        )

    now = datetime.now(tz=UTC)
    scheduled_for = _parse_scheduled_for(config, now.date())

    requested_ids = list(dict.fromkeys(config.organization_ids))
    organization_ids = [
        str(organization_id)
        for organization_id in Organization.objects.filter(id__in=requested_ids).values_list("id", flat=True)
    ]
    missing = len(requested_ids) - len(organization_ids)
    if missing:
        context.log.warning(f"{missing} of {len(requested_ids)} organization ids do not exist and are ignored")
    if config.max_campaigns is not None and len(organization_ids) > config.max_campaigns:
        context.log.info(f"Capping at max_campaigns={config.max_campaigns} of {len(organization_ids)} organizations")
        organization_ids = organization_ids[: config.max_campaigns]

    context.log.info(
        f"Queuing {product_key.value} for {len(organization_ids)} organizations "
        f"(scheduled_for={scheduled_for}, bypass_cadence={config.bypass_cadence}, dry_run={config.dry_run})"
    )

    def spec(ids: list[str]) -> ScheduleBatchSpec:
        return ScheduleBatchSpec(
            organization_ids=ids,
            product_key=product_key.value,
            scheduled_for=scheduled_for,
            reason_text=config.reason_text or None,
            skip_recently_pushed=not config.bypass_cadence,
            dry_run=config.dry_run,
        )

    # Always yield one batch so the summary op runs even when nothing matched.
    if not organization_ids:
        yield dagster.DynamicOutput(spec([]), mapping_key="batch_0")
        return
    for index in range(0, len(organization_ids), config.batch_size):
        yield dagster.DynamicOutput(
            spec(organization_ids[index : index + config.batch_size]),
            mapping_key=f"batch_{index // config.batch_size}",
        )


@dagster.op(retry_policy=_BATCH_OP_RETRY_POLICY)
def schedule_campaign_batch_op(context: dagster.OpExecutionContext, spec: ScheduleBatchSpec) -> ScheduleBatchResult:
    """Queue campaigns for the organizations in this batch. Retry-safe: an org that
    already holds a pending campaign for the product is skipped, and the partial
    unique constraint turns a concurrent double-write into a counted conflict."""
    get_query_tags().with_dagster(dagster_tags(context))
    try:
        result = schedule_campaigns_for_org_batch(
            spec.organization_ids,
            spec.product_key,
            now=datetime.now(tz=UTC),
            scheduled_for=spec.scheduled_for,
            reason_text=spec.reason_text,
            skip_recently_pushed=spec.skip_recently_pushed,
            dry_run=spec.dry_run,
        )
        context.log.info(
            f"Batch of {result.orgs_processed} orgs: {result.scheduled} scheduled "
            f"({result.queued_behind_active} behind an active campaign), {result.would_schedule} would schedule, "
            f"{result.already_pending} already pending, {result.already_adopted} already adopted, "
            f"{result.in_retry_cooldown} in retry cooldown, {result.conflicts} conflicts"
        )
        return result
    except Exception as e:
        context.log.exception(f"Failed to queue campaigns for batch of {len(spec.organization_ids)} orgs")
        capture_exception(e, {"team": "team-growth", "org_count": len(spec.organization_ids)})
        raise
    finally:
        if not settings.TEST:
            connections.close_all()


@dagster.op
def summarize_bulk_push_run_op(context: dagster.OpExecutionContext, results: list[ScheduleBatchResult]) -> None:
    """Roll up per-batch counts into a single run-level summary."""
    scheduled = sum(r.scheduled for r in results)
    would_schedule = sum(r.would_schedule for r in results)

    context.log.info(f"Run complete: {scheduled} campaigns scheduled, {would_schedule} would be scheduled")
    context.add_output_metadata(
        {
            "orgs_processed": dagster.MetadataValue.int(sum(r.orgs_processed for r in results)),
            "campaigns_scheduled": dagster.MetadataValue.int(scheduled),
            "campaigns_would_schedule": dagster.MetadataValue.int(would_schedule),
            "queued_behind_active": dagster.MetadataValue.int(sum(r.queued_behind_active for r in results)),
            "skipped_already_pending": dagster.MetadataValue.int(sum(r.already_pending for r in results)),
            "skipped_already_adopted": dagster.MetadataValue.int(sum(r.already_adopted for r in results)),
            "skipped_in_retry_cooldown": dagster.MetadataValue.int(sum(r.in_retry_cooldown for r in results)),
            "conflicts": dagster.MetadataValue.int(sum(r.conflicts for r in results)),
        }
    )


@dagster.job(
    description=(
        "Queue a product push campaign for a list of organizations. Campaigns land as scheduled and are "
        "started by the daily product push job."
    ),
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 5}),
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def bulk_product_push_job():
    results = get_bulk_push_batches_op().map(schedule_campaign_batch_op).collect()
    summarize_bulk_push_run_op(results)
