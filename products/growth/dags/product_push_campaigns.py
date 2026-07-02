"""Daily Dagster job driving organization product push campaigns.

Two sequenced phases:

1. Close — evaluate every ACTIVE campaign: close as adopted when the org started
   using the product, as skipped when the 30-day window expired without adoption.
2. Start — start the next campaign for every eligible org (past the signup grace
   period, no active campaign, out of the between-campaigns cooldown, or holding a
   due dated TAM pin).

The start phase depends on the collected close results so a campaign that expires
today frees its org for cadence evaluation in the same run (the cooldown then
keeps it quiet for 15 days).

All business logic lives in products/growth/backend/product_push/; this file only
orchestrates. Rollout controls (`rollout_percentage`, `max_starts`, `dry_run`)
exist for the first supervised runs: on day one every org older than the grace
period is eligible at once, so ramp gradually to stagger cadence phases across
the fleet.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.db import connections

import dagster
import pydantic

from posthog.clickhouse.query_tagging import get_query_tags
from posthog.dags.common import JobOwners, dagster_tags, skip_if_already_running
from posthog.exceptions_capture import capture_exception

from products.growth.backend.models import ProductPushCampaign
from products.growth.backend.product_push.service import (
    CloseBatchResult,
    StartBatchResult,
    evaluate_and_close_campaign_batch,
    get_eligible_organization_queryset,
    start_campaigns_for_org_batch,
)

SWEEP_BATCH_SIZE = 500

_BATCH_OP_RETRY_POLICY = dagster.RetryPolicy(
    max_retries=3,
    delay=30,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.FULL,
)


@dataclass(kw_only=True)
class StartBatchSpec:
    organization_ids: list[str]
    dry_run: bool


class StartSweepConfig(dagster.Config):
    """Config for the start phase of the product push campaign job."""

    organization_ids: list[str] = pydantic.Field(
        default=[],
        description="Only consider these organization ids (UUIDs). Empty = all eligible organizations.",
    )
    batch_size: int = pydantic.Field(default=SWEEP_BATCH_SIZE, gt=0)
    rollout_percentage: float = pydantic.Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Deterministic per-org rollout fraction (sha256 over the org id, monotonic across runs).",
    )
    max_starts: int | None = pydantic.Field(
        default=None,
        description="Cap on how many organizations may start a campaign this run (herd control for early runs).",
        gt=0,
    )
    dry_run: bool = pydantic.Field(
        default=False,
        description="Log what would start without writing campaigns or emitting events.",
    )


def _org_in_rollout(organization_id: str, rollout_percentage: float) -> bool:
    if rollout_percentage >= 1.0:
        return True
    bucket = int(hashlib.sha256(organization_id.encode()).hexdigest(), 16) % 100_000
    return bucket < rollout_percentage * 100_000


@dagster.op(out=dagster.DynamicOut(list[str]))
def get_active_campaign_batches_op(context: dagster.OpExecutionContext):
    """Fan out every ACTIVE campaign id as batches for the close phase.

    Always yields at least one (possibly empty) batch so the downstream collect —
    and with it the whole start phase — runs even on days with zero active
    campaigns (e.g. the very first run).
    """
    campaign_ids = [
        str(campaign_id)
        for campaign_id in ProductPushCampaign.objects.filter(status=ProductPushCampaign.Status.ACTIVE).values_list(
            "id", flat=True
        )
    ]
    context.log.info(f"Found {len(campaign_ids)} active campaigns to evaluate")

    if not campaign_ids:
        yield dagster.DynamicOutput([], mapping_key="batch_0")
        return
    for index in range(0, len(campaign_ids), SWEEP_BATCH_SIZE):
        yield dagster.DynamicOutput(
            campaign_ids[index : index + SWEEP_BATCH_SIZE], mapping_key=f"batch_{index // SWEEP_BATCH_SIZE}"
        )


@dagster.op(retry_policy=_BATCH_OP_RETRY_POLICY)
def evaluate_campaign_batch_op(context: dagster.OpExecutionContext, campaign_ids: list[str]) -> CloseBatchResult:
    """Adopt / skip the campaigns in this batch. Retry-safe: transitions run under
    SKIP LOCKED with a status filter, so a retried batch is a no-op for rows the
    first attempt already closed."""
    get_query_tags().with_dagster(dagster_tags(context))
    try:
        result = evaluate_and_close_campaign_batch(campaign_ids, now=datetime.now(tz=UTC))
        context.log.info(
            f"Batch of {len(campaign_ids)}: {result.evaluated} evaluated, "
            f"{result.adopted} adopted, {result.skipped} skipped"
        )
        return result
    except Exception as e:
        context.log.exception(f"Failed to evaluate batch of {len(campaign_ids)} campaigns")
        capture_exception(e, {"team": "team-growth", "campaign_count": len(campaign_ids)})
        raise
    finally:
        if not settings.TEST:
            connections.close_all()


@dagster.op(out=dagster.DynamicOut(StartBatchSpec))
def get_eligible_org_batches_op(
    context: dagster.OpExecutionContext,
    config: StartSweepConfig,
    close_results: list[CloseBatchResult],
):
    """Fan out eligible organization ids as batches for the start phase.

    Takes the collected close results as input purely for sequencing: starts must
    observe the campaigns this run just closed.
    """
    context.log.info(
        f"Close phase done ({sum(r.evaluated for r in close_results)} campaigns evaluated); computing eligible orgs"
    )

    queryset = get_eligible_organization_queryset(datetime.now(tz=UTC)).order_by("created_at")
    if config.organization_ids:
        queryset = queryset.filter(id__in=config.organization_ids)

    organization_ids = [str(organization_id) for organization_id in queryset.values_list("id", flat=True)]
    total_eligible = len(organization_ids)

    if config.rollout_percentage < 1.0:
        organization_ids = [
            organization_id
            for organization_id in organization_ids
            if _org_in_rollout(organization_id, config.rollout_percentage)
        ]
    if config.max_starts is not None:
        organization_ids = organization_ids[: config.max_starts]

    context.log.info(
        f"{total_eligible} orgs eligible, {len(organization_ids)} selected "
        f"(rollout={config.rollout_percentage}, max_starts={config.max_starts}, dry_run={config.dry_run})"
    )

    if not organization_ids:
        yield dagster.DynamicOutput(StartBatchSpec(organization_ids=[], dry_run=config.dry_run), mapping_key="batch_0")
        return
    for index in range(0, len(organization_ids), config.batch_size):
        yield dagster.DynamicOutput(
            StartBatchSpec(
                organization_ids=organization_ids[index : index + config.batch_size], dry_run=config.dry_run
            ),
            mapping_key=f"batch_{index // config.batch_size}",
        )


@dagster.op(retry_policy=_BATCH_OP_RETRY_POLICY)
def start_campaign_batch_op(context: dagster.OpExecutionContext, spec: StartBatchSpec) -> StartBatchResult:
    """Start campaigns for the orgs in this batch. Retry-safe: eligibility is
    re-checked per org and the one-active-per-org partial unique constraint turns
    a concurrent double-start into a counted conflict."""
    get_query_tags().with_dagster(dagster_tags(context))
    try:
        result = start_campaigns_for_org_batch(spec.organization_ids, now=datetime.now(tz=UTC), dry_run=spec.dry_run)
        context.log.info(
            f"Batch of {result.orgs_processed} orgs: {result.started} started, {result.would_start} would start, "
            f"{result.no_candidate} without candidate, {result.not_eligible} not eligible, "
            f"{result.conflicts} conflicts"
        )
        return result
    except Exception as e:
        context.log.exception(f"Failed to start campaigns for batch of {len(spec.organization_ids)} orgs")
        capture_exception(e, {"team": "team-growth", "org_count": len(spec.organization_ids)})
        raise
    finally:
        if not settings.TEST:
            connections.close_all()


@dagster.op
def summarize_product_push_run_op(
    context: dagster.OpExecutionContext,
    close_results: list[CloseBatchResult],
    start_results: list[StartBatchResult],
) -> None:
    """Roll up per-batch counts into a single run-level summary."""
    adopted = sum(r.adopted for r in close_results)
    skipped = sum(r.skipped for r in close_results)
    started = sum(r.started for r in start_results)
    would_start = sum(r.would_start for r in start_results)

    context.log.info(
        f"Run complete: {adopted} adopted, {skipped} skipped, {started} started, {would_start} would start"
    )
    context.add_output_metadata(
        {
            "campaigns_evaluated": dagster.MetadataValue.int(sum(r.evaluated for r in close_results)),
            "campaigns_adopted": dagster.MetadataValue.int(adopted),
            "campaigns_skipped": dagster.MetadataValue.int(skipped),
            "orgs_processed": dagster.MetadataValue.int(sum(r.orgs_processed for r in start_results)),
            "campaigns_started": dagster.MetadataValue.int(started),
            "campaigns_would_start": dagster.MetadataValue.int(would_start),
            "starts_not_eligible": dagster.MetadataValue.int(sum(r.not_eligible for r in start_results)),
            "starts_no_candidate": dagster.MetadataValue.int(sum(r.no_candidate for r in start_results)),
            "start_conflicts": dagster.MetadataValue.int(sum(r.conflicts for r in start_results)),
        }
    )


@dagster.job(
    description=(
        "Daily job driving organization product push campaigns: closes active campaigns "
        "(adopted / skipped) and starts the next campaign for eligible organizations."
    ),
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 5}),
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def product_push_campaigns_job():
    close_results = get_active_campaign_batches_op().map(evaluate_campaign_batch_op).collect()
    start_results = get_eligible_org_batches_op(close_results).map(start_campaign_batch_op).collect()
    summarize_product_push_run_op(close_results, start_results)


@dagster.schedule(
    job=product_push_campaigns_job,
    cron_schedule="0 6 * * *",
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.STOPPED,
)
@skip_if_already_running
def product_push_campaigns_schedule(context: dagster.ScheduleEvaluationContext):
    # Never stack runs: overlapping sweeps are transition-safe (SKIP LOCKED +
    # unique constraint) but would double-scan every org and double-check
    # adoption for nothing.
    return dagster.RunRequest()
