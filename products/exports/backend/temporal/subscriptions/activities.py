import json
import math
import time
import uuid
import typing
import asyncio
import datetime as dt
import dataclasses
from collections import defaultdict
from datetime import datetime

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.models import Case, Q, Value, When
from django.utils import timezone as tz

import temporalio.activity
from structlog import get_logger
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode

from posthog.dataclasses import frozen
from posthog.models.temporal_scheduler import TemporalSchedulerClaim, TemporalSchedulerState
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.scheduler.admission import (
    SCHEDULER_LOCK_TIMEOUT_MS,
    SchedulerAdmissionLimits,
    SchedulerClaimInvariantError,
    SchedulerClaimRequest,
    complete_scheduler_claim,
    confirm_scheduler_claim,
    defer_scheduler_claim_recovery,
    list_expired_scheduler_claims,
    prune_inactive_scheduler_claims,
    release_scheduler_claim,
    renew_scheduler_claim,
    reserve_scheduler_claims,
)
from posthog.temporal.scheduler.metrics import DEFAULT_SCHEDULER_METRICS, record_scheduler_metrics_safely
from posthog.temporal.scheduler.payload import select_items_within_temporal_payload

from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import _deliver_ai_subscription
from products.exports.backend.temporal.subscriptions.delivery_common import (
    auto_disable_and_return,
    deliver_email,
    deliver_slack,
)
from products.exports.backend.temporal.subscriptions.delivery_webhook import deliver_teams_webhook
from products.exports.backend.temporal.subscriptions.insight_snapshot import (
    build_initial_content_snapshot,
    build_insight_delivery_snapshot,
)
from products.exports.backend.temporal.subscriptions.types import (
    AI_PROMPT_RESOURCE_TYPE,
    DEFAULT_MAX_DUE_SUBSCRIPTIONS_PER_SCHEDULE_RUN,
    MAX_DUE_SUBSCRIPTIONS_PER_SCHEDULE_RUN,
    SUBSCRIPTION_CLAIM_LEASE_SAFETY_MARGIN,
    SUBSCRIPTION_WORKFLOW_EXECUTION_TIMEOUT,
    AdvanceNextDeliveryDateInputs,
    AdvanceSubscriptionSchedulerCursorInputs,
    CreateDeliveryRecordInputs,
    CreateExportAssetsInputs,
    CreateExportAssetsResult,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    DeliveryAbort,
    DueSubscription,
    ExportAssetPreparationStatus,
    FetchDueSubscriptionsActivityInputs,
    FetchDueSubscriptionsActivityOutput,
    NoExportableInsightsContext,
    NoExportableInsightsReason,
    RecipientResult,
    RecoverSubscriptionSchedulerClaimsInputs,
    SubscriptionSchedulerClaimInputs,
    UpdateDeliveryRecordInputs,
)
from products.product_analytics.backend.facade.models import Insight

from ee.tasks.subscriptions import _capture_delivery_failed_event
from ee.tasks.subscriptions.auto_disable import (
    UNSUPPORTED_TARGET_DISABLE_REASON,
    disable_invalid_subscription,
    get_subscription_disable_reason,
)
from ee.tasks.subscriptions.email_subscriptions import send_email_subscription_report
from ee.tasks.subscriptions.failure_notifications import (
    create_subscription_delivery_failure_notification,
    send_subscription_delivery_failure_email,
)
from ee.tasks.subscriptions.slack_subscriptions import send_slack_message_with_integration_async
from ee.tasks.subscriptions.subscription_utils import MAX_INSIGHTS
from ee.tasks.subscriptions.teams_subscriptions import build_teams_subscription_card

LOGGER = get_logger(__name__)

_SUBSCRIPTION_SCHEDULER_NAME = "subscriptions"
_SUBSCRIPTION_RESERVATION_LEASE = dt.timedelta(minutes=25)
_SUBSCRIPTION_EXECUTION_LEASE = SUBSCRIPTION_WORKFLOW_EXECUTION_TIMEOUT + SUBSCRIPTION_CLAIM_LEASE_SAFETY_MARGIN
_SUBSCRIPTION_UNCERTAIN_RECOVERY_BACKOFF = dt.timedelta(minutes=5)
_SUBSCRIPTION_MAX_IN_FLIGHT = MAX_DUE_SUBSCRIPTIONS_PER_SCHEDULE_RUN
_SUBSCRIPTION_MAX_IN_FLIGHT_PER_TENANT = DEFAULT_MAX_DUE_SUBSCRIPTIONS_PER_SCHEDULE_RUN
_SUBSCRIPTION_RECOVERY_CONCURRENCY = 20
SUBSCRIPTION_RECOVERY_ACTIVITY_TIMEOUT = dt.timedelta(minutes=2)
# Finish status checks and synchronous reconciliation before Temporal's activity
# timeout: timing out does not interrupt an executor thread that is holding DB locks.
_SUBSCRIPTION_RECOVERY_ACTIVITY_BUDGET = SUBSCRIPTION_RECOVERY_ACTIVITY_TIMEOUT - dt.timedelta(seconds=20)
_SUBSCRIPTION_RECOVERY_STATUS_BUDGET = _SUBSCRIPTION_RECOVERY_ACTIVITY_BUDGET - dt.timedelta(seconds=20)
# One stalled Temporal frontend response must not consume the status-check budget.
_SUBSCRIPTION_RECOVERY_RPC_TIMEOUT = dt.timedelta(seconds=5)
_SUBSCRIPTION_CANDIDATE_LIMIT = _SUBSCRIPTION_MAX_IN_FLIGHT + MAX_DUE_SUBSCRIPTIONS_PER_SCHEDULE_RUN + 1
_monotonic = time.monotonic

# Used only as the recipient_results error message — `no_assets` doesn't auto-disable
# (it indicates a transient resolve failure that retries can recover from).
NO_ASSETS_REASON = "No assets to deliver — likely a transient export pipeline failure; will retry on next schedule"
# Plain-English twin of NO_ASSETS_REASON for the delivery-history UI: "assets" and "export pipeline"
# are internal jargon subscribers won't parse.
NO_ASSETS_HUMAN_READABLE_REASON = (
    "Nothing could be generated to send this time. We'll try again on the next scheduled run."
)


class NoExportableInsightsError(Exception):
    pass


@dataclasses.dataclass
class ResolvedExportableInsights:
    tile_insight_pairs: list[tuple[DashboardTile | None, Insight]]
    available_insight_count: int
    selected_insight_count: int
    no_exportable_reason: str | None


@dataclasses.dataclass(frozen=True)
class _DueSubscriptionsPage:
    subscriptions: list[DueSubscription]
    due_items_lower_bound: int
    oldest_due_at: dt.datetime | None
    discovery_cursor: str
    selected_team_ids: tuple[int, ...]


@frozen
class _ClaimReservations:
    reservations: dict[str, tuple[str, str]]


@frozen
class _ExpiredSchedulerClaimsSnapshot:
    claims: list[tuple[uuid.UUID, uuid.UUID, str, str, dt.datetime]]
    pruned: int


@frozen
class _WorkflowClaimStatus:
    is_open: bool | None
    error: str = ""


