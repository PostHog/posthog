"""The per-scout lifecycle lock: who may pause, silence, or remove one scout.

`signal_scout:write` is project-wide, and an unattended agent holding a member's credential
carries it exactly as a person does. That is the right bar for tuning a schedule, and too weak
for the lifecycle: one bulk pause silences a project's whole fleet, and a resume has to pass the
enabled-scout maximum that a pause does not, so the fleet does not come back in one step.

A scout that opts in (`SignalScoutConfig.lifecycle_locked`) therefore asks for the same claim
`write_scopes` asks for, resolved the same way: the person the runs act as, or a project admin.

This module holds the parts two products share. The signals config API reads them for its own
write paths, and the skills product reads them through the signals facade, because archiving a
scout's skill stops the scout just as surely as deleting its config does.
"""

from collections.abc import Mapping

import structlog
from prometheus_client import Counter

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.user_permissions import UserPermissions

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.skill_loader import resolve_scout_acting_user_id

logger = structlog.get_logger(__name__)

LIFECYCLE_WRITES_REFUSED = Counter(
    "signals_scout_lifecycle_writes_refused",
    "Writes to a locked scout's lifecycle refused by the owner gate",
    labelnames=["action", "auth_kind"],
)

# The fields the lock protects, alongside removing the scout. `enabled` stops the scout running
# and `emit` stops it reporting, so either one silences it.
LOCK_PROTECTED_FIELDS = ("enabled", "emit", "lifecycle_locked")


class ScoutLifecycleLocked(Exception):
    """A locked scout refused a lifecycle write. Carries the message to show the caller.

    A plain exception rather than a DRF error, because the skills product raises it from an MCP
    tool as well as from an endpoint, and each entrypoint renders it its own way.
    """


def resolve_auth_kind(authenticator: object) -> str:
    """How a caller authenticated, as a bounded metric label.

    A refusal matters most when it comes from an unattended agent holding a member's credential,
    so the counter has to separate a token from a person at a browser.
    """
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        return "oauth"
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        return "personal_api_key"
    if isinstance(authenticator, SessionAuthentication):
        return "session"
    return "other"


def canonical_team(team: Team) -> Team:
    """The team a scout config lives under. A child environment resolves to its parent."""
    return team.parent_team or team


def lock_protected_changes(requested: object, *, config: SignalScoutConfig | None) -> list[str]:
    """Which protected fields a write body would actually change on an existing scout.

    Only a change counts: clients resend whole config objects, so a body repeating the current
    `enabled` must not be refused as a pause. A malformed value counts as an attempt to change the
    field — the serializer rejects it afterwards, and the gate must not be the thing that lets it
    through. Nothing is protected while the scout is unlocked, except the lock itself: turning it
    on decides who may turn it off, so it asks for the same claim from the start.
    """
    if config is None or not isinstance(requested, Mapping):
        return []
    changed = [
        field for field in LOCK_PROTECTED_FIELDS if field in requested and requested[field] != getattr(config, field)
    ]
    if not changed:
        return []
    return changed if config.lifecycle_locked or "lifecycle_locked" in changed else []


def user_holds_scout_lifecycle_claim(
    *,
    team: Team,
    skill_name: str,
    config: SignalScoutConfig,
    user: User,
) -> bool:
    """Whether this person may move a locked scout's lifecycle.

    The acting user comes from `resolve_scout_acting_user_id`, never `LLMSkillOwner`: any skill
    editor can rewrite that owner list, so reading it here would let an editor appoint themselves
    and pass the gate.
    """
    level = UserPermissions(user=user, team=team).current_team.effective_membership_level
    if level is not None and level >= OrganizationMembership.Level.ADMIN:
        return True
    return resolve_scout_acting_user_id(team, skill_name, config) == user.pk


def record_lifecycle_refusal(
    *,
    team: Team,
    skill_name: str,
    action: str,
    auth_kind: str,
    user_id: int | None,
    fields: list[str] | None = None,
) -> None:
    """Count and log a refused lifecycle write, so the rate is visible per action and auth kind."""
    LIFECYCLE_WRITES_REFUSED.labels(action=action, auth_kind=auth_kind).inc()
    logger.warning(
        "signals_scout: locked lifecycle write refused",
        team_id=team.id,
        skill_name=skill_name,
        action=action,
        fields=sorted(fields or []),
        user_id=user_id,
        auth_kind=auth_kind,
    )


def assert_can_archive_scout_skill(
    *,
    team: Team,
    skill_name: str,
    user: User,
    authenticator: object = None,
) -> None:
    """Refuse to archive the skill behind a locked scout unless the caller owns it.

    Archiving is how the product removes a custom scout: the delete flow tombstones the skill
    first, and only then deletes the config. So a lock that guarded the config alone would still
    let a non-owner stop a locked scout for good, and there is no way to unarchive a skill.

    A no-op for a skill that is not a scout, or whose scout never opted in.
    """
    scoped_team = canonical_team(team)
    config = SignalScoutConfig.objects.for_team(scoped_team.id).filter(skill_name=skill_name).first()
    if config is None or not config.lifecycle_locked:
        return
    if user_holds_scout_lifecycle_claim(team=scoped_team, skill_name=skill_name, config=config, user=user):
        return
    record_lifecycle_refusal(
        team=scoped_team,
        skill_name=skill_name,
        action="archive_skill",
        auth_kind=resolve_auth_kind(authenticator),
        user_id=user.pk,
    )
    raise ScoutLifecycleLocked(
        "This scout is locked, so only the person its runs act as or a project admin can delete it."
    )
