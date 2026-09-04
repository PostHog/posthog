import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.temporal.common.utils import retry_on_db_connection_drop

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