@frozen
class _ClaimRecoveryCounts:
    released: int = 0
    renewed: int = 0
    retained: int = 0


@frozen
class _AdvanceNextDeliveryDateResult:
    advanced: bool
    next_delivery_date: dt.datetime | None
    outcome: str


def _defer_subscription_claim_after_recovery_error(
    claim_id: uuid.UUID,
    claim_token: uuid.UUID,
    lease_expires_at: dt.datetime,
    error: BaseException,
) -> None:
    try:
        defer_scheduler_claim_recovery(
            claim_id,
            claim_token,
            lease_duration=_SUBSCRIPTION_UNCERTAIN_RECOVERY_BACKOFF,
            error=f"{type(error).__name__}: {error}",
            expected_lease_expires_at=lease_expires_at,
        )
    except DatabaseError:
        if not connection.is_usable():
            raise
        LOGGER.exception("subscription_scheduler.claim_recovery_deferral_failed", claim_id=str(claim_id))


def _reconcile_expired_subscription_claim(
    claim_id: uuid.UUID,
    claim_token: uuid.UUID,
    claim_status: str,
    lease_expires_at: dt.datetime,
    status: _WorkflowClaimStatus,
) -> _ClaimRecoveryCounts:
    try:
        if status.is_open is True:
            transition = (
                renew_scheduler_claim
                if claim_status == TemporalSchedulerClaim.Status.CONFIRMED
                else confirm_scheduler_claim
            )
            return _ClaimRecoveryCounts(
                renewed=int(
                    transition(
                        claim_id,
                        claim_token,
                        lease_duration=_SUBSCRIPTION_UNCERTAIN_RECOVERY_BACKOFF,
                    )
                ),
            )
        if status.is_open is False:
            return _ClaimRecoveryCounts(
                released=int(
                    release_scheduler_claim(
                        claim_id,
                        claim_token,
                        error="expired claim has no open Temporal workflow",
                        expected_lease_expires_at=lease_expires_at,
                    )
                ),
            )
        defer_scheduler_claim_recovery(
            claim_id,
            claim_token,
            lease_duration=_SUBSCRIPTION_UNCERTAIN_RECOVERY_BACKOFF,
            error=status.error or "Temporal workflow status could not be determined",
            expected_lease_expires_at=lease_expires_at,
        )
    except (DatabaseError, SchedulerClaimInvariantError) as error:
        if isinstance(error, DatabaseError) and not connection.is_usable():
            raise
        LOGGER.warning(
            "subscription_scheduler.claim_recovery_transition_failed",
            claim_id=str(claim_id),
            error_type=type(error).__name__,
            error=str(error),
        )
        _defer_subscription_claim_after_recovery_error(claim_id, claim_token, lease_expires_at, error)
    return _ClaimRecoveryCounts(retained=1)


def _reconcile_expired_subscription_claims(
    expired_claims: list[tuple[uuid.UUID, uuid.UUID, str, str, dt.datetime]],
    statuses: typing.Sequence[_WorkflowClaimStatus | None],
    *,
    pruned: int,
    recovery_deadline: float,
) -> tuple[dict[str, int], int]:
    released = 0
    renewed = 0
    retained = 0
    processed = 0
    transition_headroom = 2 * SCHEDULER_LOCK_TIMEOUT_MS / 1000
    for (claim_id, claim_token, _, claim_status, lease_expires_at), status in zip(
        expired_claims, statuses, strict=True
    ):
        if status is None or _monotonic() + transition_headroom >= recovery_deadline:
            LOGGER.warning(
                "subscription_scheduler.claim_recovery_budget_exhausted",
                reconciled=processed,
                remaining=len(expired_claims) - processed,
            )
            break
        counts = _reconcile_expired_subscription_claim(
            claim_id,
            claim_token,
            claim_status,
            lease_expires_at,
            status,
        )
        released += counts.released
        renewed += counts.renewed
        retained += counts.retained
        processed += 1
    return {
        "released": released,
        "renewed": renewed,
        "retained": retained,
        "pruned": pruned,
    }, len(expired_claims) - processed


def _resolve_scheduler_region(region: str) -> str:
    configured_region = (settings.CLOUD_DEPLOYMENT or "").lower()
    resolved_region = region or configured_region or "local"
    if not resolved_region.strip() or len(resolved_region) > 32:
        raise ValueError("region must contain between 1 and 32 characters")
    if configured_region and resolved_region != configured_region:
        raise ValueError(
            f"region {resolved_region!r} does not match configured deployment region {configured_region!r}"
        )
    return resolved_region


def _subscription_child_workflow_id(subscription: DueSubscription) -> str:
    prefix = (
        "process-ai-subscription" if subscription.resource_type == AI_PROMPT_RESOURCE_TYPE else "process-subscription"
    )
    return f"{prefix}-{subscription.subscription_id}"


def _subscription_occurrence_key(subscription: DueSubscription) -> str:
    if subscription.next_delivery_date is None:
        raise ValueError(f"Due subscription {subscription.subscription_id} is missing next_delivery_date")
    return f"subscription:{subscription.subscription_id}:{subscription.next_delivery_date}"


def _subscription_source_due_at(subscription: DueSubscription) -> datetime:
    if subscription.next_delivery_date is None:
        raise ValueError(f"Due subscription {subscription.subscription_id} is missing next_delivery_date")
    return datetime.fromisoformat(subscription.next_delivery_date)


def _select_due_subscription_candidate_ids(
    selected_team_ids: list[int], now_with_buffer: dt.datetime, candidate_limit: int
) -> list[int]:
    candidates_by_team: dict[int, list[tuple[int, dt.datetime]]] = defaultdict(list)
    team_order = {team_id: index for index, team_id in enumerate(selected_team_ids)}
    teams_to_fetch = list(selected_team_ids)

    with connection.cursor() as cursor:
        while teams_to_fetch and sum(len(rows) for rows in candidates_by_team.values()) < candidate_limit:
            remaining = candidate_limit - sum(len(rows) for rows in candidates_by_team.values())
            candidates_per_team = math.ceil(remaining / len(teams_to_fetch))
            offsets = [len(candidates_by_team[team_id]) for team_id in teams_to_fetch]
            orders = [team_order[team_id] for team_id in teams_to_fetch]
            cursor.execute(
                """
                WITH selected_teams(team_id, candidate_offset, team_order) AS (
                    SELECT * FROM unnest(%s::bigint[], %s::bigint[], %s::bigint[])
                )
                SELECT
                    selected_teams.team_id,
                    candidate.id,
                    candidate.next_delivery_date
                FROM selected_teams
                CROSS JOIN LATERAL (
                    SELECT subscription.id, subscription.next_delivery_date
                    FROM posthog_subscription AS subscription
                    LEFT JOIN posthog_dashboard AS dashboard ON dashboard.id = subscription.dashboard_id
                    -- Insight kept the legacy dashboarditem relation name through the model rename.
                    LEFT JOIN posthog_dashboarditem AS insight ON insight.id = subscription.insight_id
                    WHERE subscription.team_id = selected_teams.team_id
                      AND subscription.next_delivery_date <= %s
                      AND subscription.deleted = FALSE
                      AND subscription.enabled = TRUE
                      AND (subscription.dashboard_id IS NULL OR dashboard.deleted = FALSE)
                      AND (subscription.insight_id IS NULL OR insight.deleted = FALSE)
                      AND (
                          subscription.insight_id IS NOT NULL
                          OR subscription.dashboard_id IS NOT NULL
                          OR NULLIF(subscription.prompt, '') IS NOT NULL
                      )
                    ORDER BY subscription.next_delivery_date, subscription.id
                    OFFSET selected_teams.candidate_offset
                    LIMIT %s
                ) AS candidate
                ORDER BY selected_teams.team_order, candidate.next_delivery_date, candidate.id
                """,
                [teams_to_fetch, offsets, orders, now_with_buffer, candidates_per_team],
            )
            fetched_counts: dict[int, int] = defaultdict(int)
            for team_id, subscription_id, next_delivery_date in cursor.fetchall():
                candidates_by_team[team_id].append((subscription_id, next_delivery_date))
                fetched_counts[team_id] += 1
            teams_to_fetch = [team_id for team_id in teams_to_fetch if fetched_counts[team_id] == candidates_per_team]

    candidates: list[tuple[int, int, dt.datetime, int]] = []
    for team_id, rows in candidates_by_team.items():
        candidates.extend(
            (team_rank, team_order[team_id], next_delivery_date, subscription_id)
            for team_rank, (subscription_id, next_delivery_date) in enumerate(rows, start=1)
        )
    candidates.sort()
    return list(dict.fromkeys(subscription_id for _, _, _, subscription_id in candidates))[:candidate_limit]


