import posthoganalytics
from rest_framework import exceptions

from posthog.models.team import Team


def require_team_feature_flag(flag: str, team: Team) -> None:
    # Invisible while the flag is off, rather than 403: an endpoint that admits it exists gets built against.
    if not posthoganalytics.feature_enabled(
        flag,
        str(team.uuid),
        groups={"organization": str(team.organization_id)},
        group_properties={
            "organization": {
                "id": str(team.organization_id),
                "created_at": team.organization.created_at,
            }
        },
        send_feature_flag_events=False,
    ):
        raise exceptions.NotFound()
