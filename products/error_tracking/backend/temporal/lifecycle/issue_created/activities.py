import json
from datetime import UTC, datetime
from typing import cast

from django.conf import settings
from django.utils.dateparse import parse_datetime

import httpx
import requests
import tiktoken
import posthoganalytics
from asgiref.sync import sync_to_async
from confluent_kafka import KafkaError, KafkaException
from prometheus_client import Counter, Histogram
from redis.exceptions import RedisError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import generate_embedding
from posthog.cdp.internal_events import InternalEventEvent, flush_internal_events_producer, produce_internal_event
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.helpers.tiktoken_encoding import (
    LLM_TOKEN_COUNT_PROXY_MODEL,
    TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL,
    get_tiktoken_encoding_for_model,
)
from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_TOPIC
from posthog.models import Team
from posthog.redis import get_client
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.temporal.fingerprint_embedding_result.activities import merge_similar_fingerprints
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
)
from products.error_tracking.backend.temporal.lifecycle.issue_created.types import (
    EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE,
    GeneratedIssueEmbedding,
    IssueCreatedWorkflowInputs,
    IssueEmbeddingPreparationResult,
)
from products.signals.backend.facade.api import emit_signal

EMBEDDING_MODEL = "text-embedding-3-large-3072"
EMBEDDING_RENDERING = "type_message_and_stack"
EMBEDDING_MAX_TOKENS = 7000
SIGNAL_MAX_TOKENS = 8000
KAFKA_DELIVERY_TIMEOUT_SECONDS = 30
EMBEDDING_DISABLED_LIBRARIES = {"posthog-elixir"}
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