async def _resolve_exportable_insights(subscription: Subscription) -> ResolvedExportableInsights:
    dashboard = subscription.dashboard
    if dashboard:
        if dashboard.deleted:
            return ResolvedExportableInsights(
                tile_insight_pairs=[],
                available_insight_count=0,
                selected_insight_count=0,
                no_exportable_reason=NoExportableInsightsReason.DASHBOARD_DELETED,
            )

        tiles = await database_sync_to_async(
            lambda: list(
                dashboard.tiles.select_related("insight").filter(insight__isnull=False, insight__deleted=False).all()
            ),
            thread_sensitive=False,
        )()
        tiles.sort(
            key=lambda x: (
                (x.layouts or {}).get("sm", {}).get("y", 100),
                (x.layouts or {}).get("sm", {}).get("x", 100),
            )
        )
        tile_insight_pairs: list[tuple[DashboardTile | None, Insight]] = [
            (tile, tile.insight) for tile in tiles if tile.insight
        ]
        available_insight_count = len(tile_insight_pairs)
        selected_ids = await database_sync_to_async(
            lambda: (
                set(subscription.dashboard_export_insights.values_list("id", flat=True))
                if subscription.dashboard_export_insights.exists()
                else None
            ),
            thread_sensitive=False,
        )()
        if selected_ids:
            selected_pairs: list[tuple[DashboardTile | None, Insight]] = [
                (tile, insight) for tile, insight in tile_insight_pairs if insight.id in selected_ids
            ]
            return ResolvedExportableInsights(
                tile_insight_pairs=selected_pairs,
                available_insight_count=available_insight_count,
                selected_insight_count=len(selected_ids),
                no_exportable_reason=(
                    None if selected_pairs else NoExportableInsightsReason.SELECTED_INSIGHTS_NO_LONGER_AVAILABLE
                ),
            )

        return ResolvedExportableInsights(
            tile_insight_pairs=tile_insight_pairs,
            available_insight_count=available_insight_count,
            selected_insight_count=0,
            no_exportable_reason=None if tile_insight_pairs else NoExportableInsightsReason.EMPTY_DASHBOARD,
        )

    if subscription.insight and not subscription.insight.deleted:
        return ResolvedExportableInsights(
            tile_insight_pairs=[(None, subscription.insight)],
            available_insight_count=1,
            selected_insight_count=0,
            no_exportable_reason=None,
        )

    return ResolvedExportableInsights(
        tile_insight_pairs=[],
        available_insight_count=0,
        selected_insight_count=0,
        no_exportable_reason=NoExportableInsightsReason.MISSING_RESOURCE,
    )


async def _persist_content_snapshot(
    *,
    delivery_id: uuid.UUID,
    total_insight_count: int,
    insight_snapshots: list[dict[str, typing.Any]],
) -> int:
    """Merge insight snapshots onto SubscriptionDelivery.content_snapshot.

    Returns the serialized size of the insight_snapshots payload so callers can
    log it — the whole point of owning this write is staying under size cliffs,
    so measuring proximity to the next one is worth the cycles.
    """
    snapshot_bytes = len(json.dumps(insight_snapshots, default=str).encode("utf-8"))

    @database_sync_to_async(thread_sensitive=False)
    def _merge() -> None:
        delivery = SubscriptionDelivery.objects.get(pk=delivery_id)
        # insight_snapshots must already be NUL-scrubbed at its source (build_insight_delivery_snapshot
        # → _serialize_insight_result); a NUL reaching content_snapshot fails this save with a DataError.
        delivery.content_snapshot = {
            **(delivery.content_snapshot or {}),
            "total_insight_count": total_insight_count,
            "insights": insight_snapshots,
        }
        delivery.save(update_fields=["content_snapshot", "last_updated_at"])

    await _merge()
    return snapshot_bytes


