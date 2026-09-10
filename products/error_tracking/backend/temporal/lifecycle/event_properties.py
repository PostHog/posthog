import json
from datetime import UTC
from typing import Protocol

from django.conf import settings
from django.utils.dateparse import parse_datetime

from prometheus_client import Counter, Histogram
from redis.exceptions import RedisError

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.models import Team
from posthog.redis import get_client

ERROR_TRACKING_EVENT_PROPERTIES_KEY_PREFIX = "error_tracking:event_properties:v1"

ERROR_TRACKING_EVENT_PROPERTIES_READS = Counter(
    "error_tracking_event_properties_reads_total",
    "Error Tracking event property reads by storage source and outcome",
    labelnames=("source", "outcome"),
)
ERROR_TRACKING_EVENT_PROPERTIES_READ_DURATION = Histogram(
    "error_tracking_event_properties_read_duration_seconds",
    "Duration of Error Tracking event property reads by storage source",
    labelnames=("source",),
)


class IssueCreatedEventNotFoundError(RuntimeError):
    pass


class EventPropertiesIssueSnapshot(Protocol):
    @property
    def created_at(self) -> str: ...


class EventPropertiesWorkflowInputs(Protocol):
    @property
    def team_id(self) -> int: ...

    @property
    def event_uuid(self) -> str: ...

    @property
    def event_timestamp(self) -> str: ...

    @property
    def issue(self) -> EventPropertiesIssueSnapshot: ...


def error_tracking_event_properties_key(team_id: int, event_uuid: str) -> str:
    return f"{ERROR_TRACKING_EVENT_PROPERTIES_KEY_PREFIX}:{team_id}:{event_uuid}"


def _fetch_event_properties_from_valkey(inputs: EventPropertiesWorkflowInputs) -> dict[str, object] | None:
    redis_url = settings.ERROR_TRACKING_EVENT_PROPERTIES_REDIS_URL
    if not redis_url:
        ERROR_TRACKING_EVENT_PROPERTIES_READS.labels(source="valkey", outcome="not_configured").inc()
        return None

    key = error_tracking_event_properties_key(inputs.team_id, inputs.event_uuid)
    try:
        with ERROR_TRACKING_EVENT_PROPERTIES_READ_DURATION.labels(source="valkey").time():
            payload = get_client(redis_url).get(key)
    except RedisError:
        ERROR_TRACKING_EVENT_PROPERTIES_READS.labels(source="valkey", outcome="error").inc()
        return None

    if payload is None:
        ERROR_TRACKING_EVENT_PROPERTIES_READS.labels(source="valkey", outcome="miss").inc()
        return None

    try:
        properties = json.loads(payload)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        ERROR_TRACKING_EVENT_PROPERTIES_READS.labels(source="valkey", outcome="invalid_payload").inc()
        return None

    if not isinstance(properties, dict):
        ERROR_TRACKING_EVENT_PROPERTIES_READS.labels(source="valkey", outcome="invalid_payload").inc()
        return None

    ERROR_TRACKING_EVENT_PROPERTIES_READS.labels(source="valkey", outcome="hit").inc()
    return properties


def _fetch_event_properties_from_clickhouse(team: Team, inputs: EventPropertiesWorkflowInputs) -> dict[str, object]:
    event_timestamp = parse_datetime(inputs.event_timestamp) or parse_datetime(inputs.issue.created_at)
    if event_timestamp is None:
        raise ValueError(f"Invalid exception timestamp: {inputs.event_timestamp}")
    if event_timestamp.tzinfo is None:
        event_timestamp = event_timestamp.replace(tzinfo=UTC)

    query = parse_select(
        """
        SELECT properties
        FROM events
        WHERE uuid = {event_uuid}
          AND timestamp >= {event_timestamp} - INTERVAL 1 MINUTE
          AND timestamp <= {event_timestamp} + INTERVAL 1 MINUTE
        LIMIT 1
        """,
        placeholders={
            "event_uuid": ast.Constant(value=inputs.event_uuid),
            "event_timestamp": ast.Constant(value=event_timestamp),
        },
    )
    with ERROR_TRACKING_EVENT_PROPERTIES_READ_DURATION.labels(source="clickhouse").time():
        response = execute_hogql_query(
            query=query,
            team=team,
            query_type="ErrorTrackingIssueCreatedEventProperties",
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.ERROR_TRACKING,
        )
    if not response.results:
        ERROR_TRACKING_EVENT_PROPERTIES_READS.labels(source="clickhouse", outcome="miss").inc()
        raise IssueCreatedEventNotFoundError(f"Exception event {inputs.event_uuid} not found for team {inputs.team_id}")

    properties = response.results[0][0]
    if isinstance(properties, str):
        properties = json.loads(properties)
    if not isinstance(properties, dict):
        raise TypeError(f"Exception event {inputs.event_uuid} returned invalid properties")
    ERROR_TRACKING_EVENT_PROPERTIES_READS.labels(source="clickhouse", outcome="hit").inc()
    return properties


def fetch_event_properties(team: Team, inputs: EventPropertiesWorkflowInputs) -> dict[str, object]:
    properties = _fetch_event_properties_from_valkey(inputs)
    if properties is not None:
        return properties
    return _fetch_event_properties_from_clickhouse(team, inputs)
