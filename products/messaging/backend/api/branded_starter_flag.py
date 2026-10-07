import posthoganalytics
from rest_framework import exceptions

from posthog.models import Team, User

BRANDED_STARTER_FLAG = "email-branded-starter"


def require_branded_starter(user: User, team: Team) -> None:
    try:
        enabled = posthoganalytics.feature_enabled(
            BRANDED_STARTER_FLAG,
            str(user.distinct_id),
            groups={"organization": str(team.organization_id), "project": str(team.uuid)},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        enabled = False
    if enabled is not True:
        raise exceptions.NotFound()
