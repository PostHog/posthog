"""The subscription API's reads: lists, single rows, delivery history and AI summaries, as contracts."""

import operator
from collections.abc import Iterable
from functools import reduce

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import OuterRef, Prefetch, Q, QuerySet, Subquery

from posthog.api.pagination import stable_queryset_ordering
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.product_analytics.backend.facade.api import insights_including_soft_deleted_for_team
from products.subscriptions.backend.facade.contracts import (
    CreatedAtCursorWindow,
    MalformedIdError,
    SubscriptionCreator,
    SubscriptionDashboardContext,
    SubscriptionDeliveryRecord,
    SubscriptionFilters,
    SubscriptionInsightContext,
    SubscriptionListQuery,
    SubscriptionNotFoundError,
    SubscriptionPage,
    SubscriptionPermissionDeniedError,
    SubscriptionRecord,
    SubscriptionRef,
    SubscriptionSummaryRecord,
)
from products.subscriptions.backend.models.subscription import Subscription, SubscriptionDelivery
from products.subscriptions.backend.models.subscription_context import SubscriptionContext
from products.subscriptions.backend.temporal.ai_subscription.spec_generator import get_ai_query_plan_status

from .visibility import viewable_delivery_filter, viewable_subscription_filter

# Each search term must match one of these, ignoring case.
SEARCH_LOOKUPS = (
    "title__icontains",
    "insight__name__icontains",
    "insight__derived_name__icontains",
    "dashboard__name__icontains",
    # An AI report's subject lives only in its prompt, so without this the only way to find the
    # reports about a given thing is to fetch every ai_prompt row and sift them client-side.
    # Scoped to one team by the caller, so the ILIKE never widens past that team's rows.
    "prompt__icontains",
)


def context_rows(obj: Subscription) -> Iterable[SubscriptionContext]:
    cached_contexts = getattr(obj, "_prefetched_objects_cache", {}).get("contexts")
    if cached_contexts is not None:
        return cached_contexts
    return (
        SubscriptionContext.objects.for_team(obj.team_id)
        .filter(subscription=obj)
        .select_related("dashboard", "insight")
    )


def _context_records(
    obj: Subscription,
) -> tuple[SubscriptionDashboardContext | SubscriptionInsightContext, ...]:
    if obj.resource_type != Subscription.ResourceType.AI_PROMPT:
        return ()

    contexts: list[SubscriptionDashboardContext | SubscriptionInsightContext] = []
    for context in context_rows(obj):
        if not context.has_live_target_for_team(context.team_id):
            continue

        if context.dashboard_id is not None and context.dashboard is not None:
            contexts.append(
                SubscriptionDashboardContext(
                    dashboard_id=context.dashboard_id,
                    dashboard_name=context.dashboard.name or "Untitled dashboard",
                )
            )
        elif context.insight_id is not None and context.insight is not None:
            contexts.append(
                SubscriptionInsightContext(
                    insight_id=context.insight_id,
                    insight_short_id=context.insight.short_id,
                    insight_name=str(context.insight),
                )
            )
    return tuple(contexts)


def _creator(user: User | None) -> SubscriptionCreator | None:
    if user is None:
        return None
    return SubscriptionCreator(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )


def subscription_record(obj: Subscription) -> SubscriptionRecord:
    resource_info = obj.resource_info
    resource_type = obj.resource_type
    return SubscriptionRecord(
        id=obj.id,
        team_id=obj.team_id,
        resource_type=resource_type,
        dashboard_id=obj.dashboard_id,
        insight_id=obj.insight_id,
        insight_short_id=obj.insight.short_id if obj.insight_id and obj.insight is not None else None,
        resource_name=resource_info.name if resource_info else None,
        dashboard_export_insight_ids=tuple(insight.id for insight in obj.dashboard_export_insights.all()),
        prompt=obj.prompt,
        ai_prompt_config=obj.ai_prompt_config,
        contexts=_context_records(obj),
        ai_query_plan_status=(
            get_ai_query_plan_status(obj.ai_query_plan).value
            if resource_type == Subscription.ResourceType.AI_PROMPT
            else None
        ),
        target_type=obj.target_type,
        target_value=obj.target_value,
        recipient_label=obj.recipient_label,
        frequency=obj.frequency,
        interval=obj.interval,
        byweekday=tuple(obj.byweekday) if obj.byweekday is not None else None,
        bysetpos=obj.bysetpos,
        count=obj.count,
        start_date=obj.start_date,
        until_date=obj.until_date,
        created_at=obj.created_at,
        created_by_id=obj.created_by_id,
        created_by=_creator(obj.created_by),
        deleted=obj.deleted,
        enabled=obj.enabled,
        title=obj.title,
        summary=obj.summary,
        next_delivery_date=obj.next_delivery_date,
        integration_id=obj.integration_id,
        summary_enabled=obj.summary_enabled,
        summary_prompt_guide=obj.summary_prompt_guide,
        delivery_config=obj.delivery_config,
    )


