"""Cancel or move a transactional email before a worker claims it. The CDP service holds the waiting job."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.utils.dateparse import parse_datetime

import requests
import structlog

from posthog.plugins.plugin_server_api import cancel_scheduled_email, reschedule_scheduled_email

from products.messaging.backend.facade.contracts import (
    AlreadySending,
    DeliveryUnavailable,
    EmailCanceled,
    EmailNotFound,
    EmailSendStatus,
    RescheduleTooFar,
)
from products.messaging.backend.services.transactional_email_status import get_email_status, queued_at

logger = structlog.get_logger(__name__)

_CANCELED_MARK_TTL = timedelta(hours=1)


def cancel_email(team_id: int, message_id: UUID) -> None:
    """Cancel the email, or confirm a cancel that already happened. Raises EmailNotFound, AlreadySending or
    DeliveryUnavailable."""
    if queued_at(message_id) is None:
        raise EmailNotFound()
    response = _call(lambda: cancel_scheduled_email(team_id, str(message_id)), "cancel", team_id, message_id)
    refusal = _refusal_code(response)
    if response.status_code == 200:
        _mark_canceled(team_id, message_id)
        return
    if response.status_code == 409 and refusal == "already_sending":
        raise AlreadySending()
    if response.status_code == 404 and refusal == "not_found":
        if _canceled_before(team_id, message_id):
            return
        raise EmailNotFound()
    raise _unexpected("cancel", team_id, message_id, response)


def _canceled_mark_key(team_id: int, message_id: UUID) -> str:
    return f"transactional_email_canceled:{team_id}:{message_id}"


def _canceled_before(team_id: int, message_id: UUID) -> bool:
    if _has_canceled_mark(team_id, message_id):
        return True
    email_status = get_email_status(team_id, message_id)
    return email_status is not None and email_status.status == EmailSendStatus.CANCELED


def _mark_canceled(team_id: int, message_id: UUID) -> None:
    try:
        cache.set(_canceled_mark_key(team_id, message_id), True, timeout=int(_CANCELED_MARK_TTL.total_seconds()))
    except Exception:
        logger.exception("transactional_email_cancel_mark_failed", team_id=team_id, message_id=str(message_id))


def _has_canceled_mark(team_id: int, message_id: UUID) -> bool:
    try:
        return bool(cache.get(_canceled_mark_key(team_id, message_id)))
    except Exception:
        logger.exception("transactional_email_cancel_mark_failed", team_id=team_id, message_id=str(message_id))
        return False


def reschedule_email(team_id: int, message_id: UUID, scheduled_at: datetime) -> datetime:
    """Move the email to `scheduled_at`, or to now when that time passed. Returns the time it now goes out. Raises
    EmailNotFound, RescheduleTooFar, AlreadySending, EmailCanceled or DeliveryUnavailable."""
    if queued_at(message_id) is None:
        raise EmailNotFound()
    requested = scheduled_at.astimezone(UTC).isoformat()
    response = _call(
        lambda: reschedule_scheduled_email(team_id, str(message_id), requested), "reschedule", team_id, message_id
    )
    refusal = _refusal_code(response)
    if response.status_code == 200:
        return _answered_time(response) or scheduled_at
    if response.status_code == 400 and refusal == "invalid_scheduled_at":
        raise RescheduleTooFar("scheduled_at is more than 30 days after the email was sent, so PostHog didn't move it.")
    if response.status_code == 409 and refusal == "already_sending":
        raise AlreadySending()
    if response.status_code == 409 and refusal == "canceled":
        raise EmailCanceled()
    if response.status_code == 404 and refusal == "not_found":
        raise EmailNotFound()
    raise _unexpected("reschedule", team_id, message_id, response)


def _call(post: Callable[[], requests.Response], action: str, team_id: int, message_id: UUID) -> requests.Response:
    try:
        return post()
    except Exception as e:
        logger.exception(
            "transactional_email_manage_failed", action=action, team_id=team_id, message_id=str(message_id)
        )
        raise DeliveryUnavailable() from e


def _unexpected(action: str, team_id: int, message_id: UUID, response: requests.Response) -> DeliveryUnavailable:
    logger.error(
        "transactional_email_manage_rejected",
        action=action,
        team_id=team_id,
        message_id=str(message_id),
        status_code=response.status_code,
        refusal_code=_refusal_code(response),
    )
    return DeliveryUnavailable()


def _answer(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _refusal_code(response: requests.Response) -> str | None:
    code = _answer(response).get("error")
    return code if isinstance(code, str) else None


def _answered_time(response: requests.Response) -> datetime | None:
    value = _answer(response).get("scheduled_at")
    try:
        return parse_datetime(value) if isinstance(value, str) else None
    except ValueError:
        return None
