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
def capture_people_import(
    self, *, team_id: int, cohort_id: int, storage_key: str, pending_distinct_ids: list[str] | None = None
) -> None:
    """Sends one $set event per row, so ingestion creates or updates each person with the row's columns."""
    try:
        people = read_people(storage_key)
        if pending_distinct_ids is not None:
            pending = set(pending_distinct_ids)
            people = [person for person in people if person["distinct_id"] in pending]
        team = Team.objects.get(id=team_id)
        events = _set_events(people, storage_key)
        result = capture_batch_internal(
            events=events, token=team.api_token, event_source=EVENT_SOURCE, process_person_profile=True
        )
    except Exception as error:
        logger.warning("people_import_capture_failed", team_id=team_id, cohort_id=cohort_id, error=str(error))
        _retry_or_fail(self, team_id, cohort_id, storage_key, pending_distinct_ids)
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
    # Capture can ack part of a batch, and it ingests a resent acked event twice, so a retry sends only the rest.
    unacknowledged = {*result.retried, *result.unaccounted}
    if unacknowledged:
        retry = [str(event["distinct_id"]) for event in events if event["event_uuid"] in unacknowledged]
        everything_again = pending_distinct_ids is None and len(retry) == len(events)
        _retry_or_fail(self, team_id, cohort_id, storage_key, None if everything_again else retry)
        return
    # A retry can't deliver a dropped event. The cohort import reports those people as unmatched.
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
            # A stable uuid per person lets a retry find which events capture didn't acknowledge.
            "event_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{storage_key}/{person['distinct_id']}")),
        }
        for person in people
    ]


def _schedule_fill(team_id: int, cohort_id: int, storage_key: str, *, attempt: int) -> None:
    fill_people_import_cohort.apply_async(
        kwargs={"team_id": team_id, "cohort_id": cohort_id, "storage_key": storage_key, "attempt": attempt},
        countdown=min(WAIT_FIRST_DELAY_SECONDS * 2**attempt, WAIT_MAX_DELAY_SECONDS),
    )


def _retry_or_fail(
    task: Task, team_id: int, cohort_id: int, storage_key: str, pending_distinct_ids: list[str] | None
) -> None:
    if task.request.retries < CAPTURE_MAX_RETRIES:
        raise task.retry(
            kwargs={
                "team_id": team_id,
                "cohort_id": cohort_id,
                "storage_key": storage_key,
                "pending_distinct_ids": pending_distinct_ids,
            },
            countdown=30 * (task.request.retries + 1),
        )
    fail_people_import(team_id, cohort_id, storage_key)
