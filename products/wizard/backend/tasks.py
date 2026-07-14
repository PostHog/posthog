import logging
from typing import Any

from celery import shared_task
from celery.app.task import Task

from posthog.celery_queues import CeleryQueue

from products.event_definitions.backend.facade.api import create_placeholder_event_definitions
from products.event_definitions.backend.facade.contracts import PlaceholderEventDefinition
from products.wizard.backend.facade.enums import RunPhase
from products.wizard.backend.models import WizardSession

logger = logging.getLogger(__name__)

MAX_PLANNED_EVENT_DEFINITIONS = 50
MAX_PLANNED_EVENT_CANDIDATES = 500
MAX_EVENT_NAME_LENGTH = 400


def _planned_event_definitions(event_plan: dict[str, Any] | None) -> list[PlaceholderEventDefinition]:
    events = event_plan.get("events") if isinstance(event_plan, dict) else None
    if not isinstance(events, list):
        return []

    definitions: list[PlaceholderEventDefinition] = []
    seen_names: set[str] = set()
    for planned_event in events[:MAX_PLANNED_EVENT_CANDIDATES]:
        if not isinstance(planned_event, dict):
            continue

        raw_name = planned_event.get("name")
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip().replace("\x00", "\ufffd")
        if not name or name.startswith("$") or len(name) > MAX_EVENT_NAME_LENGTH or name in seen_names:
            continue

        description = planned_event.get("description")
        definitions.append(
            PlaceholderEventDefinition(
                name=name,
                description=description.replace("\x00", "\ufffd") if isinstance(description, str) else None,
            )
        )
        seen_names.add(name)
        if len(definitions) == MAX_PLANNED_EVENT_DEFINITIONS:
            break

    return definitions


@shared_task(
    bind=True,
    ignore_result=True,
    max_retries=5,
    queue=CeleryQueue.DEFAULT.value,
)
def sync_wizard_event_definitions(self: Task, team_id: int, session_id: str) -> None:
    try:
        session = WizardSession.objects.for_team(team_id).filter(session_id=session_id).first()
        if session is None or session.run_phase != RunPhase.COMPLETED.value:
            return

        create_placeholder_event_definitions(
            team_id=team_id,
            definitions=_planned_event_definitions(session.event_plan),
        )
    except Exception as error:
        countdown = min(2**self.request.retries, 60)
        logger.warning(
            "Retrying wizard event definition sync",
            extra={"team_id": team_id, "session_id": session_id, "retry": self.request.retries},
        )
        raise self.retry(exc=error, countdown=countdown)
