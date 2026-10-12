import uuid

from celery import Task, shared_task
from structlog import get_logger

from posthog.api.capture import capture_batch_internal
from posthog.models.team.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.calculate_cohort import calculate_cohort_from_list
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.recipient_lists import (
    delete_recipient_lists_of_deleted_cohorts,
    existing_distinct_ids,
    fail_recipient_list_import,
    get_recipient_list,
    list_emails_by_distinct_id,
)

logger = get_logger(__name__)

EVENT_SOURCE = "workflows_recipient_list"
CAPTURE_MAX_RETRIES = 3
# Ingestion usually creates the people within seconds. The waits add up to about 25 minutes.
WAIT_MAX_ATTEMPTS = 8
WAIT_FIRST_DELAY_SECONDS = 15
WAIT_MAX_DELAY_SECONDS = 300


@shared_task(bind=True, ignore_result=True, queue=CeleryQueue.DEFAULT.value, max_retries=CAPTURE_MAX_RETRIES)
@skip_team_scope_audit
def capture_recipient_list_people(
    self, *, team_id: int, recipient_list_id: str, pending_distinct_ids: list[str] | None = None
) -> None:
    """Creates the people the list names who aren't in PostHog yet. The other columns stay on the list."""
    try:
        emails = list_emails_by_distinct_id(team_id, recipient_list_id)
        if pending_distinct_ids is None:
            new = set(emails) - existing_distinct_ids(team_id, list(emails))
        else:
            new = set(pending_distinct_ids)
        events = _set_events({d: email for d, email in emails.items() if d in new}, recipient_list_id)
        if not events:
            _schedule_fill(team_id, recipient_list_id, attempt=0, countdown=0)
            return
        team = Team.objects.get(id=team_id)
        result = capture_batch_internal(
            events=events, token=team.api_token, event_source=EVENT_SOURCE, process_person_profile=True
        )
    except Exception as error:
        logger.warning(
            "recipient_list_capture_failed", team_id=team_id, recipient_list_id=recipient_list_id, error=str(error)
        )
        _retry_or_fail(self, team_id, recipient_list_id, pending_distinct_ids)
        return
    if not result.succeeded():
        logger.warning(
            "recipient_list_capture_partial",
            team_id=team_id,
            recipient_list_id=recipient_list_id,
            dropped=len(result.dropped),
            retried=len(result.retried),
            unaccounted=len(result.unaccounted),
            error=result.error,
        )
    # Capture can ack part of a batch, and it ingests a resent acked event twice, so a retry sends only the rest.
    unacknowledged = {*result.retried, *result.unaccounted}
    if unacknowledged:
        retry = [str(event["distinct_id"]) for event in events if event["event_uuid"] in unacknowledged]
        _retry_or_fail(self, team_id, recipient_list_id, retry)
        return
    # A retry can't deliver a dropped event. The cohort import reports those people as unmatched.
    _schedule_fill(team_id, recipient_list_id, attempt=0)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def fill_recipient_list_cohort(*, team_id: int, recipient_list_id: str, attempt: int) -> None:
    """Waits until ingestion has created every person, then adds them all to the cohort."""
    last_attempt = attempt + 1 >= WAIT_MAX_ATTEMPTS
    try:
        recipient_list = get_recipient_list(team_id, recipient_list_id)
        if recipient_list is None:
            return
        distinct_ids = list(list_emails_by_distinct_id(team_id, recipient_list_id))
        found = existing_distinct_ids(team_id, distinct_ids)
    except Exception as error:
        logger.warning(
            "recipient_list_lookup_failed", team_id=team_id, recipient_list_id=recipient_list_id, error=str(error)
        )
        if last_attempt:
            fail_recipient_list_import(team_id, recipient_list_id)
        else:
            _schedule_fill(team_id, recipient_list_id, attempt=attempt + 1)
        return
    missing = len(distinct_ids) - len(found)
    if missing and not last_attempt:
        _schedule_fill(team_id, recipient_list_id, attempt=attempt + 1)
        return
    if missing:
        # The cohort import records the people it can't find, so the cohort shows the shortfall.
        logger.warning(
            "recipient_list_people_missing", team_id=team_id, recipient_list_id=recipient_list_id, missing=missing
        )
    calculate_cohort_from_list.delay(recipient_list.cohort_id, distinct_ids, team_id=team_id, id_type="distinct_id")


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def delete_expired_recipient_lists() -> None:
    deleted = delete_recipient_lists_of_deleted_cohorts()
    logger.info("recipient_lists_of_deleted_cohorts_deleted", deleted=deleted)


def _set_events(emails: dict[str, str], recipient_list_id: str) -> list[dict[str, object]]:
    return [
        {
            "event": "$set",
            "distinct_id": distinct_id,
            # The server's IP says nothing about where the person is.
            "properties": {"$set": {"email": email}, "$geoip_disable": True},
            # A stable uuid per person lets a retry find which events capture didn't acknowledge.
            "event_uuid": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"workflows-recipient-list/{recipient_list_id}/{distinct_id}")
            ),
        }
        for distinct_id, email in emails.items()
    ]


def _schedule_fill(team_id: int, recipient_list_id: str, *, attempt: int, countdown: int | None = None) -> None:
    fill_recipient_list_cohort.apply_async(
        kwargs={"team_id": team_id, "recipient_list_id": recipient_list_id, "attempt": attempt},
        countdown=min(WAIT_FIRST_DELAY_SECONDS * 2**attempt, WAIT_MAX_DELAY_SECONDS)
        if countdown is None
        else countdown,
    )


def _retry_or_fail(task: Task, team_id: int, recipient_list_id: str, pending_distinct_ids: list[str] | None) -> None:
    if task.request.retries < CAPTURE_MAX_RETRIES:
        raise task.retry(
            kwargs={
                "team_id": team_id,
                "recipient_list_id": recipient_list_id,
                "pending_distinct_ids": pending_distinct_ids,
            },
            countdown=30 * (task.request.retries + 1),
        )
    fail_recipient_list_import(team_id, recipient_list_id)
