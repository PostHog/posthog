import django.db

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.temporal.common.utils import retry_on_db_connection_drop

FANOUT_WAREHOUSE_REUSE_FLAG = "warehouse-fanout-parent-reuse"


def is_fanout_warehouse_reuse_enabled(team_id: int) -> bool:
    """Gate for reading fan-out parents from the warehouse instead of the parent API.

    Fails closed: any error means "off", which keeps the legacy parent-API path.
    Lives in a leaf module (no deltalake/pyarrow) so callers can import it without pulling
    the Delta reader stack into their import graph.
    """
    try:
        team = retry_on_db_connection_drop(lambda: Team.objects.only("uuid", "organization_id").get(id=team_id))
    except Team.DoesNotExist:
        return False
    except (django.db.OperationalError, django.db.InterfaceError) as e:
        # retry_on_db_connection_drop already retried once; a second failure is a genuinely
        # degraded DB, not a bug here (see repartition_controller.py's _is_flag_enabled).
        capture_exception(e)
        return False
    except Exception as e:
        capture_exception(e)
        return False

    try:
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
