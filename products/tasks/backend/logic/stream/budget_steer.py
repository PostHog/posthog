from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from django.utils import timezone

from celery import current_app

from posthog.ph_client import ph_scoped_capture

from products.tasks.backend.logic.services.connection_token import SANDBOX_EVENT_INGEST_TOKEN_TTL
from products.tasks.backend.redis import get_tasks_stream_redis_sync

BudgetSteerProperties = dict[str, str | int | float | bool]
BUDGET_STEER_CAPTURE_TASK = "products.tasks.backend.tasks.tasks.capture_budget_steer"
BUDGET_STEER_RETENTION_SECONDS = int(SANDBOX_EVENT_INGEST_TOKEN_TTL.total_seconds())


class BudgetSteerCapture:
    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str) or len(value) > 40:
            return None
        try:
            timestamp = datetime.fromisoformat(value)
        except ValueError:
            return None
        return timestamp if timestamp.tzinfo is not None else None

    @classmethod
    def enqueue(
        cls,
        team_id: int,
        run_id: str,
        sequence: int,
        properties: BudgetSteerProperties,
        event_timestamp: object = None,
    ) -> None:
        event_uuid = str(uuid5(NAMESPACE_URL, f"posthog-task-budget-steer:{run_id}:{sequence}"))
        redis = get_tasks_stream_redis_sync()
        if redis.exists(f"task-run-budget-steer:{event_uuid}:captured"):
            return
        timestamp = (
            cls._parse_timestamp(event_timestamp)
            or cls._parse_timestamp(properties.get("delivered_at"))
            or cls._parse_timestamp(properties.get("threshold_at"))
            or timezone.now()
        ).isoformat()
        timestamp_key = f"task-run-budget-steer:{event_uuid}:timestamp"
        # Redis before 7.0 rejects SET with NX and GET together, so read the first value back separately.
        if not redis.set(timestamp_key, timestamp, nx=True, ex=BUDGET_STEER_RETENTION_SECONDS):
            original_timestamp = redis.get(timestamp_key)
            if original_timestamp is not None:
                timestamp = original_timestamp.decode() if isinstance(original_timestamp, bytes) else original_timestamp
        current_app.send_task(
            BUDGET_STEER_CAPTURE_TASK,
            kwargs={"team_id": team_id, "event_uuid": event_uuid, "timestamp": timestamp, "properties": properties},
        )

    @staticmethod
    def capture(team_id: int, event_uuid: str, timestamp: str, properties: BudgetSteerProperties) -> None:
        redis = get_tasks_stream_redis_sync()
        captured_key = f"task-run-budget-steer:{event_uuid}:captured"
        if redis.exists(captured_key):
            return
        with ph_scoped_capture(raise_on_error=True) as capture:
            capture(
                distinct_id=f"team_{team_id}",
                event="task run budget steer",
                properties=properties,
                uuid=event_uuid,
                timestamp=datetime.fromisoformat(timestamp),
            )
        redis.set(captured_key, "1", ex=BUDGET_STEER_RETENTION_SECONDS)
