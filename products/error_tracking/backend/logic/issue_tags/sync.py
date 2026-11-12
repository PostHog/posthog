from datetime import datetime
from uuid import UUID

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_ERROR_TRACKING_ISSUE_TAGS

from products.error_tracking.backend.sql import INSERT_ERROR_TRACKING_ISSUE_TAG


def sync_issue_tag_to_clickhouse(
    *, team_id: int, issue_id: UUID, key: str, value: bool | None, updated_at: datetime
) -> None:
    ClickhouseProducer().produce(
        sql=INSERT_ERROR_TRACKING_ISSUE_TAG,
        topic=KAFKA_ERROR_TRACKING_ISSUE_TAGS,
        data={
            "team_id": team_id,
            "issue_id": str(issue_id),
            "key": key,
            "value": None if value is None else int(value),
            "is_deleted": 0,
            # The writer sets updated_at while it holds the row lock, so the versions of two writes to
            # one tag follow their commit order. A clock read after the commit can reverse that order.
            "version": int(updated_at.timestamp() * 1000),
        },
    )