async def _fetch_due_subscriptions(
    inputs: FetchDueSubscriptionsActivityInputs,
    *,
    advance_cursor_before_return: bool,
) -> FetchDueSubscriptionsActivityOutput:
    if not 1 <= inputs.max_subscriptions_per_run <= MAX_DUE_SUBSCRIPTIONS_PER_SCHEDULE_RUN:
        raise ValueError(f"max_subscriptions_per_run must be between 1 and {MAX_DUE_SUBSCRIPTIONS_PER_SCHEDULE_RUN}")
    if not 0 <= inputs.buffer_minutes <= 60:
        raise ValueError("buffer_minutes must be between 0 and 60")
    inputs = dataclasses.replace(inputs, region=_resolve_scheduler_region(inputs.region))
    if inputs.use_durable_claims and not inputs.claim_token_seed:
        raise ValueError("claim_token_seed is required when durable claims are enabled")

    now_with_buffer = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=inputs.buffer_minutes)
    await LOGGER.ainfo(
        "Fetching due subscriptions",
        deadline=now_with_buffer,
        max_subscriptions_per_run=inputs.max_subscriptions_per_run,
    )

    @database_sync_to_async(thread_sensitive=False)
    def get_subscriptions() -> _DueSubscriptionsPage:
        due_subscriptions = (
            Subscription.objects.filter(next_delivery_date__lte=now_with_buffer, deleted=False, enabled=True)
            .exclude(dashboard__deleted=True)
            .exclude(insight__deleted=True)
            # Skip relationless subs — resource type derivation raises on them, and one bad row
            # must not fail the whole bounded page.
            .exclude(
                Q(insight_id__isnull=True) & Q(dashboard_id__isnull=True) & (Q(prompt__isnull=True) | Q(prompt=""))
            )
        )
        oldest_due_at = (
            due_subscriptions.order_by("next_delivery_date", "id").values_list("next_delivery_date", flat=True).first()
        )
        with transaction.atomic():
            state, _ = TemporalSchedulerState.objects.get_or_create(
                scheduler=_SUBSCRIPTION_SCHEDULER_NAME,
                region=inputs.region,
            )
            state = TemporalSchedulerState.objects.select_for_update().get(pk=state.pk)
            discovery_cursor = state.discovery_cursor
            try:
                team_cursor = int(discovery_cursor or 0)
            except ValueError:
                team_cursor = 0

            teams_after_cursor = list(
                due_subscriptions.filter(team_id__gt=team_cursor)
                .order_by("team_id")
                .values_list("team_id", flat=True)
                .distinct()[: inputs.max_subscriptions_per_run + 1]
            )
            selected_team_ids = teams_after_cursor[: inputs.max_subscriptions_per_run]
            deferred_teams = len(teams_after_cursor) > inputs.max_subscriptions_per_run
            remaining_team_slots = inputs.max_subscriptions_per_run - len(selected_team_ids)
            if remaining_team_slots:
                teams_before_cursor = list(
                    due_subscriptions.filter(team_id__lte=team_cursor)
                    .order_by("team_id")
                    .values_list("team_id", flat=True)
                    .distinct()[: remaining_team_slots + 1]
                )
                selected_team_ids.extend(teams_before_cursor[:remaining_team_slots])
                deferred_teams = deferred_teams or len(teams_before_cursor) > remaining_team_slots
            elif team_cursor:
                deferred_teams = deferred_teams or due_subscriptions.filter(team_id__lte=team_cursor).exists()

            if not selected_team_ids:
                return _DueSubscriptionsPage([], 0, oldest_due_at, discovery_cursor, ())

            candidate_limit = _SUBSCRIPTION_CANDIDATE_LIMIT
            bounded_candidate_ids = _select_due_subscription_candidate_ids(
                selected_team_ids, now_with_buffer, candidate_limit
            )

            deferred_candidates = len(bounded_candidate_ids) == candidate_limit
            candidate_ids = bounded_candidate_ids

        if not candidate_ids:
            return _DueSubscriptionsPage([], 0, oldest_due_at, discovery_cursor, tuple(selected_team_ids))

        subscriptions_by_id = {
            sub["id"]: sub
            for sub in (
                due_subscriptions.filter(id__in=candidate_ids)
                .annotate(
                    _resource_type=Case(
                        When(insight_id__isnull=False, then=Value(Subscription.ResourceType.INSIGHT)),
                        When(dashboard_id__isnull=False, then=Value(Subscription.ResourceType.DASHBOARD)),
                        default=Value(Subscription.ResourceType.AI_PROMPT),
                    ),
                )
                .values(
                    "id",
                    "team_id",
                    "created_by__distinct_id",
                    "next_delivery_date",
                    "_resource_type",
                )
            )
        }
        # A subscription can be disabled or deleted after the bounded ID query. Treat that as
        # normal concurrent state change instead of letting one vanished row fail the page.
        subscriptions = [
            subscriptions_by_id[subscription_id]
            for subscription_id in candidate_ids
            if subscription_id in subscriptions_by_id
        ]
        results = [
            DueSubscription(
                subscription_id=sub["id"],
                team_id=sub["team_id"],
                distinct_id=str(sub["created_by__distinct_id"])
                if sub["created_by__distinct_id"]
                else str(sub["team_id"]),
                next_delivery_date=sub["next_delivery_date"].isoformat() if sub["next_delivery_date"] else None,
                resource_type=sub["_resource_type"],
            )
            for sub in subscriptions
        ]
        due_items_lower_bound = len(subscriptions) + int(deferred_teams or deferred_candidates)
        return _DueSubscriptionsPage(
            results,
            due_items_lower_bound,
            oldest_due_at,
            discovery_cursor,
            tuple(selected_team_ids),
        )

    page = await get_subscriptions()

    @database_sync_to_async(thread_sensitive=False)
    def reserve_candidates(candidates: list[DueSubscription]) -> _ClaimReservations:
        result = reserve_scheduler_claims(
            scheduler=_SUBSCRIPTION_SCHEDULER_NAME,
            region=inputs.region,
            requests=[
                SchedulerClaimRequest(
                    tenant_key=str(candidate.team_id),
                    occurrence_key=_subscription_occurrence_key(candidate),
                    workflow_id=_subscription_child_workflow_id(candidate),
                    source_due_at=_subscription_source_due_at(candidate),
                    claim_token=uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{inputs.claim_token_seed}:{_subscription_occurrence_key(candidate)}",
                    ),
                )
                for candidate in candidates
            ],
            limits=SchedulerAdmissionLimits(
                max_in_flight=_SUBSCRIPTION_MAX_IN_FLIGHT,
                max_in_flight_per_tenant=_SUBSCRIPTION_MAX_IN_FLIGHT_PER_TENANT,
                lease_duration=_SUBSCRIPTION_RESERVATION_LEASE,
            ),
        )
        return _ClaimReservations(
            reservations={
                reservation.occurrence_key: (str(reservation.claim_id), str(reservation.claim_token))
                for reservation in result.reservations
            },
        )

    examined_team_ids: set[int] = set()
    if inputs.use_durable_claims:
        claimed_subscriptions: list[DueSubscription] = []
        candidate_index = 0
        while len(claimed_subscriptions) < inputs.max_subscriptions_per_run and candidate_index < len(
            page.subscriptions
        ):
            remaining = inputs.max_subscriptions_per_run - len(claimed_subscriptions)
            candidates = page.subscriptions[candidate_index : candidate_index + remaining]
            probe_candidates = [
                dataclasses.replace(
                    candidate,
                    scheduler_claim_id="00000000-0000-0000-0000-000000000000",
                    scheduler_claim_token="00000000-0000-0000-0000-000000000000",
                )
                for candidate in candidates
            ]
            probe = await select_items_within_temporal_payload(
                [*claimed_subscriptions, *probe_candidates],
                build_payload=lambda items: list(items),
                max_items=inputs.max_subscriptions_per_run,
            )
            safe_candidate_count = len(probe.items) - len(claimed_subscriptions)
            if safe_candidate_count <= 0:
                break
            safe_candidates = candidates[:safe_candidate_count]
            candidate_index += safe_candidate_count
            reservation_result = await reserve_candidates(safe_candidates)
            examined_team_ids.update(candidate.team_id for candidate in safe_candidates)
            for candidate in safe_candidates:
                claim = reservation_result.reservations.get(_subscription_occurrence_key(candidate))
                if claim is not None:
                    claimed_subscriptions.append(
                        dataclasses.replace(
                            candidate,
                            scheduler_claim_id=claim[0],
                            scheduler_claim_token=claim[1],
                        )
                    )
        subscriptions_for_payload = claimed_subscriptions
    else:
        subscriptions_for_payload = page.subscriptions

    selection = await select_items_within_temporal_payload(
        subscriptions_for_payload,
        build_payload=lambda items: list(items),
        max_items=inputs.max_subscriptions_per_run,
    )
    if inputs.use_durable_claims and len(selection.items) < len(subscriptions_for_payload):

        @database_sync_to_async(thread_sensitive=False)
        def release_payload_deferred_claims() -> None:
            for subscription in subscriptions_for_payload[len(selection.items) :]:
                if subscription.scheduler_claim_id and subscription.scheduler_claim_token:
                    release_scheduler_claim(
                        uuid.UUID(subscription.scheduler_claim_id),
                        uuid.UUID(subscription.scheduler_claim_token),
                        error="deferred by the scheduler payload guard",
                    )

        await release_payload_deferred_claims()
    if inputs.use_durable_claims:
        cursor_team_id = None
        for selected_team_id in page.selected_team_ids:
            if selected_team_id not in examined_team_ids:
                break
            cursor_team_id = str(selected_team_id)
        if len(selection.items) < len(subscriptions_for_payload):
            cursor_team_id = str(selection.items[-1].team_id) if selection.items else None
    else:
        cursor_team_id = str(selection.items[-1].team_id) if selection.items else None

    if advance_cursor_before_return and cursor_team_id is not None:
        await database_sync_to_async(_advance_subscription_scheduler_cursor, thread_sensitive=False)(
            AdvanceSubscriptionSchedulerCursorInputs(
                region=inputs.region,
                expected_discovery_cursor=page.discovery_cursor,
                next_discovery_cursor=cursor_team_id,
            )
        )
    limited_by = (
        "item_limit"
        if selection.limited_by == "none" and page.due_items_lower_bound > len(selection.items)
        else selection.limited_by
    )
    oldest_age_seconds = (
        max((dt.datetime.now(dt.UTC) - page.oldest_due_at).total_seconds(), 0) if page.oldest_due_at else 0
    )
    record_scheduler_metrics_safely(
        lambda: DEFAULT_SCHEDULER_METRICS.observe_payload(
            _SUBSCRIPTION_SCHEDULER_NAME,
            inputs.region,
            "discovery",
            selection.encoded_size_bytes,
        )
    )
    record_scheduler_metrics_safely(
        lambda: DEFAULT_SCHEDULER_METRICS.set_backlog(
            _SUBSCRIPTION_SCHEDULER_NAME,
            inputs.region,
            due_items_lower_bound=page.due_items_lower_bound,
            oldest_age_seconds=oldest_age_seconds,
        )
    )
    await LOGGER.ainfo(
        "Fetched due subscriptions",
        due_items_lower_bound=page.due_items_lower_bound,
        selected_count=len(selection.items),
        encoded_size_bytes=selection.encoded_size_bytes,
        limited_by=limited_by,
        oldest_age_seconds=oldest_age_seconds,
    )

    return FetchDueSubscriptionsActivityOutput(
        subscriptions=list(selection.items),
        expected_discovery_cursor=page.discovery_cursor,
        next_discovery_cursor=cursor_team_id,
        region=inputs.region,
    )


