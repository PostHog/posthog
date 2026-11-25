"""Transactional push notifications: a push template made sendable over the API. Each one is backed by a workflow
that runs once per send, so sends get the workflow's metrics, run history and versions."""

import json
import time
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import structlog

from posthog.models.team import Team
from posthog.plugins.plugin_server_api import send_transactional_push as run_transactional_push_workflow

from products.messaging.backend.facade.contracts import (
    BatchTooLarge,
    ContentTooLarge,
    DeliveryUnavailable,
    EmailNotQueued,
    IdempotencyKeyInFlight,
    IdempotencyKeyReused,
    InvalidIdempotencyKey,
    InvalidRequest,
    PushBatchRecipient,
    PushBusy,
    QueuedEmail,
    QuotaLimited,
    TemplateNotSendable,
    TemplateNotTransactional,
    TransactionalEmailError,
    TransactionalPushPaused,
)
from products.messaging.backend.services.transactional_email import (
    BATCH_SHARED_MAX_BYTES,
    IDEMPOTENCY_KEY_PATTERN,
    TransactionalTemplate,
    check_sendable,
    encoded_size,
    queued_send,
    raise_refusal,
    refusal_code_of,
)
from products.messaging.backend.services.transactional_email_status import keyed_run_id
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_summary

logger = structlog.get_logger(__name__)

# The CDP service names a keyed send's run with this scope, so a batch result's ID matches the run's.
TRANSACTIONAL_PUSH_RUN_SCOPE = "transactional-push"
PUSH_BATCH_PARALLEL_REQUESTS = 10
# A recipient not reached by then is answered as unconfirmed, so a stalled CDP service can't hold the request.
PUSH_BATCH_TIMEOUT_SECONDS = 30
# A web process serves 8 requests at once, email sends included. Push waits on the CDP service in at most this many of
# them, so a CDP service that hangs on pushes leaves the rest to email.
PUSH_REQUESTS_PER_PROCESS = 3
# The same as BATCH_COPIED_BYTES_MAX, which the CDP service applies to an email batch.
PUSH_BATCH_COPIED_MAX_BYTES = 16 * 1024 * 1024
# These hold for every recipient, so a batch refused for all of them answers once instead of per recipient.
WHOLE_BATCH_REFUSALS = (QuotaLimited, TransactionalPushPaused, DeliveryUnavailable)

_push_requests = threading.BoundedSemaphore(PUSH_REQUESTS_PER_PROCESS)


@contextmanager
def _push_request() -> Iterator[None]:
    # Refuses instead of waiting, because a waiting request holds its thread too.
    if not _push_requests.acquire(blocking=False):
        raise PushBusy()
    try:
        yield
    finally:
        _push_requests.release()


PUSH_REFUSALS: dict[str, tuple[type[TransactionalEmailError], str]] = {
    "quota_limited": (QuotaLimited, "The project is over its quota for push notifications."),
    "idempotency_key_in_flight": (
        IdempotencyKeyInFlight,
        "A request with this idempotency key is still being processed. Retry in a few seconds.",
    ),
    "idempotency_key_reused": (
        IdempotencyKeyReused,
        "This idempotency key was already used for a different notification. Use a new key for a new notification.",
    ),
    "not_sendable": (
        TransactionalPushPaused,
        "This push notification's workflow isn't active or no longer only sends a push. Turn it back on, or "
        "save the template again to restore it.",
    ),
    "invalid_request": (
        InvalidRequest,
        "The push pipeline couldn't accept a field of this notification, so it wasn't sent. Check the distinct "
        "ID and message data, then send it again.",
    ),
}


def send_transactional_push(
    team: Team,
    template: TransactionalTemplate,
    *,
    distinct_id: str,
    message_data: dict[str, Any],
    idempotency_key: str | None = None,
    timeout: float = 10,
) -> QueuedEmail:
    """Queue one push notification from a transactional push template to every device of one person."""
    if idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise InvalidIdempotencyKey(
            "The Idempotency-Key header must be 1 to 255 visible ASCII characters, with no spaces."
        )
    hog_flow_id = _transactional_push_workflow_id(team.id, template)
    with _push_request():
        return _queue_push(
            team.id,
            hog_flow_id,
            distinct_id=distinct_id,
            message_data=message_data,
            idempotency_key=idempotency_key,
            timeout=timeout,
        )


def check_push_batch(message_data: dict[str, Any], recipients_data: Sequence[dict[str, Any]]) -> None:
    """Refuse a batch whose shared data, or all its copies of data together, are over the email batch's caps."""
    if encoded_size(message_data) > BATCH_SHARED_MAX_BYTES:
        raise ContentTooLarge(
            f"The `message_data` that a batch sends to every recipient can be at most "
            f"{BATCH_SHARED_MAX_BYTES // 1024} KiB. Send larger notifications one at a time."
        )
    copied = len(recipients_data) * _pipeline_size(message_data) + sum(map(_pipeline_size, recipients_data))
    if copied > PUSH_BATCH_COPIED_MAX_BYTES:
        raise BatchTooLarge()


