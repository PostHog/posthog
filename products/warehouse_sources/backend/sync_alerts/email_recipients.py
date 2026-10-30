"""Who a warehouse alert emails when its `email_project_members` setting is on.

The people the data pipeline error emails reach: active members of the project's organization who
can access the project and did not turn those emails off. One rule for both, so a member who opts
out of pipeline error emails also stops receiving these. Members who cannot view warehouse sources
are left out, as for the destination paused email, because these emails name sources and their errors.
"""

from typing import Final
from uuid import UUID

from posthog.models import Team
from posthog.tasks.email import filter_members_by_external_data_source_access, get_members_to_notify_for_pipeline_error

from products.alerts_platform.backend.facade.api import get_configuration
from products.alerts_platform.backend.facade.contracts import SourceKind

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
    return sorted(
        {
            membership.user.email
            for membership in filter_members_by_external_data_source_access(
                get_members_to_notify_for_pipeline_error(team), team
            )
            if membership.user.email
        }
    )