def _advance_subscription_scheduler_cursor(inputs: AdvanceSubscriptionSchedulerCursorInputs) -> bool:
    state = TemporalSchedulerState.objects.filter(
        scheduler=_SUBSCRIPTION_SCHEDULER_NAME,
        region=inputs.region,
    )
    updated = state.filter(discovery_cursor=inputs.expected_discovery_cursor).update(
        discovery_cursor=inputs.next_discovery_cursor,
        updated_at=tz.now(),
    )
    if updated:
        return True
    return state.filter(discovery_cursor=inputs.next_discovery_cursor).exists()


@temporalio.activity.defn
async def fetch_due_subscriptions_activity(inputs: FetchDueSubscriptionsActivityInputs) -> list[DueSubscription]:
    if inputs.use_durable_claims:
        raise ValueError("fetch_due_subscriptions_activity does not support durable claims")
    output = await _fetch_due_subscriptions(inputs, advance_cursor_before_return=True)
    return output.subscriptions


@temporalio.activity.defn
async def fetch_claimed_due_subscriptions_activity(
    inputs: FetchDueSubscriptionsActivityInputs,
) -> FetchDueSubscriptionsActivityOutput:
    if not inputs.use_durable_claims:
        raise ValueError("fetch_claimed_due_subscriptions_activity requires use_durable_claims=True")
    return await _fetch_due_subscriptions(inputs, advance_cursor_before_return=False)


@temporalio.activity.defn
async def advance_subscription_scheduler_cursor_activity(
    inputs: AdvanceSubscriptionSchedulerCursorInputs,
) -> bool:
    inputs = dataclasses.replace(inputs, region=_resolve_scheduler_region(inputs.region))
    return await database_sync_to_async(_advance_subscription_scheduler_cursor, thread_sensitive=False)(inputs)


@temporalio.activity.defn
async def recover_subscription_scheduler_claims_activity(
    inputs: RecoverSubscriptionSchedulerClaimsInputs,
) -> dict[str, int]:
    recovery_started_at = _monotonic()
    recovery_deadline = recovery_started_at + _SUBSCRIPTION_RECOVERY_ACTIVITY_BUDGET.total_seconds()
    status_deadline = recovery_started_at + _SUBSCRIPTION_RECOVERY_STATUS_BUDGET.total_seconds()
    inputs = dataclasses.replace(inputs, region=_resolve_scheduler_region(inputs.region))
    if not 1 <= inputs.limit <= MAX_DUE_SUBSCRIPTIONS_PER_SCHEDULE_RUN:
        raise ValueError(f"limit must be between 1 and {MAX_DUE_SUBSCRIPTIONS_PER_SCHEDULE_RUN}")

    @database_sync_to_async(thread_sensitive=False)
    def load_expired_claims() -> _ExpiredSchedulerClaimsSnapshot:
        now = tz.now()
        expired = [
            (claim.id, claim.claim_token, claim.workflow_id, claim.status, claim.lease_expires_at)
            for claim in list_expired_scheduler_claims(
                scheduler=_SUBSCRIPTION_SCHEDULER_NAME,
                region=inputs.region,
                limit=inputs.limit,
            )
            if claim.lease_expires_at is not None
        ]
        pruned = prune_inactive_scheduler_claims(
            scheduler=_SUBSCRIPTION_SCHEDULER_NAME,
            region=inputs.region,
            completed_before=now - dt.timedelta(days=7),
            available_before=now - dt.timedelta(days=1),
            limit=inputs.limit,
        )
        return _ExpiredSchedulerClaimsSnapshot(claims=expired, pruned=pruned)

    expired_snapshot = await load_expired_claims()
    expired_claims = expired_snapshot.claims
    pruned = expired_snapshot.pruned
    if not expired_claims:
        return {"released": 0, "renewed": 0, "retained": 0, "pruned": pruned}

    temporal = await async_connect()
    semaphore = asyncio.Semaphore(_SUBSCRIPTION_RECOVERY_CONCURRENCY)

    async def workflow_is_open(workflow_id: str) -> _WorkflowClaimStatus | None:
        async with semaphore:
            remaining_status_budget = status_deadline - _monotonic()
            if remaining_status_budget <= 0:
                return None
            try:
                description = await temporal.get_workflow_handle(workflow_id).describe(
                    rpc_timeout=min(_SUBSCRIPTION_RECOVERY_RPC_TIMEOUT, dt.timedelta(seconds=remaining_status_budget))
                )
            except RPCError as error:
                if error.status == RPCStatusCode.NOT_FOUND:
                    return _WorkflowClaimStatus(is_open=False)
                return _WorkflowClaimStatus(is_open=None, error=f"{type(error).__name__}: {error}")
            except Exception as error:
                return _WorkflowClaimStatus(is_open=None, error=f"{type(error).__name__}: {error}")
            return _WorkflowClaimStatus(is_open=description.status == WorkflowExecutionStatus.RUNNING)

    statuses = await asyncio.gather(*(workflow_is_open(workflow_id) for _, _, workflow_id, _, _ in expired_claims))

    result, unprocessed = await database_sync_to_async(_reconcile_expired_subscription_claims, thread_sensitive=False)(
        expired_claims,
        statuses,
        pruned=pruned,
        recovery_deadline=recovery_deadline,
    )
    await LOGGER.ainfo("Recovered subscription scheduler claims", **result, unprocessed=unprocessed)
    return result


