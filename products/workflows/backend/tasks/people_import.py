import uuid

from celery import Task, shared_task
from structlog import get_logger

from posthog.api.capture import capture_batch_internal
from posthog.models.team.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.calculate_cohort import calculate_cohort_from_list
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.people_import import (
    StagedPerson,
    delete_people,
    existing_distinct_ids,
    fail_people_import,
    read_people,
)

logger = get_logger(__name__)

EVENT_SOURCE = "workflows_people_import"
CAPTURE_MAX_RETRIES = 3
# Ingestion usually creates the people within seconds. The waits add up to about 25 minutes.
WAIT_MAX_ATTEMPTS = 8
WAIT_FIRST_DELAY_SECONDS = 15
WAIT_MAX_DELAY_SECONDS = 300


@shared_task(bind=True, ignore_result=True, queue=CeleryQueue.DEFAULT.value, max_retries=CAPTURE_MAX_RETRIES)
@skip_team_scope_audit
def capture_people_import(self, *, team_id: int, cohort_id: int, storage_key: str) -> None:
    """Sends one $set event per row, so ingestion creates or updates each person with the row's columns."""
    try:
        people = read_people(storage_key)
        team = Team.objects.get(id=team_id)
        result = capture_batch_internal(
            events=_set_events(people, storage_key),
            token=team.api_token,
            event_source=EVENT_SOURCE,
            process_person_profile=True,
        )
    except Exception as error:
        logger.warning("people_import_capture_failed", team_id=team_id, cohort_id=cohort_id, error=str(error))
        _retry_or_fail(self, team_id, cohort_id, storage_key)
        return
    if not result.succeeded():
        logger.warning(
            "people_import_capture_partial",
            team_id=team_id,
            cohort_id=cohort_id,
            dropped=len(result.dropped),
            retried=len(result.retried),
            unaccounted=len(result.unaccounted),
            error=result.error,
        )
        _retry_or_fail(self, team_id, cohort_id, storage_key)
        return
    _schedule_fill(team_id, cohort_id, storage_key, attempt=0)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def fill_people_import_cohort(*, team_id: int, cohort_id: int, storage_key: str, attempt: int) -> None:
    """Waits until ingestion has created every person, then adds them all to the cohort."""
    last_attempt = attempt + 1 >= WAIT_MAX_ATTEMPTS
    try:
        distinct_ids = [person["distinct_id"] for person in read_people(storage_key)]
        found = existing_distinct_ids(team_id, distinct_ids)
    except Exception as error:
        logger.warning("people_import_lookup_failed", team_id=team_id, cohort_id=cohort_id, error=str(error))
        if last_attempt:
            fail_people_import(team_id, cohort_id, storage_key)
        else:
            _schedule_fill(team_id, cohort_id, storage_key, attempt=attempt + 1)
        return
    missing = len(distinct_ids) - len(found)
    if missing and not last_attempt:
        _schedule_fill(team_id, cohort_id, storage_key, attempt=attempt + 1)
        return
    if missing:
        # The cohort import records the people it can't find, so the cohort shows the shortfall.
        logger.warning("people_import_people_missing", team_id=team_id, cohort_id=cohort_id, missing=missing)
    calculate_cohort_from_list.delay(cohort_id, distinct_ids, team_id=team_id, id_type="distinct_id")
    delete_people(storage_key)


def _set_events(people: list[StagedPerson], storage_key: str) -> list[dict[str, object]]:
    return [
        {
            "event": "$set",
            "distinct_id": person["distinct_id"],
            "properties": {"$set": person["properties"]},
            # A retried task resends the same uuids, so capture drops the copies it already has.
            "event_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{storage_key}/{person['distinct_id']}")),
        }
        for person in people
    ]


def _schedule_fill(team_id: int, cohort_id: int, storage_key: str, *, attempt: int) -> None:
    fill_people_import_cohort.apply_async(
        kwargs={"team_id": team_id, "cohort_id": cohort_id, "storage_key": storage_key, "attempt": attempt},
        countdown=min(WAIT_FIRST_DELAY_SECONDS * 2**attempt, WAIT_MAX_DELAY_SECONDS),
    )


def _retry_or_fail(task: Task, team_id: int, cohort_id: int, storage_key: str) -> None:
    if task.request.retries < CAPTURE_MAX_RETRIES:
        raise task.retry(countdown=30 * (task.request.retries + 1))
    fail_people_import(team_id, cohort_id, storage_key)
