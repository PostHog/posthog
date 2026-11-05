"""Push each organization member's projects to hogtower, for team-scoped hoglake tokens.

hogtower mints a team credential's token from its own copy of which teams the credential's
owner can see. PostHog is not a live dependency of that mint, so PostHog pushes the copy:

- Every team the member can see, by both access-control systems (``visible_teams_for_user``),
  goes in at the member's level on warehouse objects: ``viewer`` is ``read``, ``editor`` and
  above are ``write``. A team where that level is ``none`` is left out.
- A member who has left the organization, or whose user is deactivated, is removed. hogtower
  then revokes every team credential the member owns.

Each push carries the member's whole team set and a version: the database clock, read before
the state is. hogtower keeps the highest version and answers 409 for an older one, which here
means a newer push already landed. Every change enqueues a push after it commits, so the last
push to run reads the change, and hogtower settles on it whatever order the pushes finish in.
A full push runs on a schedule as well, for anything a signal missed.
"""

from __future__ import annotations

import uuid
from typing import Literal

from django.conf import settings
from django.core.cache import cache
from django.db import connection

import structlog

from posthog.models import Organization, OrganizationMembership, User
from posthog.scopes import APIScopeObject
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl, visible_teams_for_user
from products.managed_warehouse.backend.metrics import record_counter
from products.managed_warehouse.backend.presentation import hogtower

logger = structlog.get_logger(__name__)

READ = "read"
WRITE = "write"
# The access-control resource whose level decides read or write on a team's namespace.
WAREHOUSE_RESOURCE: APIScopeObject = "warehouse_objects"
_READ_LEVELS = frozenset({"viewer"})
_WRITE_LEVELS = frozenset({"editor", "manager"})

# A push waiting in the queue covers every change made before it runs, so a second one is
# not enqueued. The key is cleared when the push starts, so a change made while it runs
# enqueues another. The timeout only bounds a key whose push never ran.
_PENDING_TIMEOUT_SECONDS = 600
# A short delay lets the changes of one request share one push.
_ENQUEUE_COUNTDOWN_SECONDS = 5

Outcome = Literal["pushed", "removed", "superseded", "no_warehouse", "rejected"]


class MemberTeamsPushError(Exception):
    """A push hogtower did not accept and may accept on retry (transport error, 5xx)."""


def is_enabled() -> bool:
    return bool(getattr(settings, "HOGTOWER_MEMBER_TEAMS_PUSH_ENABLED", False)) and hogtower.is_configured()


def member_teams(organization: Organization, user: User) -> dict[int, str]:
    """The teams ``user`` can see in ``organization``, each with ``read`` or ``write``."""
    access = UserAccessControl(user, organization_id=str(organization.id))
    visible = visible_teams_for_user(organization, access, UserPermissions(user)).values_list("id", flat=True)
    teams: dict[int, str] = {}
    for team_id, team_access in access.for_team_ids(list(visible)).items():
        resolved = team_access.access_level_for_resource(WAREHOUSE_RESOURCE)
        level = resolved.access_level if resolved else None
        if level in _WRITE_LEVELS:
            teams[team_id] = WRITE
        elif level in _READ_LEVELS:
            teams[team_id] = READ
    return teams