@temporalio.activity.defn
async def confirm_subscription_scheduler_claim_activity(inputs: SubscriptionSchedulerClaimInputs) -> bool:
    now = tz.now()
    lease_duration = _SUBSCRIPTION_EXECUTION_LEASE
    if inputs.lease_expires_at is not None:
        lease_expires_at = datetime.fromisoformat(inputs.lease_expires_at)
        if lease_expires_at.tzinfo is None:
            raise ValueError("lease_expires_at must include a timezone")
        lease_duration = lease_expires_at - now
        if lease_duration <= dt.timedelta(0):
            return False
    return await database_sync_to_async(confirm_scheduler_claim, thread_sensitive=False)(
        uuid.UUID(inputs.claim_id),
        uuid.UUID(inputs.claim_token),
        lease_duration=lease_duration,
        now=now,
    )


@temporalio.activity.defn
async def complete_subscription_scheduler_claim_activity(inputs: SubscriptionSchedulerClaimInputs) -> bool:
    return await database_sync_to_async(complete_scheduler_claim, thread_sensitive=False)(
        uuid.UUID(inputs.claim_id),
        uuid.UUID(inputs.claim_token),
    )


@temporalio.activity.defn
async def release_subscription_scheduler_claim_activity(inputs: SubscriptionSchedulerClaimInputs) -> bool:
    return await database_sync_to_async(release_scheduler_claim, thread_sensitive=False)(
        uuid.UUID(inputs.claim_id),
        uuid.UUID(inputs.claim_token),
        error="scheduled delivery did not advance its next delivery date",
    )


@temporalio.activity.defn
async def validate_subscription_for_delivery(subscription_id: int) -> DeliveryAbort | None:
    """Returns abort info when delivery should not proceed; None to continue."""
    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "integration").get,
        thread_sensitive=False,
    )(pk=subscription_id)

    # Idempotency: a Temporal redispatch (e.g. worker crash mid-acknowledge) after a
    # prior auto-disable committed must not re-fire side effects.
    if not subscription.enabled or subscription.deleted:
        await LOGGER.ainfo("validate_subscription.inactive_skipping", subscription_id=subscription_id)
        return DeliveryAbort()

    reason = get_subscription_disable_reason(subscription.target_type, subscription.integration_id)
    if reason is None:
        return None

    LOGGER.warning(
        "validate_subscription.invalid_auto_disabling",
        subscription_id=subscription_id,
        target_type=subscription.target_type,
        reason=reason.key,
    )
    _capture_delivery_failed_event(subscription, Exception(reason.description))
    await database_sync_to_async(disable_invalid_subscription, thread_sensitive=False)(subscription, reason)
    return DeliveryAbort(
        failed_recipient=RecipientResult(
            recipient=subscription.recipient_label,
            status="failed",
            error={"message": reason.description, "type": reason.key},
            human_readable_error=reason.description,
        )
    )


@temporalio.activity.defn
async def create_export_assets(inputs: CreateExportAssetsInputs) -> CreateExportAssetsResult:
    await LOGGER.ainfo(
        "create_export_assets.starting",
        subscription_id=inputs.subscription_id,
    )

    max_asset_count = inputs.max_asset_count if inputs.max_asset_count is not None else MAX_INSIGHTS
    if max_asset_count <= 0:
        raise ApplicationError(
            f"Dashboard insight export limit must be at least 1, received {max_asset_count} for subscription {inputs.subscription_id}",
            non_retryable=True,
        )

    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "insight", "dashboard", "team").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)

    team = subscription.team
    dashboard = subscription.dashboard

    await LOGGER.ainfo(
        "create_export_assets.loaded",
        subscription_id=inputs.subscription_id,
        has_dashboard=bool(dashboard),
        has_insight=bool(subscription.insight_id),
        target_type=subscription.target_type,
    )

    resolved_insights = await _resolve_exportable_insights(subscription)
    tile_insight_pairs = resolved_insights.tile_insight_pairs

    total_insight_count = len(tile_insight_pairs)

    if not tile_insight_pairs:
        no_exportable_reason = resolved_insights.no_exportable_reason
        if no_exportable_reason is None:
            raise RuntimeError("No-exportable-insights resolution missing a failure reason")
        failure_context: NoExportableInsightsContext = {
            "reason": no_exportable_reason,
            "resource_type": "dashboard" if dashboard else "insight" if subscription.insight_id else "unknown",
            "available_insight_count": resolved_insights.available_insight_count,
            "selected_insight_count": resolved_insights.selected_insight_count,
        }
        await LOGGER.awarning(
            "create_export_assets.no_exportable_insights",
            subscription_id=inputs.subscription_id,
            dashboard_id=subscription.dashboard_id,
            insight_id=subscription.insight_id,
            **failure_context,
        )
        _capture_delivery_failed_event(
            subscription,
            NoExportableInsightsError(no_exportable_reason),
            failure_context,
        )
        return CreateExportAssetsResult(
            exported_asset_ids=[],
            total_insight_count=total_insight_count,
            team_id=team.id,
            distinct_id=str(subscription.created_by.distinct_id) if subscription.created_by else str(team.id),
            target_type=subscription.target_type,
            available_insight_count=resolved_insights.available_insight_count,
            selected_insight_count=resolved_insights.selected_insight_count,
            status=ExportAssetPreparationStatus.NO_EXPORTABLE_INSIGHTS,
            failure_context=failure_context,
        )

    export_pairs = tile_insight_pairs[:max_asset_count]

    expiry = ExportedAsset.compute_expires_after(ExportedAsset.ExportFormat.PNG)
    assets = [
        ExportedAsset(
            team=team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
            dashboard=dashboard,
            expires_after=expiry,
            # The exporter runs the insight query as the asset's creator; without it the render is
            # userless and warehouse access control fails closed, breaking subscription deliveries.
            created_by=subscription.created_by,
        )
        for _tile, insight in export_pairs
    ]
    await database_sync_to_async(ExportedAsset.objects.bulk_create, thread_sensitive=False)(assets)

    @database_sync_to_async(thread_sensitive=False)
    def build_insight_snapshots() -> list[dict[str, typing.Any]]:
        return [
            build_insight_delivery_snapshot(
                insight=insight,
                team=team,
                dashboard=dashboard,
                tile=tile,
                user=subscription.created_by,
            )
            for tile, insight in export_pairs
        ]

    insight_snapshots = await build_insight_snapshots()

    # Persist insight snapshots directly on SubscriptionDelivery.content_snapshot
    # instead of returning them across the Temporal activity boundary — per-insight
    # query_results can reach multi-MB and will trip Temporal's ~2 MiB payload cap.
    # Standalone callers (tests, management commands) that don't pass delivery_id
    # skip the persist — they don't have a row to write to.
    target_delivery_id = inputs.delivery_id
    if target_delivery_id is not None:
        snapshot_bytes = await _persist_content_snapshot(
            delivery_id=target_delivery_id,
            total_insight_count=total_insight_count,
            insight_snapshots=insight_snapshots,
        )
        await LOGGER.ainfo(
            "create_export_assets.content_snapshot_persisted",
            subscription_id=inputs.subscription_id,
            delivery_id=str(target_delivery_id),
            insight_count=len(insight_snapshots),
            snapshot_bytes=snapshot_bytes,
        )

    await LOGGER.ainfo(
        "create_export_assets.assets_created",
        subscription_id=inputs.subscription_id,
        asset_count=len(assets),
        total_insights=total_insight_count,
    )
    return CreateExportAssetsResult(
        exported_asset_ids=[a.id for a in assets],
        total_insight_count=total_insight_count,
        team_id=team.id,
        distinct_id=str(subscription.created_by.distinct_id) if subscription.created_by else str(team.id),
        target_type=subscription.target_type,
        available_insight_count=resolved_insights.available_insight_count,
        selected_insight_count=resolved_insights.selected_insight_count,
    )


