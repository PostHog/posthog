import re
import uuid
from typing import Any

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.utils import cast_timestamp_or_now

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID

logger = structlog.get_logger(__name__)

_INSTANCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@frozen
class UnsubscribeSource:
    """The workflow email a preferences link came from, read from the verified preferences token."""

    app_source_id: str
    instance_id: str


def parse_unsubscribe_source(token_data: dict[str, Any]) -> UnsubscribeSource | None:
    app_source_id = token_data.get("app_source_id")
    instance_id = token_data.get("instance_id")
    if not isinstance(app_source_id, str) or not isinstance(instance_id, str):
        return None
    try:
        uuid.UUID(app_source_id)
    except ValueError:
        return None
    if not _INSTANCE_ID_PATTERN.match(instance_id):
        return None
    return UnsubscribeSource(app_source_id=app_source_id, instance_id=instance_id)


def _includes_real_category(team_id: int, category_ids: list[str]) -> bool:
    # The preferences form accepts any category id string, so made-up ids must not add to the count.
    if ALL_MESSAGE_PREFERENCE_CATEGORY_ID in category_ids:
        return True
    real_ids = {
        str(category_id)
        for category_id in MessageCategory.objects.filter(team_id=team_id, deleted=False).values_list("id", flat=True)
    }
    return any(category_id in real_ids for category_id in category_ids)


def record_email_unsubscribed_metric(
    team_id: int, source: UnsubscribeSource | None, opted_out_category_ids: list[str]
) -> None:
    """Count one opt-out against the workflow email it came from. Best-effort: never fails the opt-out."""
    if source is None:
        return
    try:
        if not _includes_real_category(team_id, opted_out_category_ids):
            return
        payload = {
            "team_id": team_id,
            "timestamp": format_clickhouse_timestamp(cast_timestamp_or_now(None)),
            "app_source": "hog_flow",
            "app_source_id": source.app_source_id,
            "instance_id": source.instance_id,
            "metric_kind": "email",
            "metric_name": "email_unsubscribed",
            "count": 1,
        }
        get_producer(topic=KAFKA_APP_METRICS2).produce(topic=KAFKA_APP_METRICS2, data=payload)
    except Exception as e:
        logger.warning("email_unsubscribed_metric_failed", team_id=team_id, error=str(e))
        capture_exception(e)
