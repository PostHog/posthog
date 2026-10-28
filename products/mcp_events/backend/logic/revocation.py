from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from rest_framework.exceptions import APIException

from posthog.dataclasses import frozen
from posthog.models.personal_api_key import PersonalAPIKey

from products.mcp_events.backend.logic.credentials import lock_subscriber, validate_principal
from products.mcp_events.backend.logic.destination import save_destination
from products.mcp_events.backend.logic.filters import MCPEventFilterAccessValidator, restricted_event_property_names
from products.mcp_events.backend.logic.subscriptions import MCPEventSubscriptions, deactivate
from products.mcp_events.backend.models import MCPEventSubscription

logger = structlog.get_logger(__name__)


@frozen
class SubscriptionReference:
    team_id: int
    id: UUID
    renewed_at: datetime


def _references(subscriptions: QuerySet[MCPEventSubscription]) -> list[SubscriptionReference]:
    return [
        SubscriptionReference(team_id=team_id, id=subscription_id, renewed_at=renewed_at)
        for team_id, subscription_id, renewed_at in subscriptions.values_list("team_id", "id", "renewed_at")
    ]


def _lock_active(team_id: int, subscription_id: UUID) -> MCPEventSubscription | None:
    return (
        MCPEventSubscription.objects.for_team(team_id)
        .select_for_update(of=("self",))
        .select_related("team", "created_by")
        .filter(id=subscription_id, active=True)
        .first()
    )


def revalidate_subscription(team_id: int, subscription_id: UUID) -> None:
    user_id = (
        MCPEventSubscription.objects.for_team(team_id)
        .filter(id=subscription_id, active=True)
        .values_list("created_by_id", flat=True)
        .first()
    )
    if user_id is None:
        return
    with transaction.atomic():
        lock_subscriber(user_id)
        subscription = _lock_active(team_id, subscription_id)
        if subscription is None:
            return
        try:
            expiry = validate_principal(
                team=subscription.team,
                user=subscription.created_by,
                principal=subscription.principal,
                renewed_at=subscription.renewed_at,
            )
            if subscription.expires_at <= timezone.now():
                deactivate(subscription)
                return
            service = MCPEventSubscriptions(
                team=subscription.team, user=subscription.created_by, principal=subscription.principal
            )
            filters = service.normalize_filters(subscription.arguments["filters"])
        except (APIException, ObjectDoesNotExist):
            logger.info("mcp_event_subscription_revoked", team_id=team_id, subscription_id=str(subscription.pk))
            deactivate(subscription)
            return
        subscription.arguments = {"project_id": team_id, "filters": filters}
        subscription.property_dependencies = MCPEventFilterAccessValidator.property_dependencies(
            filters, team=subscription.team
        )
        subscription.restricted_properties = restricted_event_property_names(
            team=subscription.team, user=subscription.created_by
        )
        if expiry is not None:
            subscription.expires_at = min(subscription.expires_at, expiry)
        subscription.hog_function_id = save_destination(subscription)
        subscription.save(
            update_fields=[
                "arguments",
                "property_dependencies",
                "restricted_properties",
                "expires_at",
                "hog_function",
                "updated_at",
            ]
        )


def revalidate_team_subscriptions(team_id: int) -> None:
    subscriptions = MCPEventSubscription.objects.for_team(team_id).filter(active=True)
    for reference in _references(subscriptions):
        revalidate_subscription(team_id, reference.id)


def _deactivate_all(subscriptions: Iterable[SubscriptionReference]) -> None:
    for reference in subscriptions:
        subscription = _lock_active(reference.team_id, reference.id)
        if subscription is not None:
            deactivate(subscription)


def _active_for_principal(principal: str) -> list[SubscriptionReference]:
    # Credentials span projects; each mutation below uses its own team scope.
    return _references(MCPEventSubscription.objects.unscoped().filter(principal=principal, active=True))


def revoke_personal_api_key(*, user_id: int, key_id: str) -> None:
    with transaction.atomic():
        lock_subscriber(user_id)
        _deactivate_all(_active_for_principal(f"personal_api_key:{user_id}:{key_id}"))


def recheck_personal_api_key(key: PersonalAPIKey) -> None:
    with transaction.atomic():
        lock_subscriber(key.user_id)
        for reference in _active_for_principal(f"personal_api_key:{key.user_id}:{key.pk}"):
            revalidate_subscription(reference.team_id, reference.id)


def revoke_user(*, user_id: int, organization_id: UUID | None = None) -> None:
    with transaction.atomic():
        lock_subscriber(user_id)
        subscriptions = MCPEventSubscription.objects.unscoped().filter(created_by_id=user_id, active=True)
        if organization_id is not None:
            subscriptions = subscriptions.filter(team__organization_id=organization_id)
        _deactivate_all(_references(subscriptions))


def revoke_user_in_organization(*, user_id: int, organization_id: UUID) -> None:
    revoke_user(user_id=user_id, organization_id=organization_id)


def revalidate_user_in_organization(*, user_id: int, organization_id: UUID) -> None:
    with transaction.atomic():
        lock_subscriber(user_id)
        subscriptions = MCPEventSubscription.objects.unscoped().filter(
            created_by_id=user_id, team__organization_id=organization_id, active=True
        )
        for reference in _references(subscriptions):
            revalidate_subscription(reference.team_id, reference.id)


def revoke_oauth_application(*, application_id: UUID, user_id: int | None = None) -> None:
    subscriptions = MCPEventSubscription.objects.unscoped().filter(
        principal__startswith="oauth:", principal__endswith=f":{application_id}", active=True
    )
    user_ids = (
        [user_id] if user_id is not None else sorted(subscriptions.values_list("created_by_id", flat=True).distinct())
    )
    for owner_id in user_ids:
        with transaction.atomic():
            lock_subscriber(owner_id)
            _deactivate_all(_active_for_principal(f"oauth:{owner_id}:{application_id}"))
