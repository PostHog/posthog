from django.db import InterfaceError, OperationalError

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.temporal.common.utils import retry_on_db_connection_drop

logger = structlog.get_logger(__name__)

BYTE_BOUNDED_EXTRACTION_FLAG = "warehouse-byte-bounded-extraction"


def is_byte_bounded_extraction_enabled(team_id: int, source_type: str) -> bool:
    """Gate for bounding extraction batches by accumulated bytes rather than a sampled row count.

    `source_type` rides along as a person property so the rollout widens one driver at a time
    from the flag itself. The drivers differ in what a smaller fetch costs them — a Postgres
    server cursor pays a round trip per fetch where MySQL reads from an unbuffered stream — so
    they are worth validating separately.

    Fails closed: any error means "off", which keeps the row-count batching.
    """
    try:
        team = retry_on_db_connection_drop(lambda: Team.objects.only("uuid", "organization_id").get(id=team_id))
    except Team.DoesNotExist:
        return False
    except (OperationalError, InterfaceError) as e:
        # retry_on_db_connection_drop already retried once; a second OperationalError/InterfaceError
        # here is the same app-DB connectivity blip class import_data_sync._handle_import_error
        # treats as non-reportable elsewhere (pooler drop, or this worker briefly out of file
        # descriptors) - not a bug in this gate, so it shouldn't page anyone.
        logger.warning(
            "is_byte_bounded_extraction_enabled: transient app-DB error, failing closed",
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
                BYTE_BOUNDED_EXTRACTION_FLAG,
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
