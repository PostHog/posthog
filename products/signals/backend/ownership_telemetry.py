import logging
from functools import partial

from django.db import transaction

import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Team

logger = logging.getLogger(__name__)


def capture_routing_change(
    *, team_id: int, action: str, outcome: str = "saved", changed: int = 0, skipped: int = 0
) -> None:
    def capture() -> None:
        try:
            team = Team.objects.select_related("organization").get(id=team_id)
            posthoganalytics.capture(
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
