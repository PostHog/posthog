import uuid
from uuid import UUID

from celery import Task, shared_task
from structlog import get_logger

from posthog.api.capture import capture_batch_internal
from posthog.models.team.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.calculate_cohort import calculate_cohort_from_list
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.people_import import (
    STALLED_IMPORT_AFTER,
    StagedPerson,
    StallCheck,
    check_stalled_people_import,
    existing_distinct_ids,
    fail_people_import,
    finish_people_import_batch,
    finish_people_import_rows,
    mark_people_import_populating,
    people_import_batch_rows,
    people_import_fills_cohort,
    people_import_part,
    read_people,
    wait_for_other_parts,
)

logger = get_logger(__name__)

EVENT_SOURCE = "workflows_people_import"
CAPTURE_MAX_RETRIES = 3
# Ingestion usually creates the people within seconds. The waits add up to about 25 minutes.
WAIT_MAX_ATTEMPTS = 8
WAIT_FIRST_DELAY_SECONDS = 15
WAIT_MAX_DELAY_SECONDS = 300
STALL_CHECK_MAX_RETRIES = 5
STALL_CHECK_RETRY_SECONDS = 60


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
        if not people_import_fills_cohort(storage_key):
            finish_people_import_rows(team_id, storage_key)
            return
        distinct_ids = [person["distinct_id"] for person in read_people(storage_key)]
        found = existing_distinct_ids(team_id, distinct_ids)
        part = people_import_part(storage_key)
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
    try:
        if part is None:
            _populate(team_id, cohort_id, [storage_key], distinct_ids)
        elif wait_for_other_parts(team_id, storage_key):
            fill_people_import_batch.delay(team_id=team_id, batch_id=str(part[0]))
    except Exception as error:
        # Both steps can run again: a part counts once, and a cohort ignores people it already has.
        logger.warning("people_import_fill_start_failed", team_id=team_id, cohort_id=cohort_id, error=str(error))
        if last_attempt:
            fail_people_import(team_id, cohort_id, storage_key)
        else:
            _schedule_fill(team_id, cohort_id, storage_key, attempt=attempt + 1)


@shared_task(bind=True, ignore_result=True, queue=CeleryQueue.DEFAULT.value, max_retries=STALL_CHECK_MAX_RETRIES)
@skip_team_scope_audit
def fill_people_import_batch(self: Task, *, team_id: int, batch_id: str) -> None:
    """Fills the cohort with every part of a batch, once the people of all of them exist."""
    try:
        batch = people_import_batch_rows(team_id, UUID(batch_id))
        if batch is None:
            # A part failed, and the stall check of each other part ends it.
            return
        cohort_id, storage_keys = batch
        distinct_ids = list(dict.fromkeys(person["distinct_id"] for key in storage_keys for person in read_people(key)))
        if not distinct_ids:
            finish_people_import_batch(team_id, UUID(batch_id))
            return
        _populate(team_id, cohort_id, storage_keys, distinct_ids, batch_id=batch_id)
    except Exception as error:
        # The parts keep their rows. Once these retries run out, a part's stall check starts the fill again.
        logger.warning("people_import_batch_fill_failed", team_id=team_id, batch_id=batch_id, error=str(error))
        raise self.retry(countdown=STALL_CHECK_RETRY_SECONDS * (self.request.retries + 1))


def _populate(
    team_id: int, cohort_id: int, storage_keys: list[str], distinct_ids: list[str], *, batch_id: str | None = None
) -> None:
    for storage_key in storage_keys:
        mark_people_import_populating(storage_key)
    # The rows stay until the population succeeds, so the stall check can tell a lost population from a running one.
    calculate_cohort_from_list.apply_async(
        args=[cohort_id, distinct_ids],
        kwargs={"team_id": team_id, "id_type": "distinct_id"},
        link=finish_people_import.si(team_id=team_id, storage_keys=storage_keys, batch_id=batch_id),
    )


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def finish_people_import(*, team_id: int, storage_keys: list[str], batch_id: str | None = None) -> None:
    """Deletes an import's stored rows once its cohort population succeeded."""
    for storage_key in storage_keys:
        finish_people_import_rows(team_id, storage_key)
    if batch_id is not None:
        finish_people_import_batch(team_id, UUID(batch_id))


@shared_task(bind=True, ignore_result=True, queue=CeleryQueue.DEFAULT.value, max_retries=STALL_CHECK_MAX_RETRIES)
@skip_team_scope_audit
def fail_people_import_if_stalled(
    self: Task, *, team_id: int, cohort_id: int, storage_key: str, check: int = 0
) -> None:
    """Ends an import that should have finished, or dispatches it again, or checks again while its cohort fills."""
    try:
        outcome = check_stalled_people_import(team_id, cohort_id, storage_key, check=check)
    except Exception as error:
        # Nothing else checks this import again, so a storage or database blip must not end the checks.
        logger.warning("people_import_stall_check_failed", team_id=team_id, cohort_id=cohort_id, error=str(error))
        if self.request.retries < STALL_CHECK_MAX_RETRIES:
            raise self.retry(countdown=STALL_CHECK_RETRY_SECONDS * (self.request.retries + 1))
        # Out of quick retries, the next hourly check takes over, and the last one deletes the rows.
        outcome = StallCheck.WAITING
    if outcome == StallCheck.FAILED:
        logger.warning("people_import_stalled", team_id=team_id, cohort_id=cohort_id)
    elif outcome == StallCheck.WAITING:
        next_check = {"team_id": team_id, "cohort_id": cohort_id, "storage_key": storage_key, "check": check + 1}
        try:
            fail_people_import_if_stalled.apply_async(
                kwargs=next_check, countdown=int(STALLED_IMPORT_AFTER.total_seconds())
            )
        except Exception as error:
            logger.warning("people_import_stall_check_schedule_failed", team_id=team_id, error=str(error))
            raise self.retry(kwargs=next_check, countdown=STALL_CHECK_RETRY_SECONDS)


def _set_events(people: list[StagedPerson], storage_key: str) -> list[dict[str, object]]:
    return [
        {
            "event": "$set",
            "distinct_id": person["distinct_id"],
            # The server's IP says nothing about where the person is.
            "properties": {
                "$set_once" if person.get("fill_only") else "$set": person["properties"],
                "$geoip_disable": True,
            },
            # A stable uuid per person lets a retry find which events capture didn't acknowledge.
            "event_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{storage_key}/{person['distinct_id']}")),
        }
        for person in people
    ]


def schedule_people_import_fill(*, team_id: int, cohort_id: int, storage_key: str) -> None:
    """Fill the cohort once ingestion has the people, for an import whose events another import sends."""
    _schedule_fill(team_id, cohort_id, storage_key, attempt=0)


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
