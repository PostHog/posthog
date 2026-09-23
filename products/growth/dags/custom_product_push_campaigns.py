"""Dagster job that creates custom product push campaigns for a list of organizations.

Growth names the organizations, the product, and the window the push should run
for. The job creates one SCHEDULED, TAM-sourced `ProductPushCampaign` per
organization, and the daily `product_push_campaigns_job` starts it on or after
`starts_on` and closes it at `ends_on` — so a custom push joins the normal campaign
lifecycle instead of bypassing it.

Two things the operator has to decide per run, because no default is safe:

- `on_active_campaign` — an organization can already be running a campaign, and
  only one runs at a time. `skip` writes nothing for it, `queue` starts the custom
  push once the running one closes, `override` cancels the running one. A queued
  push is refused when the running campaign is planned to outlast the window,
  since it would expire before getting to run.
- `starts_on` / `ends_on` — the campaign window. Dating the campaign also overrides
  the signup grace period and the between-campaigns cooldown.

Re-running with the same organization list creates nothing new: an organization
that already holds a scheduled or active campaign for the product is counted and
skipped.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, time

from django.conf import settings
from django.db import connections

import dagster
import pydantic

from posthog.clickhouse.query_tagging import get_query_tags
from posthog.dags.common import JobOwners, dagster_tags
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.schema_enums import ProductKey

from products.growth.backend.product_push.selection import (
    BLESSED_PRODUCT_ORDER,
    FALLBACK_PRODUCT_ORDER,
    PUSH_PRODUCT_PATHS,
)
from products.growth.backend.product_push.service import (
    ON_ACTIVE_POLICIES,
    CustomProductPushBatchResult,
    create_custom_product_push_campaigns_for_org_batch,
)

CUSTOM_PUSH_BATCH_SIZE = 500

_BATCH_OP_RETRY_POLICY = dagster.RetryPolicy(
    max_retries=3,
    delay=30,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.FULL,
)


@frozen
class CustomProductPushBatchSpec:
    organization_ids: list[str]
    product_key: str
    starts_on: date
    ends_at: datetime
    on_active_campaign: str
    reason_text: str | None
    skip_recently_pushed: bool
    dry_run: bool


class CustomProductPushCampaignConfig(dagster.Config):
    """Config for the custom product push campaign job."""

    organization_ids: list[str] = pydantic.Field(
        description="Organization ids (UUIDs) to create the campaign for.",
        min_length=1,
    )
    product_key: str = pydantic.Field(
        description="ProductKey value of the product to push, e.g. 'session_replay'.",
    )
    starts_on: str = pydantic.Field(
        description="First day the campaign may start (YYYY-MM-DD). The daily sweep starts it on or after "
        "this date, and a dated campaign overrides the signup grace period and the between-campaigns cooldown.",
    )
    ends_on: str = pydantic.Field(
        description="Last day the campaign runs (YYYY-MM-DD), inclusive. A campaign that never got to start "
        "by then is cancelled instead of shown late.",
    )
    on_active_campaign: str = pydantic.Field(
        description="What to do with an organization that is already running a campaign: "
        "'skip' writes nothing for it, 'queue' starts this campaign once the running one closes, "
        "'override' cancels the running one so this campaign starts on the next sweep.",
    )
    reason_text: str | None = pydantic.Field(
        default=None,
        description="Custom promo copy shown on the card. Empty uses the product's default copy.",
    )
    skip_recently_pushed: bool = pydantic.Field(
        default=True,
        description="Skip organizations that were pushed this same product in the last 90 days. "
        "Turn off only when the repeat push is deliberate.",
    )
    batch_size: int = pydantic.Field(default=CUSTOM_PUSH_BATCH_SIZE, gt=0)
    max_campaigns: int | None = pydantic.Field(
        default=None,
        description="Cap on how many campaigns this run may create (herd control for large lists).",
        gt=0,
    )
    dry_run: bool = pydantic.Field(
        default=False,
        description="Log what would be created without writing campaigns or emitting events.",
    )


def _parse_window(config: CustomProductPushCampaignConfig) -> tuple[date, datetime]:
    try:
        starts_on = date.fromisoformat(config.starts_on)
        ends_on = date.fromisoformat(config.ends_on)
    except ValueError:
        raise dagster.Failure(
            f"starts_on and ends_on must be YYYY-MM-DD dates, got {config.starts_on!r} and {config.ends_on!r}"
        )
    if ends_on < starts_on:
        raise dagster.Failure(f"ends_on ({ends_on}) is before starts_on ({starts_on})")
    # ends_on is inclusive, so the campaign runs to the end of that day.
    return starts_on, datetime.combine(ends_on, time.max, tzinfo=UTC)


@dagster.op(out=dagster.DynamicOut(CustomProductPushBatchSpec))
def get_custom_product_push_batches_op(
    context: dagster.OpExecutionContext, config: CustomProductPushCampaignConfig
) -> Iterator[dagster.DynamicOutput[CustomProductPushBatchSpec]]:
    """Validate the config and fan out the organization list as batches."""
    try:
        product_key = ProductKey(config.product_key)
    except ValueError:
        raise dagster.Failure(f"product_key must be a valid ProductKey value, got {config.product_key!r}")

    if config.on_active_campaign not in ON_ACTIVE_POLICIES:
        raise dagster.Failure(
            f"on_active_campaign must be one of {', '.join(ON_ACTIVE_POLICIES)}, got {config.on_active_campaign!r}"
        )

    starts_on, ends_at = _parse_window(config)
    now = datetime.now(tz=UTC)
    if ends_at <= now:
        raise dagster.Failure(f"ends_on ({config.ends_on}) is already past — the campaign would never run")

    if product_key not in PUSH_PRODUCT_PATHS:
        context.log.warning(
            f"{product_key.value} has no curated catalog path — the card falls back to intent inference, "
            "which resolves to the wrong product for several keys. Add it to PUSH_PRODUCT_PATHS first."
        )
    if product_key not in BLESSED_PRODUCT_ORDER and product_key not in FALLBACK_PRODUCT_ORDER:
        context.log.warning(
            f"{product_key.value} is outside the automatic push lists, so it may be feature-flag gated or "
            "unreleased. The card is hidden for users without the flag, and this run will still report "
            "the campaigns as created."
        )

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
        f"Creating {product_key.value} campaigns for {len(organization_ids)} organizations, running "
        f"{starts_on} to {config.ends_on} (on_active_campaign={config.on_active_campaign}, dry_run={config.dry_run})"
    )

    def spec(ids: list[str]) -> CustomProductPushBatchSpec:
        return CustomProductPushBatchSpec(
            organization_ids=ids,
            product_key=product_key.value,
            starts_on=starts_on,
            ends_at=ends_at,
            on_active_campaign=config.on_active_campaign,
            reason_text=config.reason_text or None,
            skip_recently_pushed=config.skip_recently_pushed,
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
def create_custom_product_push_batch_op(
    context: dagster.OpExecutionContext, spec: CustomProductPushBatchSpec
) -> CustomProductPushBatchResult:
    """Create campaigns for the organizations in this batch. Retry-safe: an org that
    already holds a pending campaign for the product is skipped, and the partial
    unique constraint turns a concurrent double-write into a counted conflict."""
    get_query_tags().with_dagster(dagster_tags(context))
    try:
        result = create_custom_product_push_campaigns_for_org_batch(
            spec.organization_ids,
            spec.product_key,
            now=datetime.now(tz=UTC),
            starts_on=spec.starts_on,
            ends_at=spec.ends_at,
            on_active_campaign=spec.on_active_campaign,
            reason_text=spec.reason_text,
            skip_recently_pushed=spec.skip_recently_pushed,
            dry_run=spec.dry_run,
        )
        context.log.info(
            f"Batch of {result.orgs_processed} orgs: {result.created} created "
            f"({result.queued_behind_active} queued behind a running campaign, "
            f"{result.overrode_active} overrode one), {result.would_create} would create, "
            f"{result.blocked_by_active} blocked by a running campaign, "
            f"{result.window_unreachable} without room in the window, {result.already_pending} already pending, "
            f"{result.already_adopted} already adopted, {result.in_retry_cooldown} pushed this product recently, "
            f"{result.conflicts} conflicts"
        )
        return result
    except Exception as e:
        context.log.exception(f"Failed to create campaigns for batch of {len(spec.organization_ids)} orgs")
        capture_exception(e, {"team": "team-growth", "org_count": len(spec.organization_ids)})
        raise
    finally:
        if not settings.TEST:
            connections.close_all()


@dagster.op
def summarize_custom_product_push_run_op(
    context: dagster.OpExecutionContext, results: list[CustomProductPushBatchResult]
) -> None:
    """Roll up per-batch counts into a single run-level summary."""
    created = sum(r.created for r in results)
    would_create = sum(r.would_create for r in results)

    context.log.info(f"Run complete: {created} campaigns created, {would_create} would be created")
    context.add_output_metadata(
        {
            "orgs_processed": dagster.MetadataValue.int(sum(r.orgs_processed for r in results)),
            "campaigns_created": dagster.MetadataValue.int(created),
            "campaigns_would_create": dagster.MetadataValue.int(would_create),
            "queued_behind_active": dagster.MetadataValue.int(sum(r.queued_behind_active for r in results)),
            "overrode_active": dagster.MetadataValue.int(sum(r.overrode_active for r in results)),
            "skipped_blocked_by_active": dagster.MetadataValue.int(sum(r.blocked_by_active for r in results)),
            "skipped_window_unreachable": dagster.MetadataValue.int(sum(r.window_unreachable for r in results)),
            "skipped_already_pending": dagster.MetadataValue.int(sum(r.already_pending for r in results)),
            "skipped_already_adopted": dagster.MetadataValue.int(sum(r.already_adopted for r in results)),
            "skipped_pushed_recently": dagster.MetadataValue.int(sum(r.in_retry_cooldown for r in results)),
            "conflicts": dagster.MetadataValue.int(sum(r.conflicts for r in results)),
        }
    )


@dagster.job(
    description=(
        "Create a custom product push campaign for a list of organizations, running for a given window. "
        "Campaigns land as scheduled and are started and closed by the daily product push job."
    ),
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 5}),
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def custom_product_push_campaigns_job() -> None:
    results = get_custom_product_push_batches_op().map(create_custom_product_push_batch_op).collect()
    summarize_custom_product_push_run_op(results)