def delivery_record(delivery: SubscriptionDelivery) -> SubscriptionDeliveryRecord:
    return SubscriptionDeliveryRecord(
        id=delivery.id,
        subscription_id=delivery.subscription_id,
        temporal_workflow_id=delivery.temporal_workflow_id,
        idempotency_key=delivery.idempotency_key,
        trigger_type=delivery.trigger_type,
        scheduled_at=delivery.scheduled_at,
        target_type=delivery.target_type,
        target_value=delivery.target_value,
        exported_asset_ids=tuple(delivery.exported_asset_ids),
        content_snapshot=delivery.content_snapshot,
        recipient_results=delivery.recipient_results,
        status=delivery.status,
        error=delivery.error,
        created_at=delivery.created_at,
        last_updated_at=delivery.last_updated_at,
        finished_at=delivery.finished_at,
        change_summary=delivery.change_summary,
    )


def _filter_subscriptions(queryset: QuerySet, filters: SubscriptionFilters) -> QuerySet:
    if filters.deleted is not None:
        queryset = queryset.filter(deleted=filters.deleted)
    if filters.insight_ids is not None:
        queryset = queryset.filter(insight_id__in=filters.insight_ids)
    if filters.any_of_insight_ids is not None:
        queryset = queryset.filter(insight_id__in=filters.any_of_insight_ids)
    if filters.tile_insight_ids is not None:
        queryset = queryset.filter(insight_id__in=filters.tile_insight_ids)
    if filters.dashboard_id is not None:
        queryset = queryset.filter(dashboard_id=filters.dashboard_id)
    if filters.search_terms:
        conditions = (
            reduce(operator.or_, (Q(**{lookup: term}) for lookup in SEARCH_LOOKUPS)) for term in filters.search_terms
        )
        queryset = queryset.filter(reduce(operator.and_, conditions))
    return queryset


def list_subscriptions(
    *, team_id: int, query: SubscriptionListQuery, viewer: UserAccessControl, offset: int, limit: int
) -> SubscriptionPage:
    context_queryset = SubscriptionContext.objects.for_team(team_id).select_related("dashboard", "insight")
    queryset = Subscription.objects.prefetch_related(
        "dashboard_export_insights",
        Prefetch("contexts", queryset=context_queryset),
    ).select_related("insight", "dashboard", "created_by")

    if query.created_by_uuid:
        queryset = queryset.filter(created_by__uuid=query.created_by_uuid)

    if query.resource_type == "insight":
        queryset = queryset.filter(insight_id__isnull=False)
    elif query.resource_type == "dashboard":
        queryset = queryset.filter(dashboard_id__isnull=False)
    elif query.resource_type == "ai_prompt":
        queryset = queryset.filter(prompt__isnull=False).exclude(prompt="")

    if query.target_type:
        queryset = queryset.filter(target_type=query.target_type)

    queryset = _filter_subscriptions(queryset, query.filters)
    queryset = queryset.filter(viewable_subscription_filter(viewer, team_id)).distinct()
    queryset = queryset.filter(team_id=team_id)
    if query.filter_by_object_access:
        queryset = viewer.filter_queryset_by_access_level(queryset, include_all_if_admin=query.include_all_if_admin)
    if query.ordering:
        queryset = queryset.order_by(*query.ordering)
    queryset = stable_queryset_ordering(queryset)

    count = queryset.count()
    if count == 0 or offset > count:
        return SubscriptionPage(count=count, results=())
    return SubscriptionPage(
        count=count, results=tuple(subscription_record(obj) for obj in queryset[offset : offset + limit])
    )


def get_subscription_row(
    *, team_id: int, subscription_id: str | int, filters: SubscriptionFilters, viewer: UserAccessControl
) -> Subscription:
    queryset = _filter_subscriptions(Subscription.objects.all(), filters).filter(team_id=team_id)
    try:
        subscription = queryset.get(pk=subscription_id)
    except Subscription.DoesNotExist:
        raise SubscriptionNotFoundError(str(subscription_id))
    can_view_subscription = (
        Subscription.objects.filter(pk=subscription.pk, team_id=team_id)
        .filter(viewable_subscription_filter(viewer, team_id))
        .exists()
    )
    if not can_view_subscription:
        raise SubscriptionPermissionDeniedError(
            "You do not have viewer access to this subscription. Ask an organization admin to update your access."
        )
    return subscription


def get_subscription_ref(
    *, team_id: int, subscription_id: str | int, filters: SubscriptionFilters, viewer: UserAccessControl
) -> SubscriptionRef:
    subscription = get_subscription_row(
        team_id=team_id, subscription_id=subscription_id, filters=filters, viewer=viewer
    )
    return SubscriptionRef(
        id=subscription.id,
        team_id=subscription.team_id,
        created_by_id=subscription.created_by_id,
        deleted=subscription.deleted,
        enabled=subscription.enabled,
        target_type=subscription.target_type,
        insight_id=subscription.insight_id,
        dashboard_id=subscription.dashboard_id,
    )


def get_subscription(*, team_id: int, subscription_id: int) -> SubscriptionRecord:
    return subscription_record(Subscription.objects.get(pk=subscription_id, team_id=team_id))


