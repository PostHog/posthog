from dataclasses import dataclass

from django.utils import timezone

import posthoganalytics
from temporalio import activity

from posthog.models import Team
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.code_workstreams.constants import (
    ACTIVITY_WINDOW,
    HOME_TAB_FLAG,
    MAX_TEAMS_PER_CYCLE,
)

CODE_ORIGIN_PRODUCTS = (
    Task.OriginProduct.USER_CREATED,
    Task.OriginProduct.SLACK,
    Task.OriginProduct.AUTOMATION,
)


@dataclass
class ListActiveCodeTeamsOutput:
    team_ids: list[int]
    truncated: bool


def _org_home_tab_enabled(organization_id: str) -> bool:
    # Evaluate locally and fail closed so a flag-service blip doesn't fan out work.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                HOME_TAB_FLAG,
                distinct_id=organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        activity.logger.warning(
            "code_workstreams_home_tab_flag_check_failed", organization_id=organization_id, error=str(e)
        )
        return False


@activity.defn
@close_db_connections
def list_active_code_teams(_: None = None) -> ListActiveCodeTeamsOutput:
    cutoff = timezone.now() - ACTIVITY_WINDOW
    team_ids = list(
        TaskRun.objects.filter(updated_at__gte=cutoff, task__origin_product__in=CODE_ORIGIN_PRODUCTS)
        .order_by("team_id")
        .values_list("team_id", flat=True)
        .distinct()
    )

    org_enabled: dict[str, bool] = {}
    enabled_team_ids: list[int] = []
    for team_id, organization_id in Team.objects.filter(id__in=team_ids).values_list("id", "organization_id"):
        org_id = str(organization_id)
        if org_id not in org_enabled:
            org_enabled[org_id] = _org_home_tab_enabled(org_id)
        if org_enabled[org_id]:
            enabled_team_ids.append(team_id)
    enabled_team_ids.sort()

    truncated = len(enabled_team_ids) > MAX_TEAMS_PER_CYCLE
    if truncated:
        activity.logger.warning(
            "code_workstreams_active_teams_truncated",
            total=len(enabled_team_ids),
            cap=MAX_TEAMS_PER_CYCLE,
        )
        enabled_team_ids = enabled_team_ids[:MAX_TEAMS_PER_CYCLE]
    return ListActiveCodeTeamsOutput(team_ids=enabled_team_ids, truncated=truncated)
