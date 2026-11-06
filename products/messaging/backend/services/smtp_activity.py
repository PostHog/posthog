"""A short list per project of what the SMTP relay refused or dropped, for the setup page. It holds addresses and the
reply a client got, never message content, and expires on its own."""

import json
import time
from typing import Any

from django.db import models

from posthog.redis import get_client

SMTP_ACTIVITY_LIMIT = 50
SMTP_ACTIVITY_TTL_SECONDS = 7 * 24 * 60 * 60


class SmtpActivityKind(models.TextChoices):
    REFUSED = "refused", "Refused"
    DROPPED_HEADERS = "dropped_headers", "Dropped headers"


def _key(team_id: int) -> str:
    return f"@posthog/messaging/smtp-activity/{team_id}"


def record_smtp_activity(team_id: int, activity: dict[str, Any]) -> None:
    key = _key(team_id)
    pipeline = get_client().pipeline()
    pipeline.lpush(key, json.dumps({**activity, "at": time.time()}))
    pipeline.ltrim(key, 0, SMTP_ACTIVITY_LIMIT - 1)
    pipeline.expire(key, SMTP_ACTIVITY_TTL_SECONDS)
    pipeline.execute()


def recent_smtp_activity(team_id: int) -> list[dict[str, Any]]:
    return [json.loads(entry) for entry in get_client().lrange(_key(team_id), 0, SMTP_ACTIVITY_LIMIT - 1)]
