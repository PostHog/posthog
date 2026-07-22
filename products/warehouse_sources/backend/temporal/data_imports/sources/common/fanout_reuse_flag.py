import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

FANOUT_WAREHOUSE_REUSE_FLAG = "warehouse-fanout-parent-reuse"


def is_fanout_warehouse_reuse_enabled(team_id: int) -> bool:
    """Gate for reading fan-out parents from the warehouse instead of the parent API.

    Fails closed: any error means "off", which keeps the legacy parent-API path.
    Lives in a leaf module (no deltalake/pyarrow) so API-process callers can import it
    without pulling the Delta reader stack into the web import graph.
    """
    try:
        team = Team.objects.get(id=team_id)
        return bool(
            posthoganalytics.feature_enabled(
                FANOUT_WAREHOUSE_REUSE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False
