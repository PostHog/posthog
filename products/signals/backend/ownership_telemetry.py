import logging
from functools import partial

from django.db import transaction

from posthog.event_usage import groups
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture

logger = logging.getLogger(__name__)


def capture_routing_change(
    *, team_id: int, action: str, outcome: str = "saved", changed: int = 0, skipped: int = 0
) -> None:
    def capture() -> None:
        try:
            team = Team.objects.select_related("organization").get(id=team_id)
            with ph_scoped_capture() as emit:
                emit(
                    distinct_id=str(team.uuid),
                    event="signals_routing_changed",
                    properties={
                        "team_id": team_id,
                        "action": action,
                        "outcome": outcome,
                        "changed": changed,
                        "skipped": skipped,
                    },
                    groups=groups(team.organization, team),
                )
        except Exception:
            logger.exception("Could not capture routing outcome", extra={"team_id": team_id, "action": action})

    transaction.on_commit(partial(capture), robust=True)
