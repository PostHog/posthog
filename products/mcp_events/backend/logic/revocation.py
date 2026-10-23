from collections.abc import Iterable
from datetime import datetime
from typing import Final
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
from pydantic import JsonValue
from rest_framework.exceptions import APIException

from posthog.models import Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.scopes import scopes_not_covered

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.mcp_events.backend.logic.destination import save_destination
from products.mcp_events.backend.logic.filters import MCPEventFilterAccessValidator, restricted_event_property_names
from products.mcp_events.backend.logic.subscriptions import deactivate
from products.mcp_events.backend.models import MCPEventSubscription

logger = structlog.get_logger(__name__)

REQUIRED_SCOPES: Final = ("mcp_event_subscription:write", "query:read")


def personal_api_key_principal(*, user_id: int, key_id: str) -> str:
    return f"personal_api_key:{user_id}:{key_id}"


def _lock_active(team_id: int, subscription_id: UUID) -> MCPEventSubscription | None:
    return (
        MCPEventSubscription.objects.for_team(team_id)
        .select_for_update()
        .select_related("team", "created_by")
        .filter(id=subscription_id, active=True)
        .first()
    )


def _still_allowed(subscription: MCPEventSubscription) -> bool:
    team: Team = subscription.team
    user: User = subscription.created_by
    if not user.is_active or not UserAccessControl(user, team).has_project_access:
        return False
    filters: dict[str, JsonValue] = subscription.arguments["filters"]
    try:
        MCPEventFilterAccessValidator.validate_actions(filters, team=team, user=user)
        MCPEventFilterAccessValidator.validate_snapshot(subscription.property_dependencies, team=team, user=user)
    except APIException:
        return False
    return True


def revalidate_subscription(team_id: int, subscription_id: UUID) -> None:
    with transaction.atomic():
        subscription = _lock_active(team_id, subscription_id)
        if subscription is None:
            return
        if not _still_allowed(subscription):
            logger.info("mcp_event_subscription_revoked", team_id=team_id, subscription_id=str(subscription.pk))
            deactivate(subscription)
            return
        restricted = restricted_event_property_names(team=subscription.team, user=subscription.created_by)
        if restricted != subscription.restricted_properties:
            subscription.restricted_properties = restricted
            subscription.hog_function_id = save_destination(subscription)
            subscription.save(update_fields=["restricted_properties", "hog_function", "updated_at"])


def revalidate_team_subscriptions(team_id: int) -> None:
    """Re-check every live subscription in the team after an access change, and stop the ones that lost access."""
    subscription_ids = list(
        MCPEventSubscription.objects.for_team(team_id)
        .filter(active=True, expires_at__gt=timezone.now())
        .values_list("id", flat=True)
    )
    for subscription_id in subscription_ids:
        revalidate_subscription(team_id, subscription_id)


def _deactivate_all(subscriptions: Iterable[tuple[int, UUID]]) -> None:
    for team_id, subscription_id in subscriptions:
        with transaction.atomic():
            subscription = _lock_active(team_id, subscription_id)
            if subscription is not None:
                deactivate(subscription)


def _active_for_principal(principal: str) -> list[tuple[int, UUID, datetime]]:
    # A credential spans projects, so the lookup is cross-team; each change then locks the row in its own team.
    return list(
        MCPEventSubscription.objects.unscoped()
        .filter(principal=principal, active=True)
        .values_list("team_id", "id", "renewed_at")
    )


def revoke_personal_api_key(*, user_id: int, key_id: str) -> None:
    rows = _active_for_principal(personal_api_key_principal(user_id=user_id, key_id=key_id))
    _deactivate_all((team_id, subscription_id) for team_id, subscription_id, _ in rows)


def recheck_personal_api_key(key: PersonalAPIKey) -> None:
    rows = _active_for_principal(personal_api_key_principal(user_id=key.user_id, key_id=key.pk))
    if not rows:
        return
    lacks_scopes = "*" not in (key.scopes or []) and bool(scopes_not_covered(key.scopes or [], REQUIRED_SCOPES))
    expired = key.expires_at is not None and key.expires_at <= timezone.now()
    revoked: list[tuple[int, UUID]] = []
    for team_id, subscription_id, renewed_at in rows:
        rolled = key.last_rolled_at is not None and key.last_rolled_at > renewed_at
        out_of_scope = bool(key.scoped_teams) and team_id not in (key.scoped_teams or [])
        if lacks_scopes or expired or rolled or out_of_scope or _outside_scoped_organizations(key, team_id):
            revoked.append((team_id, subscription_id))
        elif key.expires_at is not None:
            MCPEventSubscription.objects.for_team(team_id).filter(
                id=subscription_id, expires_at__gt=key.expires_at
            ).update(expires_at=key.expires_at)
    _deactivate_all(revoked)


def _outside_scoped_organizations(key: PersonalAPIKey, team_id: int) -> bool:
    if not key.scoped_organizations:
        return False
    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    return str(organization_id) not in key.scoped_organizations


def organization_team_ids(organization_id: UUID) -> list[int]:
    return list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))


def revoke_user_in_organization(*, user_id: int, organization_id: UUID) -> None:
    rows: list[tuple[int, UUID]] = []
    for team_id in organization_team_ids(organization_id):
        rows.extend(
            (team_id, subscription_id)
            for subscription_id in MCPEventSubscription.objects.for_team(team_id)
            .filter(created_by_id=user_id, active=True)
            .values_list("id", flat=True)
        )
    _deactivate_all(rows)
