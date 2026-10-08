from typing import TYPE_CHECKING

from django.conf import settings

import posthoganalytics

if TYPE_CHECKING:
    from posthog.models.team import Team

WAREHOUSE_SUGGESTIONS_FEATURE_FLAG = "warehouse-suggestions"


def is_warehouse_suggestions_enabled(team: "Team") -> bool:
    if settings.DEBUG or settings.E2E_TESTING:
        return True
    return (
        posthoganalytics.feature_enabled(
            WAREHOUSE_SUGGESTIONS_FEATURE_FLAG,
            str(team.organization_id),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
        )
        is True
    )