def _pipeline_size(value: dict[str, Any]) -> int:
    """The bytes of the value as the CDP service would write it, which is how an email batch is measured."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(errors="backslashreplace"))


def send_transactional_push_batch(
    team: Team,
    template: TransactionalTemplate,
    recipients: Sequence[PushBatchRecipient],
    *,
    timeout: float = 10,
) -> tuple[QueuedEmail | EmailNotQueued, ...]:
    """Queue one push notification per recipient, in the order of `recipients`. A recipient the push pipeline refuses
    fails only its own result, unless every recipient was refused for the same reason that holds for the whole batch."""
    hog_flow_id = _transactional_push_workflow_id(team.id, template)
    deadline = time.monotonic() + PUSH_BATCH_TIMEOUT_SECONDS

    def queue(recipient: PushBatchRecipient) -> QueuedEmail | EmailNotQueued:
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeliveryUnavailable()
            return _queue_push(
                team.id,
                hog_flow_id,
                distinct_id=recipient.distinct_id,
                message_data=recipient.message_data,
                idempotency_key=recipient.idempotency_key,
                timeout=min(timeout, remaining),
            )
        except (TransactionalEmailError, DeliveryUnavailable) as e:
            message_id = keyed_run_id(team.id, TRANSACTIONAL_PUSH_RUN_SCOPE, recipient.idempotency_key)
            return EmailNotQueued(message_id=str(message_id), error=e)

    with _push_request(), ThreadPoolExecutor(max_workers=min(PUSH_BATCH_PARALLEL_REQUESTS, len(recipients))) as pool:
        results = tuple(pool.map(queue, recipients))
    errors = [result.error for result in results if isinstance(result, EmailNotQueued)]
    if len(errors) == len(results) and isinstance(errors[0], WHOLE_BATCH_REFUSALS):
        if all(type(error) is type(errors[0]) for error in errors):
            raise errors[0]
    return results


def _queue_push(
    team_id: int,
    hog_flow_id: UUID,
    *,
    distinct_id: str,
    message_data: dict[str, Any],
    idempotency_key: str | None,
    timeout: float,
) -> QueuedEmail:
    payload: dict[str, Any] = {"distinct_id": distinct_id, "variables": message_data}
    if idempotency_key is not None:
        # The CDP service holds the key, because only it knows whether the push was queued.
        payload["idempotency_key"] = idempotency_key
    try:
        response = run_transactional_push_workflow(team_id, str(hog_flow_id), payload, timeout=timeout)
    except Exception as e:
        logger.exception("transactional_push_queue_failed", team_id=team_id, hog_flow_id=str(hog_flow_id))
        raise DeliveryUnavailable() from e
    if response.status_code == 413:
        raise ContentTooLarge("The push notification is larger than PostHog can send. Make its message data smaller.")
    if response.status_code != 202:
        refusal_code = refusal_code_of(response)
        refusal = PUSH_REFUSALS.get(refusal_code or "")
        raise_refusal(
            refusal,
            log_event="transactional_push_queue_rejected",
            team_id=team_id,
            hog_flow_id=hog_flow_id,
            status_code=response.status_code,
            refusal_code=refusal_code,
        )
    try:
        return queued_send(response)
    except KeyError as e:
        # Accepted, but the answer names no run, so whether the push goes out isn't known.
        logger.exception("transactional_push_answer_unreadable", team_id=team_id, hog_flow_id=str(hog_flow_id))
        raise DeliveryUnavailable() from e


def _transactional_push_workflow_id(team_id: int, template: TransactionalTemplate) -> UUID:
    if template.type != "push":
        raise TemplateNotSendable("The template isn't a push template. Send it with the email API instead.")
    if not template.transactional_hog_flow_id:
        raise TemplateNotTransactional("The template isn't transactional. Make it transactional to send it.")
    # A category's type can change after the template was made transactional.
    check_sendable(
        team_id,
        template_type=template.type,
        content=template.content,
        message_category_id=template.message_category_id,
    )
    try:
        workflow = get_workflow_summary(team_id=team_id, workflow_id=str(template.transactional_hog_flow_id))
    except WorkflowNotFound as e:
        raise TransactionalPushPaused("This push notification's workflow no longer exists.") from e
    if workflow.status != "active":
        raise TransactionalPushPaused("This push notification's workflow isn't active. Turn it back on to send.")
    return template.transactional_hog_flow_id