def _version() -> int:
    """Microseconds on the database clock: one clock for every web and worker host."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT (EXTRACT(EPOCH FROM clock_timestamp()) * 1000000)::bigint")
        row = cursor.fetchone()
    return int(row[0])


def _record(outcome: str) -> None:
    record_counter("managed_warehouse.member_teams.push", 1, {"outcome": outcome})


def push_member(organization_id: str, user_uuid: str) -> Outcome:
    """Push one member's teams to hogtower, or their removal when they are no longer a member.

    Raises :class:`MemberTeamsPushError` when a retry may succeed.
    """
    _clear_pending(_member_key(organization_id, user_uuid))
    version = _version()
    membership = (
        OrganizationMembership.objects.select_related("organization", "user")
        .filter(organization_id=organization_id, user__uuid=user_uuid, user__is_active=True)
        .first()
    )
    try:
        if membership is None:
            response = hogtower.remove_member(organization_id, user_uuid, version)
            done: Outcome = "removed"
        else:
            teams = member_teams(membership.organization, membership.user)
            response = hogtower.put_member_teams(organization_id, user_uuid, teams, version)
            done = "pushed"
    except Exception as e:
        _record("error")
        raise MemberTeamsPushError(f"hogtower unreachable: {type(e).__name__}") from e

    status = response.status_code
    if 200 <= status < 300:
        outcome: Outcome = done
    elif status == 409:
        outcome = "superseded"
    elif status == 404:
        # hogtower has no warehouse for this organization (yet, or any more).
        outcome = "no_warehouse"
    elif status == 400:
        # Malformed on our side: a retry sends the same thing, so log it and stop.
        logger.error(
            "managed_warehouse_member_teams_rejected",
            organization_id=organization_id,
            user_uuid=user_uuid,
            error=str(response.json())[:500],
        )
        outcome = "rejected"
    else:
        _record("error")
        raise MemberTeamsPushError(f"hogtower answered {status}")
    _record(outcome)
    logger.info(
        "managed_warehouse_member_teams_push",
        organization_id=organization_id,
        user_uuid=user_uuid,
        outcome=outcome,
        version=version,
    )
    return outcome


def organization_member_uuids(organization_id: str) -> list[str]:
    return [
        str(user_uuid)
        for user_uuid in OrganizationMembership.objects.filter(
            organization_id=organization_id, user__is_active=True
        ).values_list("user__uuid", flat=True)
    ]


def push_organization(organization_id: str) -> int:
    """Enqueue a push for every member of ``organization_id``; returns how many."""
    _clear_pending(_organization_key(organization_id))
    user_uuids = organization_member_uuids(organization_id)
    for user_uuid in user_uuids:
        enqueue_member_push(organization_id, user_uuid, countdown=0)
    return len(user_uuids)


def push_all() -> int:
    """Enqueue an organization push for every Trino warehouse hogtower manages; returns how many."""
    response = hogtower.list_warehouses()
    if not 200 <= response.status_code < 300:
        raise MemberTeamsPushError(f"hogtower answered {response.status_code} listing warehouses")
    body = response.json()
    warehouses = body.get("warehouses") if isinstance(body, dict) else None
    org_ids: set[uuid.UUID] = set()
    for warehouse in warehouses or []:
        # Only a Trino warehouse has a hoglake catalog, so only its members can hold team tokens.
        if not isinstance(warehouse, dict) or not warehouse.get("trino"):
            continue
        try:
            org_ids.add(uuid.UUID(str(warehouse.get("org_id"))))
        except ValueError:
            continue  # a warehouse whose id is not a PostHog organization
    existing = [str(org_id) for org_id in Organization.objects.filter(id__in=org_ids).values_list("id", flat=True)]
    for organization_id in existing:
        enqueue_organization_push(organization_id, countdown=0)
    return len(existing)


# --- enqueueing ---------------------------------------------------------------------------


def _member_key(organization_id: str, user_uuid: str) -> str:
    return f"managed_warehouse:member_teams:pending:{organization_id}:{user_uuid}"


def _organization_key(organization_id: str) -> str:
    return f"managed_warehouse:member_teams:pending:{organization_id}"


def _claim_pending(key: str) -> bool:
    """Whether to enqueue: False only when a push is already waiting. A cache failure enqueues."""
    try:
        return bool(cache.add(key, 1, timeout=_PENDING_TIMEOUT_SECONDS))
    except Exception:
        logger.warning("managed_warehouse_member_teams_cache_failure", exc_info=True)
        return True


def _clear_pending(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:
        logger.warning("managed_warehouse_member_teams_cache_failure", exc_info=True)


def enqueue_member_push(organization_id: str, user_uuid: str, *, countdown: int = _ENQUEUE_COUNTDOWN_SECONDS) -> None:
    from products.managed_warehouse.backend.tasks.tasks import push_warehouse_member_teams  # noqa: PLC0415

    if _claim_pending(_member_key(organization_id, user_uuid)):
        push_warehouse_member_teams.apply_async((organization_id, user_uuid), countdown=countdown)


def enqueue_organization_push(organization_id: str, *, countdown: int = _ENQUEUE_COUNTDOWN_SECONDS) -> None:
    from products.managed_warehouse.backend.tasks.tasks import push_warehouse_organization_member_teams  # noqa: PLC0415

    if _claim_pending(_organization_key(organization_id)):
        push_warehouse_organization_member_teams.apply_async((organization_id,), countdown=countdown)
