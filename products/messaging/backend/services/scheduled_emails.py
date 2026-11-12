"""Cancel or move a transactional email before a worker claims it. The CDP service holds the waiting job."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.utils.dateparse import parse_datetime

import requests
import structlog
from redis import Redis

from posthog import redis
from posthog.plugins.plugin_server_api import cancel_scheduled_email, reschedule_scheduled_email

from products.messaging.backend.facade.contracts import (
    AlreadySending,
    DeliveryUnavailable,
    EmailCanceled,
    EmailNotFound,
    EmailSendStatus,
    EmailStatus,
    RescheduleTooFar,
)
from products.messaging.backend.services.transactional_email_status import get_email_status, queued_at

logger = structlog.get_logger(__name__)

_CANCEL_MARK_TTL = timedelta(hours=1)
_STATUS_LAG = timedelta(minutes=5)
_REDIS_TIMEOUT_SECONDS = 1.0
_WAITING = (EmailSendStatus.SCHEDULED, EmailSendStatus.QUEUED)


class _CancelMark(StrEnum):
    CANCELED = "canceled"
    ATTEMPTED = "attempted"
    UNREADABLE = "unreadable"


def cancel_email(team_id: int, message_id: UUID) -> None:
    """Cancel the email, or confirm a cancel that already happened. Raises EmailNotFound, AlreadySending or
    DeliveryUnavailable."""
    queued = queued_at(message_id)
    if queued is None:
        raise EmailNotFound()
    try:
        response = _call(lambda: cancel_scheduled_email(team_id, str(message_id)), "cancel", team_id, message_id)
    except DeliveryUnavailable:
        _mark_attempted_unless_canceled(team_id, message_id)
        raise
    refusal = _refusal_code(response)
    if response.status_code == 200:
        _mark_canceled(team_id, message_id)
        return
    if response.status_code == 409 and refusal == "already_sending":
        raise AlreadySending()
    if response.status_code == 404 and refusal == "not_found":
        _answer_a_gone_job(team_id, message_id, queued)
        return
    raise _unexpected("cancel", team_id, message_id, response)


def _answer_a_gone_job(team_id: int, message_id: UUID, queued: datetime) -> None:
    mark = _read_cancel_mark(team_id, message_id)
    if mark == _CancelMark.CANCELED:
        return
    email_status = get_email_status(team_id, message_id)
    if email_status is not None and email_status.status == EmailSendStatus.CANCELED:
        return
    if mark in (_CancelMark.ATTEMPTED, _CancelMark.UNREADABLE) and _may_still_wait(email_status, queued):
        raise DeliveryUnavailable()
    raise EmailNotFound()


def _may_still_wait(email_status: EmailStatus | None, queued: datetime) -> bool:
    if email_status is None:
        return datetime.now(UTC) - queued < _STATUS_LAG
    return email_status.status in _WAITING


def _cancel_mark_key(team_id: int, message_id: UUID) -> str:
    return f"transactional_email_canceled:{team_id}:{message_id}"


def _cancel_marks() -> Redis:
    return redis.get_client(socket_timeout=_REDIS_TIMEOUT_SECONDS, socket_connect_timeout=_REDIS_TIMEOUT_SECONDS)


def _mark_canceled(team_id: int, message_id: UUID) -> None:
    _write_cancel_mark(team_id, message_id, _CancelMark.CANCELED, only_if_unmarked=False)


def _mark_attempted_unless_canceled(team_id: int, message_id: UUID) -> None:
    _write_cancel_mark(team_id, message_id, _CancelMark.ATTEMPTED, only_if_unmarked=True)


def _write_cancel_mark(team_id: int, message_id: UUID, mark: _CancelMark, *, only_if_unmarked: bool) -> None:
    try:
        _cancel_marks().set(_cancel_mark_key(team_id, message_id), mark.value, ex=_CANCEL_MARK_TTL, nx=only_if_unmarked)
    except Exception:
        logger.exception(
            "transactional_email_cancel_mark_write_failed", team_id=team_id, message_id=str(message_id), mark=mark
        )


def _read_cancel_mark(team_id: int, message_id: UUID) -> _CancelMark | None:
    try:
        stored = _cancel_marks().get(_cancel_mark_key(team_id, message_id))
    except Exception:
        logger.exception("transactional_email_cancel_mark_read_failed", team_id=team_id, message_id=str(message_id))
        return _CancelMark.UNREADABLE
    mark = stored.decode() if isinstance(stored, bytes) else None
    return _CancelMark(mark) if mark in (_CancelMark.CANCELED, _CancelMark.ATTEMPTED) else None


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
