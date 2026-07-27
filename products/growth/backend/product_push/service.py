"""State transitions and adoption detection for product push campaigns.

Adoption is ProductIntent-based for v1. Extension path: plug ClickHouse usage
counters (posthog/tasks/usage_report.py `get_teams_with_*_count_in_period`
helpers) as a second source inside `org_adopted_product` — its contract stays
fixed. We deliberately never create intents ourselves; that would corrupt the
intent metric.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q, QuerySet

import structlog

from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.models.product_intent.product_intent import ACTIVATION_CHECK_PRODUCT_KEYS, ProductIntent
from posthog.ph_client import ph_scoped_capture

from products.growth.backend.models import ProductPushCampaign
from products.growth.backend.product_push.cadence import (
    COOLDOWN_DAYS,
    GRACE_PERIOD_DAYS,
    campaign_ends_at,
    is_cooldown_over,
    is_grace_period_over,
)
from products.growth.backend.product_push.selection import Selection, select_next_product

logger = structlog.get_logger(__name__)

# Re-check a not-yet-activated intent's criterion at most this often. Matches the
# cadence of `calculate_product_activation`'s debounce.
ACTIVATION_RECHECK_STALENESS = timedelta(days=1)


@dataclass(frozen=True)
class AdoptionResult:
    signal: str  # "intent_activated" | "intent_created"
    team_id: int


@dataclass(kw_only=True)
class CloseBatchResult:
    evaluated: int = 0
    adopted: int = 0
    skipped: int = 0


@dataclass(kw_only=True)
class StartBatchResult:
    orgs_processed: int = 0
    started: int = 0
    no_candidate: int = 0
    not_eligible: int = 0
    conflicts: int = 0
    would_start: int = 0  # dry-run only


def org_adopted_product(organization_id: str, product_key: str, since: datetime) -> AdoptionResult | None:
    """Did any team in the org start using the product after `since`?"""
    intents = ProductIntent.objects.filter(team__organization_id=organization_id, product_type=product_key)

    if product_key not in ACTIVATION_CHECK_PRODUCT_KEYS:
        # No activation criterion exists — the strongest signal we have is that
        # someone showed intent during the campaign.
        created = intents.filter(created_at__gte=since).order_by("created_at").first()
        if created is not None:
            return AdoptionResult(signal="intent_created", team_id=created.team_id)
        return None

    # Proactively re-check stale intents: the Celery re-check path only fires when
    # someone re-registers intent, so without this a team that quietly meets the
    # criterion mid-campaign would never flip activated_at.
    stale_cutoff = datetime.now(UTC) - ACTIVATION_RECHECK_STALENESS
    stale_intents = intents.filter(activated_at__isnull=True).filter(
        Q(activation_last_checked_at__isnull=True) | Q(activation_last_checked_at__lt=stale_cutoff)
    )
    for intent in stale_intents:
        try:
            intent.check_and_update_activation()
        except Exception as e:
            capture_exception(e, {"team": "team-growth", "organization_id": organization_id})
            logger.exception("product_push_activation_recheck_failed", intent_id=intent.id)

    activated = intents.filter(activated_at__gte=since).order_by("activated_at").first()
    if activated is not None:
        return AdoptionResult(signal="intent_activated", team_id=activated.team_id)
    return None


def get_eligible_organization_queryset(now: datetime) -> QuerySet[Organization]:
    """Organizations that may start a campaign right now.

    Past the signup grace period, no active campaign, out of the between-campaigns
    cooldown — or holding a due dated TAM pin, which overrides grace and cooldown.
    """
    grace_cutoff = now - timedelta(days=GRACE_PERIOD_DAYS)
    cooldown_cutoff = now - timedelta(days=COOLDOWN_DAYS)

    active = ProductPushCampaign.objects.filter(
        organization_id=OuterRef("id"), status=ProductPushCampaign.Status.ACTIVE
    )
    recently_ended = ProductPushCampaign.objects.filter(organization_id=OuterRef("id"), ended_at__gt=cooldown_cutoff)
    due_pin = ProductPushCampaign.objects.filter(
        organization_id=OuterRef("id"),
        status=ProductPushCampaign.Status.SCHEDULED,
        scheduled_for__isnull=False,
        scheduled_for__lte=now.date(),
    )

    return (
        Organization.objects.exclude(for_internal_metrics=True)
        .annotate(has_active=Exists(active), has_recent_end=Exists(recently_ended), has_due_pin=Exists(due_pin))
        .filter(has_active=False)
        .filter(Q(created_at__lte=grace_cutoff, has_recent_end=False) | Q(has_due_pin=True))
    )


def evaluate_and_close_campaign_batch(campaign_ids: list[str], now: datetime) -> CloseBatchResult:
    """Close active campaigns: adopted when the org started using the product,
    skipped when the window expired without adoption.

    Concurrent-safe: the status flip runs under SELECT FOR UPDATE SKIP LOCKED, so a
    parallel run closes each campaign (and emits its event) at most once.
    """
    result = CloseBatchResult()
    closed: list[tuple[ProductPushCampaign, str]] = []

    campaigns = ProductPushCampaign.objects.filter(
        id__in=campaign_ids, status=ProductPushCampaign.Status.ACTIVE
    ).select_related("organization")

    for campaign in campaigns:
        if campaign.started_at is None:
            continue
        result.evaluated += 1

        # The adoption check reads (and may re-check/save) intents — keep it outside
        # the row lock below.
        adoption = org_adopted_product(str(campaign.organization_id), campaign.product_key, since=campaign.started_at)

        if adoption is not None:
            new_status = ProductPushCampaign.Status.ADOPTED
        elif campaign.ends_at is not None and now >= campaign.ends_at:
            new_status = ProductPushCampaign.Status.SKIPPED
        else:
            continue

        with transaction.atomic():
            locked = (
                ProductPushCampaign.objects.select_for_update(skip_locked=True)
                .filter(id=campaign.id, status=ProductPushCampaign.Status.ACTIVE)
                .first()
            )
            if locked is None:
                continue
            locked.status = new_status
            locked.ended_at = now
            if adoption is not None:
                locked.metadata = {
                    **(locked.metadata or {}),
                    "adoption_signal": adoption.signal,
                    "adoption_team_id": adoption.team_id,
                }
            locked.save(update_fields=["status", "ended_at", "metadata", "updated_at"])

        campaign.refresh_from_db(fields=["status", "ended_at", "metadata"])
        if new_status == ProductPushCampaign.Status.ADOPTED:
            result.adopted += 1
            closed.append((campaign, "adopted"))
        else:
            result.skipped += 1
            closed.append((campaign, "skipped"))
        logger.info(
            "product_push_campaign_closed",
            campaign_id=str(campaign.id),
            organization_id=str(campaign.organization_id),
            product_key=campaign.product_key,
            status=new_status,
        )

    _capture_campaign_events(closed)
    return result


def start_campaigns_for_org_batch(
    organization_ids: list[str], now: datetime, dry_run: bool = False
) -> StartBatchResult:
    """Start the next campaign for each eligible org in the batch.

    Eligibility is re-checked per org (the caller's eligible-set may be stale), and
    the one-active-per-org partial unique constraint makes concurrent starts
    idempotent. A due dated TAM pin bypasses grace and cooldown.
    """
    result = StartBatchResult()
    started: list[tuple[ProductPushCampaign, str]] = []

    organizations = Organization.objects.filter(id__in=organization_ids).only("id", "created_at", "customer_id")

    for organization in organizations:
        result.orgs_processed += 1

        selection = select_next_product(organization, now)
        if selection is None:
            result.no_candidate += 1
            continue

        if not _is_eligible_for_selection(organization, selection, now):
            result.not_eligible += 1
            continue

        if dry_run:
            result.would_start += 1
            logger.info(
                "product_push_campaign_would_start",
                organization_id=str(organization.id),
                product_key=selection.product_key,
                promotes_scheduled_row=selection.scheduled_campaign is not None,
            )
            continue

        campaign = _start_campaign(organization, selection, now)
        if campaign is None:
            result.conflicts += 1
            continue

        result.started += 1
        started.append((campaign, "started"))
        logger.info(
            "product_push_campaign_started",
            campaign_id=str(campaign.id),
            organization_id=str(organization.id),
            product_key=campaign.product_key,
            source=campaign.source,
        )

    _capture_campaign_events(started)
    return result


def cancel_campaigns(campaign_ids: list[str], now: datetime) -> int:
    """Cancel SCHEDULED or ACTIVE campaigns (admin action). Returns the count cancelled."""
    cancelled: list[tuple[ProductPushCampaign, str]] = []
    with transaction.atomic():
        campaigns = list(
            ProductPushCampaign.objects.select_for_update(skip_locked=True)
            .filter(
                id__in=campaign_ids,
                status__in=[ProductPushCampaign.Status.SCHEDULED, ProductPushCampaign.Status.ACTIVE],
            )
            .select_related("organization")
        )
        for campaign in campaigns:
            campaign.status = ProductPushCampaign.Status.CANCELLED
            campaign.ended_at = now
            campaign.save(update_fields=["status", "ended_at", "updated_at"])
            cancelled.append((campaign, "cancelled"))

    _capture_campaign_events(cancelled)
    return len(cancelled)


def _is_eligible_for_selection(organization: Organization, selection: Selection, now: datetime) -> bool:
    # One active campaign per org — nothing overrides this, not even a dated pin.
    if ProductPushCampaign.objects.filter(organization=organization, status=ProductPushCampaign.Status.ACTIVE).exists():
        return False

    # A due dated pin is an explicit TAM decision — it bypasses grace and cooldown.
    is_dated_pin = selection.scheduled_campaign is not None and selection.scheduled_campaign.scheduled_for is not None
    if is_dated_pin:
        return True

    if not is_grace_period_over(organization.created_at, now):
        return False

    last_ended_at = (
        ProductPushCampaign.objects.filter(organization=organization, ended_at__isnull=False)
        .order_by("-ended_at")
        .values_list("ended_at", flat=True)
        .first()
    )
    return is_cooldown_over(last_ended_at, now)


def _start_campaign(organization: Organization, selection: Selection, now: datetime) -> ProductPushCampaign | None:
    ends_at = campaign_ends_at(now)
    try:
        with transaction.atomic():
            if selection.scheduled_campaign is not None:
                campaign = (
                    ProductPushCampaign.objects.select_for_update(skip_locked=True)
                    .filter(id=selection.scheduled_campaign.id, status=ProductPushCampaign.Status.SCHEDULED)
                    .first()
                )
                if campaign is None:
                    return None
                campaign.status = ProductPushCampaign.Status.ACTIVE
                campaign.started_at = now
                campaign.ends_at = ends_at
                campaign.save(update_fields=["status", "started_at", "ends_at", "updated_at"])
                return campaign
            return ProductPushCampaign.objects.create(
                organization=organization,
                product_key=selection.product_key,
                status=ProductPushCampaign.Status.ACTIVE,
                started_at=now,
                ends_at=ends_at,
                source=ProductPushCampaign.Source.AUTO,
            )
    except IntegrityError:
        # Another worker started a campaign for this org concurrently — the partial
        # unique constraint makes this a no-op rather than a duplicate push.
        return None


def _capture_campaign_events(campaign_events: list[tuple[ProductPushCampaign, str]]) -> None:
    """Emit one analytics event per transition, after the transactions committed.

    At-most-once: rows are already transitioned, so a crash before flush loses those
    events; the table is the source of truth. Per-row guard keeps one bad org from
    forfeiting the rest of the batch.
    """
    if not campaign_events:
        return

    with ph_scoped_capture() as capture:
        for campaign, transition in campaign_events:
            try:
                properties = {
                    "campaign_id": str(campaign.id),
                    "product_key": campaign.product_key,
                    "source": campaign.source,
                    "adoption_signal": (campaign.metadata or {}).get("adoption_signal"),
                    "days_active": (
                        (campaign.ended_at - campaign.started_at).days
                        if campaign.ended_at and campaign.started_at
                        else None
                    ),
                }
                capture(
                    distinct_id=str(campaign.organization_id),
                    event=f"product push campaign {transition}",
                    properties={key: value for key, value in properties.items() if value is not None},
                    groups=groups(organization=campaign.organization),
                )
            except Exception as e:
                capture_exception(e, {"team": "team-growth", "campaign_id": str(campaign.id)})
                logger.exception("product_push_campaign_capture_failed", campaign_id=str(campaign.id))
