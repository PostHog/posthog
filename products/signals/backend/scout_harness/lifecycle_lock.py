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

from django.db.models import Subquery

import structlog
from prometheus_client import Counter

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.user_permissions import UserPermissions

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.skill_loader import earliest_member_author_id, resolve_scout_acting_user_id
from products.skills.backend.models.skills import LLMSkill

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


class ScoutConfigNameTaken(Exception):
    """A skill rename would move a scout's config onto a name another config already holds."""


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


def resolve_scout_lifecycle_owner_id(team: Team, skill_name: str, config: SignalScoutConfig) -> int | None:
    """The person the lock protects: the acting user, also after the skill is archived.

    The delete flow archives the skill before it deletes the config. The acting-user lookup reads
    live versions only, so without this fallback the skill author loses the claim between the two
    steps and gets a refusal for their own scout. Only the most recent archive counts: an archive
    stamps one `updated_at` on every version it tombstones, and an older skill that once used the
    name must not give its author the claim.
    """
    if LLMSkill.objects.filter(team=team, name=skill_name, deleted=False).exists():
        return resolve_scout_acting_user_id(team, skill_name, config)
    archived = LLMSkill.objects.filter(team=team, name=skill_name, deleted=True)
    last_archive = archived.filter(updated_at=Subquery(archived.order_by("-updated_at").values("updated_at")[:1]))
    archived_author_id = earliest_member_author_id(team, last_archive)
    if archived_author_id is not None:
        return archived_author_id
    return resolve_scout_acting_user_id(team, skill_name, config)


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
    return resolve_scout_lifecycle_owner_id(team, skill_name, config) == user.pk


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


def _refuse_without_claim(
    *,
    team: Team,
    skill_name: str,
    config: SignalScoutConfig,
    user: User,
    authenticator: object,
    action: str,
    verb: str,
) -> None:
    """Raise `ScoutLifecycleLocked` for a locked scout unless the caller holds its claim."""
    if not config.lifecycle_locked:
        return
    if user_holds_scout_lifecycle_claim(team=team, skill_name=skill_name, config=config, user=user):
        return
    record_lifecycle_refusal(
        team=team,
        skill_name=skill_name,
        action=action,
        auth_kind=resolve_auth_kind(authenticator),
        user_id=user.pk,
    )
    raise ScoutLifecycleLocked(
        f"This scout is locked, so only the person its runs act as or a project admin can {verb} it."
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
    if config is None:
        return
    _refuse_without_claim(
        team=scoped_team,
        skill_name=skill_name,
        config=config,
        user=user,
        authenticator=authenticator,
        action="archive_skill",
        verb="delete",
    )


def rename_scout_with_skill(
    *,
    team: Team,
    skill_name: str,
    new_name: str,
    user: User | None,
    authenticator: object = None,
) -> None:
    """Move a scout's config to its skill's new name, behind the same gate as archiving.

    The config is keyed on the skill name. A rename that left it behind would orphan the config
    and stop the scout, so a rename removes a scout as surely as an archive does. Call it inside
    the rename transaction, before the skill rows move: the owner lookup reads the old name.

    A no-op for a skill that is not a scout. A caller with no acting user is a system path, so it
    is not gated.
    """
    scoped_team = canonical_team(team)
    configs = SignalScoutConfig.objects.for_team(scoped_team.id)
    config = configs.select_for_update().filter(skill_name=skill_name).first()
    if config is None:
        return
    if user is not None:
        _refuse_without_claim(
            team=scoped_team,
            skill_name=skill_name,
            config=config,
            user=user,
            authenticator=authenticator,
            action="rename_skill",
            verb="rename",
        )
    if configs.filter(skill_name=new_name).exists():
        raise ScoutConfigNameTaken(
            "Another scout config already uses this name. Delete that config or pick another name."
        )
    config.skill_name = new_name
    config.save(update_fields=["skill_name", "updated_at"])
