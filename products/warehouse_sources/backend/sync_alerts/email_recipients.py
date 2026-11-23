"""Who a warehouse alert emails: the project members of its `email_project_members` setting, and the
users an email destination names.

Both follow the rule of the data pipeline error emails: active members of the project's organization
who can access the project and did not turn those emails off. One rule for all, so a member who opts
out of pipeline error emails also stops receiving these. Members who cannot view warehouse sources
are left out, as for the destination paused email, because these emails name sources and their errors.
"""

from collections.abc import Collection
from typing import Final
from uuid import UUID

import structlog

from posthog.models import Team
from posthog.models.organization import OrganizationMembership
from posthog.tasks.email import filter_members_by_external_data_source_access, get_members_to_notify_for_pipeline_error

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts_platform.backend.facade.api import get_configuration
from products.alerts_platform.backend.facade.contracts import SourceKind

logger = structlog.get_logger(__name__)

WAREHOUSE_ALERT_KINDS: Final = (SourceKind.WAREHOUSE_SOURCE.value, SourceKind.WAREHOUSE_DESTINATION.value)


def project_member_emails(*, team_id: int, configuration_id: UUID) -> list[str]:
    """The addresses a warehouse alert emails, or none when the alert does not email project members."""
    configuration = get_configuration(
        team_id=team_id, source_kinds=WAREHOUSE_ALERT_KINDS, configuration_id=configuration_id
    )
    if configuration is None or not configuration.source_config.get("email_project_members"):
        return []
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return []
    return sorted({membership.user.email for membership in _reachable_members(team) if membership.user.email})


def subscribers_with_warehouse_access(*, team_id: int, configuration_id: UUID, user_ids: Collection[int]) -> list[int]:
    """The users an email destination names who may still hear about a warehouse alert."""
    if not user_ids:
        return []
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return []
    members = get_members_to_notify_for_pipeline_error(team, user_ids=user_ids)
    return sorted({membership.user_id for membership in _members_with_warehouse_access(members, team)})


def _reachable_members(team: Team) -> list[OrganizationMembership]:
    return filter_members_by_external_data_source_access(get_members_to_notify_for_pipeline_error(team), team)


def _members_with_warehouse_access(
    memberships: list[OrganizationMembership], team: Team
) -> list[OrganizationMembership]:
    """`filter_members_by_external_data_source_access`, but failing closed: a destination names these users one by
    one, so a check that cannot run must not email them."""
    if not memberships:
        return memberships
    try:
        if not UserAccessControl(memberships[0].user, team).access_controls_supported:
            return memberships
        return [
            membership
            for membership in memberships
            if UserAccessControl(membership.user, team).check_access_level_for_resource(
                "external_data_source", "viewer"
            )
        ]
    except Exception:
        logger.exception("Warehouse access check failed, emailing none of the named users", team_id=team.id)
        return []