@temporalio.activity.defn
async def deliver_subscription(inputs: DeliverSubscriptionInputs) -> DeliverSubscriptionResult:
    # TODO(2026-07-31): After workflows started before 2026-07-31 have drained, remove this v1 activity,
    # rename deliver_subscription_v2 to deliver_subscription, and remove the workflow patch.
    return await _deliver_subscription(inputs)


@temporalio.activity.defn(name="deliver-subscription-v2")
async def deliver_subscription_v2(inputs: DeliverSubscriptionInputs) -> DeliverSubscriptionResult:
    return await _deliver_subscription(inputs)


async def _deliver_subscription(inputs: DeliverSubscriptionInputs) -> DeliverSubscriptionResult:
    recipient_results: list[RecipientResult] = []

    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "insight", "dashboard", "team", "integration").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)

    # Activity-retry idempotency: if a previous attempt already auto-disabled this
    # subscription (UPDATE committed) and Temporal redispatched the activity (e.g.
    # worker crash mid-acknowledge), don't re-fire the disable side effects — UUID4
    # campaign keys mean MessagingRecord wouldn't dedup the duplicate email.
    if not subscription.enabled or subscription.deleted:
        LOGGER.info("deliver_subscription.skipped_inactive", subscription_id=inputs.subscription_id)
        return DeliverSubscriptionResult(recipient_results=[], skipped=True)

    previous_target_value = inputs.previous_target_value
    if previous_target_value is None:
        previous_target_value = inputs.previous_value
    send_only_to_new_recipients = (
        inputs.is_new_subscription_target
        if inputs.is_new_subscription_target is not None
        else previous_target_value is not None and previous_target_value != subscription.target_value
    )

    await LOGGER.ainfo(
        "deliver_subscription.starting",
        subscription_id=inputs.subscription_id,
        target_type=subscription.target_type,
        asset_count=len(inputs.exported_asset_ids),
        is_new=send_only_to_new_recipients,
        resource_type=subscription.resource_type,
    )

    if subscription.resource_type == Subscription.ResourceType.AI_PROMPT:
        return await _deliver_ai_subscription(subscription, inputs, recipient_results)

    return await _deliver_insight_dashboard_subscription(
        subscription, inputs, recipient_results, send_only_to_new_recipients
    )


async def _deliver_insight_dashboard_subscription(
    subscription: Subscription,
    inputs: DeliverSubscriptionInputs,
    recipient_results: list[RecipientResult],
    send_only_to_new_recipients: bool,
) -> DeliverSubscriptionResult:
    if (
        get_subscription_disable_reason(subscription.target_type, subscription.integration_id)
        == UNSUPPORTED_TARGET_DISABLE_REASON
    ):
        LOGGER.warning(
            "deliver_subscription.unsupported_target",
            subscription_id=inputs.subscription_id,
            target_type=subscription.target_type,
        )
        return await auto_disable_and_return(
            subscription,
            UNSUPPORTED_TARGET_DISABLE_REASON,
            recipient_results,
        )

    assets_by_id = await database_sync_to_async(
        lambda: {
            a.id: a
            for a in ExportedAsset.objects_including_ttl_deleted.select_related("insight", "dashboard").filter(
                pk__in=inputs.exported_asset_ids
            )
        },
        thread_sensitive=False,
    )()
    # Preserve the order from create_export_assets (sorted by dashboard tile layout)
    assets = [assets_by_id[aid] for aid in inputs.exported_asset_ids if aid in assets_by_id]

    if not assets:
        # Empty here means non-empty exported_asset_ids didn't resolve from DB — a
        # transient condition (TTL sweep, prior export crash, S3 race). Genuine
        # deletion is filtered upstream in create_export_assets and the workflow
        # short-circuits to SKIPPED before this activity runs. Don't auto-disable;
        # the failure is observable via the `subscription_delivery_failed` analytics
        # event and the next scheduled delivery retries.
        LOGGER.warning("deliver_subscription.no_assets", subscription_id=inputs.subscription_id)
        recipient_results.append(
            RecipientResult(
                recipient=subscription.recipient_label,
                status="failed",
                error={"message": NO_ASSETS_REASON, "type": "no_assets"},
                human_readable_error=NO_ASSETS_HUMAN_READABLE_REASON,
            )
        )
        # Plain Exception — `_capture_delivery_failed_event` only reads `str(e)` and
        # `type(e).__name__`, and the activity returns cleanly so retry semantics on
        # ApplicationError would be misleading (matches `_auto_disable_and_return`).
        _capture_delivery_failed_event(subscription, Exception(NO_ASSETS_REASON))
        return DeliverSubscriptionResult(recipient_results=recipient_results)

    if subscription.target_type == Subscription.SubscriptionTarget.EMAIL:

        async def _send_email(email: str) -> None:
            await database_sync_to_async(send_email_subscription_report, thread_sensitive=False)(
                email,
                subscription,
                assets,
                invite_message=inputs.invite_message or "" if send_only_to_new_recipients else None,
                total_asset_count=inputs.total_insight_count,
                send_async=False,
                change_summary=inputs.change_summary,
                summary_skipped_over_budget=inputs.summary_skipped_over_budget,
                delivery_id=inputs.delivery_id,
            )

        result = await deliver_email(subscription, inputs, recipient_results, _send_email)
    elif subscription.target_type == Subscription.SubscriptionTarget.SLACK:
        result = await deliver_slack(
            subscription,
            recipient_results,
            lambda integration: send_slack_message_with_integration_async(
                integration,
                subscription,
                assets,
                total_asset_count=inputs.total_insight_count,
                is_new_subscription=send_only_to_new_recipients,
                change_summary=inputs.change_summary,
                summary_skipped_over_budget=inputs.summary_skipped_over_budget,
            ),
        )
    elif subscription.target_type == Subscription.SubscriptionTarget.TEAMS:
        card = build_teams_subscription_card(
            subscription,
            assets,
            inputs.total_insight_count,
            is_new_subscription=send_only_to_new_recipients,
            change_summary=inputs.change_summary,
            summary_skipped_over_budget=inputs.summary_skipped_over_budget,
        )
        result = await deliver_teams_webhook(subscription, recipient_results, body=card)
    else:
        raise ApplicationError(
            f"Subscription delivery reached an unsupported target {subscription.target_type!r}",
            non_retryable=True,
        )

    await LOGGER.ainfo(
        "deliver_subscription.completed",
        subscription_id=inputs.subscription_id,
        target_type=subscription.target_type,
    )
    return result


