from django.db import InterfaceError, OperationalError

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.temporal.common.utils import retry_on_db_connection_drop

logger = structlog.get_logger(__name__)

KEYSET_FULL_LOAD_FLAG = "warehouse-postgres-keyset-full-load"


def is_keyset_full_load_enabled(team_id: int, source_type: str) -> bool:
    """Gate for reading a full load with keyset pages instead of one server cursor.

    The two reads see the table differently. A server cursor pins one snapshot for its whole life,
    so the load reflects a single instant; keyset pages read in autocommit, so each page sees a
    fresher one. Rows inserted or updated ahead of the cursor become visible, which a full refresh
    already tolerates. A primary key that *moves* does not: shifted forward past the cursor its row
    is read twice, shifted backward it is never read. That is why this is staged rather than flipped.

    `source_type` rides along as a person property so Postgres, Supabase, Neon and PlanetScale widen
    independently. They run the same code but not the same servers, and a managed provider's idle
    and lock timeouts are its own.

    Fails closed: any error means "off", which keeps the server cursor.
    """
    try:
        team = retry_on_db_connection_drop(lambda: Team.objects.only("uuid", "organization_id").get(id=team_id))
    except Team.DoesNotExist:
        return False
    except (OperationalError, InterfaceError) as e:
        # Already retried once. A second one is an app-DB connectivity blip, not a bug in this gate,
        # so it shouldn't page anyone — matching `is_byte_bounded_extraction_enabled`.
        logger.warning(
            "is_keyset_full_load_enabled: transient app-DB error, failing closed",
            error=str(e),
            exc_info=True,
        )
        return False
    except Exception as e:
        capture_exception(e)
        return False

    try:
        return bool(
            posthoganalytics.feature_enabled(
                KEYSET_FULL_LOAD_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                person_properties={"team_id": str(team.id), "source_type": source_type},
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
