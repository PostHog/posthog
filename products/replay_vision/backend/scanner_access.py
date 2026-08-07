"""Scanner-level RBAC helper shared by the vision-action engine (run-time creator gate) and the
API serializer (write-time editor gate). Lives outside `temporal/` so the API can import it without
pulling the temporal package onto its import path.

Also home to the two queries that read observations back across scanner origins, so `all_origins`
appears once instead of at every reading call site."""

import uuid
from typing import TYPE_CHECKING

from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControl

from products.replay_vision.backend.models.replay_scanner import ReplayScanner

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from posthog.models.user import User


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError):
        return False
    return True


def scanners_for_reading_observations(team_id: int) -> "QuerySet[ReplayScanner]":
    """Every scanner whose observations can be read, inline scans included.

    The one place `all_origins` belongs on a read path. `ReplayScanner.objects` is configured-only so
    that a new call site can't leak inline scans into a list or a sweep, which leaves exactly one way to
    get this wrong: a path that reads results and forgets to opt back in, silently hiding an inline
    scan's answers. Go through this instead of naming the manager, and still apply the caller's own
    access-level filter on top — this widens origin, not RBAC.
    """
    return ReplayScanner.all_origins.filter(team_id=team_id)


def scanner_for_reading_observations(team_id: int, scanner_id: "str | uuid.UUID") -> ReplayScanner | None:
    """Resolve one scanner by id for reading its observations. See `scanners_for_reading_observations`."""
    if not is_uuid(str(scanner_id)):
        return None
    return scanners_for_reading_observations(team_id).filter(id=scanner_id).first()


def readable_scanner_ids(user: "User", team: Team, scanner_ids: list[str]) -> list[str]:
    """Restrict an action's bound scanner ids to the ones the given user may actually read.

    A vision action's scanner binding is user-supplied, so without this a user could point an action
    at a same-team scanner they lack `replay_scanner` viewer access to and receive its recording-derived
    reasoning and outcome in the synthesized report. The engine applies it to the action's creator on
    every run; the serializer applies it to the requesting user whenever the targeting changes. Mirrors
    the scanner-access gate `max_tools` applies on interactive reads (object-level access control; note
    the underlying queryset filter is a no-op for orgs without the access-control feature, where no
    per-scanner restriction exists anyway).
    """
    # Drop non-UUID ids before querying: `selection.scanner_ids` is a user-supplied CharField list, and a
    # malformed value would raise ValidationError inside the Temporal activity on every run (a permanent
    # retry loop). Mirrors the UUID pre-validation in `max_tools._resolve_scanner_scope`.
    valid_ids = [scanner_id for scanner_id in scanner_ids if is_uuid(scanner_id)]
    if not valid_ids:
        return []
    readable = UserAccessControl(user=user, team=team).filter_queryset_by_access_level(
        ReplayScanner.objects.filter(team_id=team.id, id__in=valid_ids)
    )
    return [str(scanner_id) for scanner_id in readable.values_list("id", flat=True)]
