from datetime import UTC, datetime
from typing import Protocol

from django.utils.dateparse import parse_datetime

from asgiref.sync import sync_to_async
from confluent_kafka import KafkaError, KafkaException

from posthog.cdp.internal_events import InternalEventEvent, flush_internal_events_producer, produce_internal_event
from posthog.helpers.tiktoken_encoding import (
    LLM_TOKEN_COUNT_PROXY_MODEL,
    TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL,
    get_tiktoken_encoding_for_model,
)
from posthog.models import Team

from products.error_tracking.backend.temporal.lifecycle.event_properties import (
    EventPropertiesIssueSnapshot,
    fetch_event_properties,
)
from products.error_tracking.backend.temporal.lifecycle.rendering import (
    SIGNAL_MAX_TOKENS,
    decode_token_prefix,
    render_stacktrace,
)
from products.signals.backend.facade.api import emit_signal

KAFKA_DELIVERY_TIMEOUT_SECONDS = 30


class IssueLifecycleSnapshot(EventPropertiesIssueSnapshot, Protocol):
    @property
    def name(self) -> str | None: ...

    @property
    def description(self) -> str | None: ...

    @property
    def status(self) -> str: ...


class IssueLifecycleWorkflowInputs(Protocol):
    @property
    def notification_id(self) -> str: ...

    @property
    def team_id(self) -> int: ...

    @property
    def issue_id(self) -> str: ...

    @property
    def issue(self) -> IssueLifecycleSnapshot: ...

    @property
    def fingerprint(self) -> str: ...

    @property
    def event_uuid(self) -> str: ...

    @property
    def event_timestamp(self) -> str: ...

    @property
    def assignee(self) -> str | None: ...


def produce_issue_lifecycle_internal_event(
    inputs: IssueLifecycleWorkflowInputs,
    *,
    event: str,
    exception_timestamp: str,
    extra_properties: dict[str, object] | None = None,
    include_status: bool = True,
    humanize_status: bool = True,
) -> None:
    try:
        team = Team.objects.get(id=inputs.team_id)
    except Team.DoesNotExist:
        return

    event_properties = fetch_event_properties(team, inputs)
    timestamp = parse_datetime(exception_timestamp)
    if timestamp is None:
        timestamp = datetime.now(UTC)
    elif timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    properties: dict[str, object] = {
        "name": inputs.issue.name,
        "description": inputs.issue.description,
        "issue_description": inputs.issue.description,
        "first_seen": inputs.issue.created_at,
        "fingerprint": inputs.fingerprint,
        "exception_timestamp": timestamp.isoformat(),
        "exception_props": event_properties,
    }
    if include_status:
        status = inputs.issue.status
        properties["status"] = (
            {
                "archived": "Archived",
                "active": "Active",
                "resolved": "Resolved",
                "pending_release": "Pending Release",
                "suppressed": "Suppressed",
            }.get(status, status)
            if humanize_status
            else status
        )
    if inputs.assignee is not None:
        properties["assignee"] = inputs.assignee
    if extra_properties is not None:
        properties.update(extra_properties)

    def produce(properties_to_send: dict[str, object]) -> None:
        result = produce_internal_event(
            inputs.team_id,
            InternalEventEvent(
                event=event,
                distinct_id=inputs.issue_id,
                properties=properties_to_send,
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


async def emit_issue_lifecycle_signal(
    inputs: IssueLifecycleWorkflowInputs,
    *,
    source_type: str,
    preamble: str,
) -> None:
    try:
        team = await Team.objects.aget(id=inputs.team_id)
    except Team.DoesNotExist:
        return

    event_properties = await sync_to_async(fetch_event_properties, thread_sensitive=False)(team, inputs)
    issue_name = inputs.issue.name or "Unknown"
    issue_description = inputs.issue.description or ""
    header = f"{preamble}:\n{issue_name}: {issue_description}\n"
    encoding = get_tiktoken_encoding_for_model(TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL)
    stacktrace_tokens = max(SIGNAL_MAX_TOKENS - len(encoding.encode(header)), 0)
    stacktrace = render_stacktrace(event_properties, stacktrace_tokens)
    description = f"{header}\n```\n{stacktrace}\n```"
    signal_encoding = get_tiktoken_encoding_for_model(LLM_TOKEN_COUNT_PROXY_MODEL)
    signal_tokens = signal_encoding.encode(description)
    if len(signal_tokens) > SIGNAL_MAX_TOKENS:
        description = decode_token_prefix(signal_encoding, signal_tokens, SIGNAL_MAX_TOKENS)

    await emit_signal(
        team=team,
        source_product="error_tracking",
        source_type=source_type,
        source_id=inputs.issue_id,
        description=description,
        weight=1.0,
        extra={"fingerprint": inputs.fingerprint},
        idempotency_key=inputs.notification_id,
    )