@temporalio.activity.defn
async def create_delivery_record(inputs: CreateDeliveryRecordInputs) -> uuid.UUID:
    scheduled_at = datetime.fromisoformat(inputs.scheduled_at) if inputs.scheduled_at else None

    @database_sync_to_async(thread_sensitive=False)
    def _create() -> uuid.UUID:
        subscription = Subscription.objects.select_related("insight", "dashboard").get(pk=inputs.subscription_id)
        if subscription.team_id != inputs.team_id:
            raise ValueError(
                f"Subscription team_id ({subscription.team_id}) does not match inputs.team_id ({inputs.team_id})"
            )

        content_snapshot = build_initial_content_snapshot(subscription)

        delivery, _created = SubscriptionDelivery.objects.get_or_create(
            idempotency_key=inputs.idempotency_key,
            defaults={
                "subscription": subscription,
                "team_id": inputs.team_id,
                "temporal_workflow_id": inputs.temporal_workflow_id,
                "trigger_type": inputs.trigger_type,
                "scheduled_at": scheduled_at,
                "target_type": subscription.target_type,
                "target_value": subscription.recipient_label,
                "content_snapshot": content_snapshot,
                "status": SubscriptionDelivery.Status.STARTING,
            },
        )
        return delivery.id

    delivery_id = await _create()
    await LOGGER.ainfo(
        "create_delivery_record.created",
        subscription_id=inputs.subscription_id,
        delivery_id=delivery_id,
    )
    return delivery_id


@temporalio.activity.defn
async def update_delivery_record(inputs: UpdateDeliveryRecordInputs) -> None:
    @database_sync_to_async(thread_sensitive=False)
    def _update() -> None:
        delivery = SubscriptionDelivery.objects.get(pk=inputs.delivery_id)
        update_fields: list[str] = ["status", "last_updated_at"]
        delivery.status = inputs.status

        if inputs.exported_asset_ids is not None:
            delivery.exported_asset_ids = inputs.exported_asset_ids
            update_fields.append("exported_asset_ids")
        if inputs.recipient_results is not None:
            delivery.recipient_results = inputs.recipient_results
            update_fields.append("recipient_results")
        if inputs.change_summary is not None:
            delivery.change_summary = inputs.change_summary
            update_fields.append("change_summary")
        delivery.error = inputs.error
        update_fields.append("error")
        if inputs.finished:
            delivery.finished_at = tz.now()
            update_fields.append("finished_at")

        delivery.save(update_fields=update_fields)

    await _update()
    await LOGGER.ainfo(
        "update_delivery_record.updated",
        delivery_id=inputs.delivery_id,
        status=inputs.status,
    )


@temporalio.activity.defn
async def notify_subscription_delivery_failure(subscription_id: int, failure_id: str) -> None:
    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by").get,
        thread_sensitive=False,
    )(pk=subscription_id)
    errors: list[Exception] = []
    try:
        await database_sync_to_async(send_subscription_delivery_failure_email, thread_sensitive=False)(
            subscription, failure_id
        )
    except Exception as error:
        errors.append(error)
        LOGGER.exception("notify_subscription_delivery_failure.email_failed", subscription_id=subscription_id)

    try:
        await database_sync_to_async(create_subscription_delivery_failure_notification, thread_sensitive=False)(
            subscription, failure_id
        )
    except Exception as error:
        errors.append(error)
        LOGGER.exception(
            "notify_subscription_delivery_failure.in_app_notification_failed", subscription_id=subscription_id
        )

    if errors:
        raise errors[0]


@temporalio.activity.defn
async def advance_next_delivery_date(subscription_id: int) -> None:
    subscription = await database_sync_to_async(Subscription.objects.get, thread_sensitive=False)(pk=subscription_id)
    # Disabled subs (e.g. auto-disabled this run / paused by user) don't get a
    # future delivery date — avoids showing a misleading "next delivery" in the UI.
    if not subscription.enabled or subscription.deleted:
        await LOGGER.ainfo("advance_next_delivery_date.skipped_inactive", subscription_id=subscription_id)
        return
    subscription.set_next_delivery_date(subscription.next_delivery_date)
    await database_sync_to_async(subscription.save, thread_sensitive=False)(update_fields=["next_delivery_date"])
    await LOGGER.ainfo(
        "advance_next_delivery_date.updated",
        subscription_id=subscription_id,
        next_delivery_date=subscription.next_delivery_date,
    )


@temporalio.activity.defn
async def advance_next_delivery_date_v2(inputs: AdvanceNextDeliveryDateInputs) -> bool:
    expected_next_delivery_date = dt.datetime.fromisoformat(inputs.expected_next_delivery_date)
    if tz.is_naive(expected_next_delivery_date):
        raise ValueError("expected_next_delivery_date must be timezone-aware")

    @database_sync_to_async(thread_sensitive=False)
    def advance_if_current() -> _AdvanceNextDeliveryDateResult:
        with transaction.atomic():
            subscription = Subscription.objects.select_for_update().get(pk=inputs.subscription_id)
            if not subscription.enabled or subscription.deleted:
                return _AdvanceNextDeliveryDateResult(
                    advanced=False, next_delivery_date=subscription.next_delivery_date, outcome="inactive"
                )
            if subscription.next_delivery_date is None:
                return _AdvanceNextDeliveryDateResult(
                    advanced=True, next_delivery_date=None, outcome="already_advanced"
                )
            if subscription.next_delivery_date < expected_next_delivery_date:
                return _AdvanceNextDeliveryDateResult(
                    advanced=False, next_delivery_date=subscription.next_delivery_date, outcome="schedule_changed"
                )
            if subscription.next_delivery_date > expected_next_delivery_date:
                return _AdvanceNextDeliveryDateResult(
                    advanced=True, next_delivery_date=subscription.next_delivery_date, outcome="already_advanced"
                )

            subscription.set_next_delivery_date(expected_next_delivery_date)
            subscription.save(update_fields=["next_delivery_date"])
            return _AdvanceNextDeliveryDateResult(
                advanced=True, next_delivery_date=subscription.next_delivery_date, outcome="advanced"
            )

    result = await advance_if_current()
    await LOGGER.ainfo(
        "advance_next_delivery_date_v2.finished",
        subscription_id=inputs.subscription_id,
        next_delivery_date=result.next_delivery_date,
        outcome=result.outcome,
    )
    return result.advanced