def is_ai_prompt_subscription(*, team_id: int, subscription_id: str | int) -> bool:
    """An AI subscription is one backed by a non-empty prompt (team-scoped)."""
    return (
        Subscription.objects.filter(pk=subscription_id, team_id=team_id)
        .exclude(prompt__isnull=True)
        .exclude(prompt="")
        .exists()
    )


def _window(queryset: QuerySet, window: CreatedAtCursorWindow) -> list:
    queryset = queryset.order_by("-created_at" if window.newest_first else "created_at")
    if window.created_before is not None:
        queryset = queryset.filter(created_at__lt=window.created_before)
    if window.created_after is not None:
        queryset = queryset.filter(created_at__gt=window.created_after)
    return list(queryset[window.offset : window.offset + window.limit])


def _deliveries(
    *, team_id: int, subscription_id: str | None, status: str | None, viewer: UserAccessControl
) -> QuerySet[SubscriptionDelivery]:
    queryset = SubscriptionDelivery.objects.all()
    if subscription_id:
        queryset = queryset.filter(subscription_id=subscription_id)
    if status:
        queryset = queryset.filter(status=status)
    queryset = queryset.filter(viewable_delivery_filter(viewer, team_id)).distinct()
    return queryset.filter(team_id=team_id)


def list_subscription_deliveries(
    *,
    team_id: int,
    subscription_id: str | None,
    status: str | None,
    viewer: UserAccessControl,
    window: CreatedAtCursorWindow,
    filter_by_object_access: bool,
    include_all_if_admin: bool,
) -> list[SubscriptionDeliveryRecord]:
    queryset = _deliveries(team_id=team_id, subscription_id=subscription_id, status=status, viewer=viewer)
    if filter_by_object_access:
        queryset = viewer.filter_queryset_by_access_level(queryset, include_all_if_admin=include_all_if_admin)
    return [delivery_record(delivery) for delivery in _window(queryset, window)]


def get_subscription_delivery(
    *, team_id: int, subscription_id: str | None, delivery_id: str, viewer: UserAccessControl
) -> SubscriptionDeliveryRecord:
    queryset = _deliveries(team_id=team_id, subscription_id=subscription_id, status=None, viewer=viewer)
    try:
        delivery = queryset.get(pk=delivery_id)
    except SubscriptionDelivery.DoesNotExist:
        raise SubscriptionNotFoundError(delivery_id)
    except (TypeError, ValueError, DjangoValidationError):
        raise MalformedIdError(delivery_id)
    return delivery_record(delivery)


def viewable_live_insight_id(*, team_id: int, insight_id: int, viewer: UserAccessControl) -> int:
    live_insights = [
        insight
        for insight in insights_including_soft_deleted_for_team(team_id=team_id, insight_ids=[insight_id])
        if not insight.deleted
    ]
    if not live_insights:
        raise SubscriptionNotFoundError(str(insight_id))
    insight = live_insights[0]
    if not viewer.check_access_level_for_object(insight, "viewer"):
        raise SubscriptionPermissionDeniedError("You do not have access to this resource.")
    return insight.pk


def list_subscription_summaries(
    *,
    team_id: int,
    insight_id: int | None,
    dashboard_id: int | None,
    viewer: UserAccessControl,
    window: CreatedAtCursorWindow,
) -> list[SubscriptionSummaryRecord]:
    # A subscription can change its source, so also match the source in the delivery snapshot.
    if insight_id is not None:
        source_filter = Q(subscription__insight_id=insight_id, content_snapshot__insights__0__id=insight_id)
    else:
        source_filter = Q(subscription__dashboard_id=dashboard_id, content_snapshot__dashboard__id=dashboard_id)

    previous_delivery_at = (
        SubscriptionDelivery.objects.filter(
            subscription_id=OuterRef("subscription_id"),
            status=SubscriptionDelivery.Status.COMPLETED,
            content_snapshot__isnull=False,
            created_at__lt=OuterRef("created_at"),
        )
        .order_by("-created_at")
        .values("created_at")[:1]
    )
    visible_ids = (
        SubscriptionDelivery.objects.filter(
            source_filter,
            team_id=team_id,
            subscription__deleted=False,
            status=SubscriptionDelivery.Status.COMPLETED,
            change_summary__isnull=False,
        )
        .exclude(change_summary="")
        .filter(viewable_delivery_filter(viewer, team_id))
        .values("id")
    )
    # An id subquery instead of DISTINCT lets Postgres compute period_start only for the rows on the page.
    deliveries = (
        SubscriptionDelivery.objects.filter(team_id=team_id, id__in=visible_ids)
        .select_related("subscription")
        # content_snapshot holds full query results, so load only the fields the response returns.
        .only("id", "subscription_id", "subscription__title", "target_type", "change_summary", "created_at")
        .annotate(period_start=Subquery(previous_delivery_at))
    )
    return [
        SubscriptionSummaryRecord(
            id=delivery.id,
            subscription_id=delivery.subscription_id,
            subscription_title=delivery.subscription.title,
            target_type=delivery.target_type,
            change_summary=delivery.change_summary,
            period_start=delivery.period_start,
            created_at=delivery.created_at,
        )
        for delivery in _window(deliveries, window)
    ]
