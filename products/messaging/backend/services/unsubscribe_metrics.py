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


@frozen
class EmailSendReference:
    workflow_id: str
    action_id: str | None
    invocation_id: str
    workflow_version: int | None

    def event_properties(self) -> dict[str, Any]:
        properties = {
            "$workflow_id": self.workflow_id,
            "$workflow_action_id": self.action_id,
            "$workflow_invocation_id": self.invocation_id,
            "$workflow_version": self.workflow_version,
        }
        return {key: value for key, value in properties.items() if value is not None}


def parse_email_send_reference(token_data: dict[str, Any]) -> EmailSendReference | None:
    workflow_id = token_data.get("workflow_id")
    invocation_id = token_data.get("invocation_id")
    if not isinstance(workflow_id, str) or not isinstance(invocation_id, str):
        return None
    action_id = token_data.get("instance_id")
    workflow_version = token_data.get("workflow_version")
    return EmailSendReference(
        workflow_id=workflow_id,
        action_id=action_id if isinstance(action_id, str) and _INSTANCE_ID_PATTERN.match(action_id) else None,
        invocation_id=invocation_id,
        workflow_version=workflow_version
        if isinstance(workflow_version, int) and not isinstance(workflow_version, bool)
        else None,
    )


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
