from datetime import datetime
from typing import Final

from django.db import connection
from django.utils import timezone

from rest_framework.exceptions import PermissionDenied

from posthog.models import PersonalAPIKey, Team, User
from posthog.models.oauth import OAuthAccessToken
from posthog.scopes import scopes_not_covered

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.mcp_events.backend.facade.contracts import MCPEventCredential

REQUIRED_SCOPES: Final = ("mcp_event_subscription:write", "query:read")
SUBSCRIBER_LOCK_NAMESPACE: Final = 0x4D435055


def lock_subscriber(user_id: int) -> None:
    # Admission and revocation share this lock even when no subscription row exists yet.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [SUBSCRIBER_LOCK_NAMESPACE, user_id])


def _covers_project(credential: PersonalAPIKey | OAuthAccessToken, team: Team) -> bool:
    scopes = (credential.scopes or []) if isinstance(credential, PersonalAPIKey) else credential.scope.split()
    return (
        ("*" in scopes or not scopes_not_covered(scopes, REQUIRED_SCOPES))
        and (not credential.scoped_teams or team.pk in credential.scoped_teams)
        and (not credential.scoped_organizations or str(team.organization_id) in credential.scoped_organizations)
    )


def validate_principal(
    *,
    team: Team,
    user: User,
    principal: str,
    credential: MCPEventCredential | None = None,
    renewed_at: datetime | None = None,
) -> datetime | None:
    if (
        not user.is_active
        or not user.organization_memberships.filter(organization_id=team.organization_id).exists()
        or not UserAccessControl(user, team).has_project_access
    ):
        raise PermissionDenied("This account cannot access the subscription project.")
    kind, owner, identifier = principal.split(":", 2)
    if owner != str(user.pk):
        raise PermissionDenied("This credential belongs to another account.")
    now = timezone.now()
    if kind == "personal_api_key":
        key = PersonalAPIKey.objects.filter(pk=identifier, user_id=user.pk).first()
        if (
            key is None
            or key.is_expired
            or not _covers_project(key, team)
            or credential is not None
            and (key.pk != credential.id or key.last_rolled_at != credential.last_rolled_at)
            or renewed_at is not None
            and key.last_rolled_at is not None
            and key.last_rolled_at > renewed_at
        ):
            raise PermissionDenied("The subscription credential is no longer valid.")
        return key.expires_at
    if kind == "oauth":
        tokens = OAuthAccessToken.objects.filter(user_id=user.pk, application_id=identifier, expires__gt=now)
        if credential is not None:
            tokens = tokens.filter(pk=credential.id)
        expiries = [token.expires for token in tokens if _covers_project(token, team)]
        if expiries:
            return max(expiries)
    raise PermissionDenied("The subscription credential is no longer valid.")