def _as_dict(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _as_list(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _string(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _render_frame(value: object) -> str:
    frame = _as_dict(value)
    if frame is None:
        return ""

    resolved_name = frame.get("resolved_name")
    function = resolved_name if isinstance(resolved_name, str) else _string(frame.get("mangled_name"))
    source = frame.get("source")
    line = frame.get("line")
    column = frame.get("column")

    rendered = function
    if isinstance(source, str):
        rendered += f" in {source}"
    if isinstance(line, int):
        rendered += f" line {line}"
    if isinstance(column, int):
        rendered += f" column {column}"
    return f"{rendered}\n"


def _render_stacktrace_unbounded(event_properties: dict[str, object], truncate_frames: bool) -> str:
    rendered: list[str] = []
    for value in _as_list(event_properties.get("$exception_list")):
        exception = _as_dict(value)
        if exception is None:
            continue

        exception_type = _string(exception.get("type"), "Unknown")
        exception_value = _string(exception.get("value"))[:300]
        rendered.append(f"{exception_type}: {exception_value}\n")

        stacktrace = _as_dict(exception.get("stacktrace"))
        frames = _as_list(stacktrace.get("frames")) if stacktrace and stacktrace.get("type") == "resolved" else []
        if truncate_frames and len(frames) > 2:
            rendered.extend((_render_frame(frames[0]), "...\n", _render_frame(frames[-1])))
        else:
            rendered.extend(_render_frame(frame) for frame in frames)

    return "".join(rendered)


def _decode_token_prefix(encoding: tiktoken.Encoding, tokens: list[int], max_tokens: int) -> str:
    prefix = tokens[:max_tokens]
    while prefix:
        try:
            return encoding.decode(prefix, errors="strict")
        except UnicodeDecodeError:
            prefix.pop()
    return ""


def render_stacktrace(event_properties: dict[str, object], max_tokens: int) -> str:
    encoding = get_tiktoken_encoding_for_model(TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL)
    rendered = _render_stacktrace_unbounded(event_properties, truncate_frames=False)
    tokens = encoding.encode(rendered, allowed_special="all")
    if len(tokens) <= max_tokens:
        return rendered

    rendered = _render_stacktrace_unbounded(event_properties, truncate_frames=True)
    tokens = encoding.encode(rendered, allowed_special="all")
    if len(tokens) <= max_tokens:
        return rendered

    return _decode_token_prefix(encoding, tokens, max_tokens)


def _embedding_skip_reason(event_properties: dict[str, object]) -> str | None:
    for value in _as_list(event_properties.get("$exception_fingerprint_record")):
        record = _as_dict(value)
        record_type = _string(record.get("type")) if record else ""
        if record_type == "manual":
            return "manual_fingerprint"
        if record_type == "custom":
            return "custom_grouping_rule"

    library = event_properties.get("$lib")
    if isinstance(library, str) and library in EMBEDDING_DISABLED_LIBRARIES:
        return "disabled_sdk"
    return None


def error_tracking_event_properties_key(team_id: int, event_uuid: str) -> str:
    return f"{ERROR_TRACKING_EVENT_PROPERTIES_KEY_PREFIX}:{team_id}:{event_uuid}"


def _fetch_event_properties_from_valkey(inputs: IssueCreatedWorkflowInputs) -> dict[str, object] | None:
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


def _fetch_event_properties_from_clickhouse(team: Team, inputs: IssueCreatedWorkflowInputs) -> dict[str, object]:
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


def _fetch_event_properties(team: Team, inputs: IssueCreatedWorkflowInputs) -> dict[str, object]:
    properties = _fetch_event_properties_from_valkey(inputs)
    if properties is not None:
        return properties
    return _fetch_event_properties_from_clickhouse(team, inputs)


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def generate_issue_created_embedding_activity(
    inputs: IssueCreatedWorkflowInputs,
) -> IssueEmbeddingPreparationResult:
    try:
        team = Team.objects.get(id=inputs.team_id)
    except Team.DoesNotExist:
        return IssueEmbeddingPreparationResult(team_exists=False)

    if not team.organization.is_ai_data_processing_approved:
        return IssueEmbeddingPreparationResult(
            team_exists=True,
            skipped_reason="ai_data_processing_not_approved",
        )

    event_properties = _fetch_event_properties(team, inputs)
    skipped_reason = _embedding_skip_reason(event_properties)
    if skipped_reason is not None:
        return IssueEmbeddingPreparationResult(team_exists=True, skipped_reason=skipped_reason)

    content = render_stacktrace(event_properties, EMBEDDING_MAX_TOKENS)
    try:
        response = generate_embedding(team, content, model=EMBEDDING_MODEL, no_truncate=True, timeout=60)
    except (requests.RequestException, httpx.HTTPError) as error:
        status_code = getattr(getattr(error, "response", None), "status_code", None)
        if status_code is not None and status_code < 500 and status_code != 429:
            raise ApplicationError(
                f"Embedding service rejected the request with status {status_code}",
                type="EmbeddingRequestRejected",
                non_retryable=True,
            ) from error
        raise ApplicationError(
            "Embedding service is unavailable",
            type=EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE,
        ) from error
    except (KeyError, TypeError) as error:
        raise ApplicationError(
            "Embedding service returned an invalid response",
            type=EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE,
        ) from error
    return IssueEmbeddingPreparationResult(
        team_exists=True,
        embedding=GeneratedIssueEmbedding(
            merge_inputs=FingerprintEmbeddingResultInputs(
                team_id=inputs.team_id,
                fingerprint=inputs.fingerprint,
                rendering=EMBEDDING_RENDERING,
                timestamp=inputs.issue.created_at,
                model_name=EMBEDDING_MODEL,
                embedding=response.embedding,
                source_issue_id=inputs.issue_id,
            ),
            content=content,
        ),
    )


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def persist_issue_created_embedding_activity(inputs: GeneratedIssueEmbedding) -> None:
    merge_inputs = inputs.merge_inputs
    timestamp = parse_datetime(merge_inputs.timestamp)
    if timestamp is None:
        raise ValueError(f"Invalid issue creation timestamp: {merge_inputs.timestamp}")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    payload = {
        "team_id": merge_inputs.team_id,
        "product": "error_tracking",
        "document_type": "fingerprint",
        "model_name": merge_inputs.model_name,
        "rendering": merge_inputs.rendering,
        "document_id": merge_inputs.fingerprint,
        "timestamp": timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "embedding": merge_inputs.embedding,
        "content": inputs.content,
        "metadata": json.dumps({}),
    }

    with producer_scope(
        topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, flush_timeout=KAFKA_DELIVERY_TIMEOUT_SECONDS
    ) as producer:
        result = producer.produce(topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, data=payload)
    result.get(timeout=0)


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def merge_issue_created_fingerprint_activity(
    inputs: FingerprintEmbeddingResultInputs,
) -> FingerprintEmbeddingMergeResult:
    return merge_similar_fingerprints(
        inputs,
        activity_name="merge_issue_created_fingerprint_activity",
        workflow_name="error-tracking-issue-created",
    )


def _produce_issue_created_internal_event(
    inputs: IssueCreatedWorkflowInputs, event_properties: dict[str, object]
) -> None:
    exception_timestamp = parse_datetime(inputs.event_timestamp)
    if exception_timestamp is None:
        exception_timestamp = datetime.now(UTC)
    elif exception_timestamp.tzinfo is None:
        exception_timestamp = exception_timestamp.replace(tzinfo=UTC)

    properties: dict[str, object] = {
        "name": inputs.issue.name,
        "description": inputs.issue.description,
        "issue_description": inputs.issue.description,
        "first_seen": inputs.issue.created_at,
        "status": inputs.issue.status,
        "fingerprint": inputs.fingerprint,
        "exception_timestamp": exception_timestamp.isoformat(),
        "exception_props": event_properties,
    }
    if inputs.assignee is not None:
        properties["assignee"] = inputs.assignee

    def produce(event_properties: dict[str, object]) -> None:
        result = produce_internal_event(
            inputs.team_id,
            InternalEventEvent(
                event="$error_tracking_issue_created",
                distinct_id=inputs.issue_id,
                properties=event_properties,
                uuid=inputs.notification_id,
            ),
        )
        flush_internal_events_producer(KAFKA_DELIVERY_TIMEOUT_SECONDS)
        result.get(timeout=0)

    try:
        produce(properties)
    except KafkaException as error:
        kafka_error = error.args[0] if error.args else None
        if not isinstance(kafka_error, KafkaError) or kafka_error.name() != "MSG_SIZE_TOO_LARGE":
            raise
        properties.pop("exception_props", None)
        properties["message_was_too_large"] = True
        produce(properties)


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def emit_issue_created_internal_event_activity(inputs: IssueCreatedWorkflowInputs) -> None:
    try:
        team = Team.objects.get(id=inputs.team_id)
    except Team.DoesNotExist:
        return

    event_properties = _fetch_event_properties(team, inputs)
    _produce_issue_created_internal_event(inputs, event_properties)


@activity.defn
@scoped_temporal()
@close_db_connections
async def emit_issue_created_signal_activity(inputs: IssueCreatedWorkflowInputs) -> None:
    try:
        team = await Team.objects.aget(id=inputs.team_id)
    except Team.DoesNotExist:
        return

    event_properties = await sync_to_async(_fetch_event_properties, thread_sensitive=False)(team, inputs)
    issue_name = inputs.issue.name or "Unknown"
    issue_description = inputs.issue.description or ""
    preamble = "New error tracking issue created - this particular exception was observed for the first time"
    header = f"{preamble}:\n{issue_name}: {issue_description}\n"
    encoding = get_tiktoken_encoding_for_model(TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL)
    stacktrace_tokens = max(SIGNAL_MAX_TOKENS - len(encoding.encode(header)), 0)
    stacktrace = render_stacktrace(event_properties, stacktrace_tokens)
    description = f"{header}\n```\n{stacktrace}\n```"
    signal_encoding = get_tiktoken_encoding_for_model(LLM_TOKEN_COUNT_PROXY_MODEL)
    signal_tokens = signal_encoding.encode(description)
    if len(signal_tokens) > SIGNAL_MAX_TOKENS:
        description = _decode_token_prefix(signal_encoding, signal_tokens, SIGNAL_MAX_TOKENS)

    await emit_signal(
        team=team,
        source_product="error_tracking",
        source_type="issue_created",
        source_id=inputs.issue_id,
        description=description,
        weight=1.0,
        extra={"fingerprint": inputs.fingerprint},
        idempotency_key=inputs.notification_id,
    )


ACTIVITIES = [
    generate_issue_created_embedding_activity,
    persist_issue_created_embedding_activity,
    merge_issue_created_fingerprint_activity,
    emit_issue_created_internal_event_activity,
    emit_issue_created_signal_activity,
]
