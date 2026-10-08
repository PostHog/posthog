import uuid

from django.db.models import F
from django.utils import timezone

from celery import Task, shared_task
from structlog import get_logger

from posthog.api.capture import capture_batch_internal
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.calculate_cohort import calculate_cohort_from_list
from posthog.tasks.utils import CeleryQueue

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.services.people_import import delete_people, read_people

logger = get_logger(__name__)

EVENT_SOURCE = "workflows_people_import"
CAPTURE_MAX_RETRIES = 3
# Ingestion usually creates the people within seconds. The waits add up to about 25 minutes.
WAIT_MAX_ATTEMPTS = 8
WAIT_FIRST_DELAY_SECONDS = 15
WAIT_MAX_DELAY_SECONDS = 300
PERSON_LOOKUP_CHUNK_SIZE = 1000


@shared_task(bind=True, ignore_result=True, queue=CeleryQueue.DEFAULT.value, max_retries=CAPTURE_MAX_RETRIES)
@skip_team_scope_audit
def capture_people_import(self, *, team_id: int, cohort_id: int, storage_key: str) -> None:
    """Sends one $set event per row, so ingestion creates or updates each person with the row's columns."""
    people = read_people(storage_key)
    team = Team.objects.get(id=team_id)
    events = [
        {
            "event": "$set",
            "distinct_id": person["distinct_id"],
            "properties": {"$set": person["properties"]},
            # A retried task resends the same uuids, so capture drops the copies it already has.
            "event_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{storage_key}/{person['distinct_id']}")),
        }
        for person in people
    ]
    try:
        result = capture_batch_internal(
            events=events, token=team.api_token, event_source=EVENT_SOURCE, process_person_profile=True
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
    fill_people_import_cohort.apply_async(
        kwargs={"team_id": team_id, "cohort_id": cohort_id, "storage_key": storage_key, "attempt": 0},
        countdown=WAIT_FIRST_DELAY_SECONDS,
    )


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def fill_people_import_cohort(*, team_id: int, cohort_id: int, storage_key: str, attempt: int) -> None:
    """Waits until ingestion has created every person, then adds them all to the cohort."""
    distinct_ids = [person["distinct_id"] for person in read_people(storage_key)]
    missing = _missing_distinct_ids(team_id, distinct_ids)
    if missing and attempt + 1 < WAIT_MAX_ATTEMPTS:
        fill_people_import_cohort.apply_async(
            kwargs={"team_id": team_id, "cohort_id": cohort_id, "storage_key": storage_key, "attempt": attempt + 1},
            countdown=min(WAIT_FIRST_DELAY_SECONDS * 2 ** (attempt + 1), WAIT_MAX_DELAY_SECONDS),
        )
        return
    if missing:
        # The cohort import records the people it can't find, so the cohort shows the shortfall.
        logger.warning("people_import_people_missing", team_id=team_id, cohort_id=cohort_id, missing=len(missing))
    calculate_cohort_from_list.delay(cohort_id, distinct_ids, team_id=team_id, id_type="distinct_id")
    delete_people(storage_key)


def _missing_distinct_ids(team_id: int, distinct_ids: list[str]) -> list[str]:
    found: set[str] = set()
    for start in range(0, len(distinct_ids), PERSON_LOOKUP_CHUNK_SIZE):
        found.update(get_persons_mapped_by_distinct_id(team_id, distinct_ids[start : start + PERSON_LOOKUP_CHUNK_SIZE]))
    return [distinct_id for distinct_id in distinct_ids if distinct_id not in found]


def _retry_or_fail(task: Task, team_id: int, cohort_id: int, storage_key: str) -> None:
    if task.request.retries < CAPTURE_MAX_RETRIES:
        raise task.retry(countdown=30 * (task.request.retries + 1))
    _fail_import(team_id, cohort_id, storage_key)


def _fail_import(team_id: int, cohort_id: int, storage_key: str) -> None:
    Cohort.objects.filter(pk=cohort_id, team_id=team_id).update(
        is_calculating=False, errors_calculating=F("errors_calculating") + 1, last_error_at=timezone.now()
    )
    delete_people(storage_key)
