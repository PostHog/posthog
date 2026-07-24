import json
import uuid
import dataclasses
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.helpers.tiktoken_encoding import LLM_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model

from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
)
from products.error_tracking.backend.temporal.lifecycle.event_properties import (
    error_tracking_event_properties_key,
    fetch_event_properties,
)
from products.error_tracking.backend.temporal.lifecycle.issue_created.activities import (
    generate_issue_created_embedding_activity,
)
from products.error_tracking.backend.temporal.lifecycle.issue_created.types import (
    EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE,
    GeneratedIssueEmbedding,
    IssueCreatedSnapshot,
    IssueCreatedWorkflowInputs,
    IssueCreatedWorkflowResult,
    IssueEmbeddingPreparationResult,
)
from products.error_tracking.backend.temporal.lifecycle.issue_created.workflow import ErrorTrackingIssueCreatedWorkflow
from products.error_tracking.backend.temporal.lifecycle.rendering import decode_token_prefix, render_stacktrace


def _inputs(fingerprint: str) -> IssueCreatedWorkflowInputs:
    event_uuid = str(uuid.uuid4())
    return IssueCreatedWorkflowInputs(
        notification_id=str(uuid.uuid4()),
        team_id=1,
        issue_id=str(uuid.uuid4()),
        issue=IssueCreatedSnapshot(
            name="TypeError",
            description="Something failed",
            status="active",
            created_at="2026-07-21T12:00:00Z",
        ),
        fingerprint=fingerprint,
        event_uuid=event_uuid,
        event_timestamp="2026-07-21T12:00:00Z",
    )


def test_parse_inputs_accepts_cymbal_issue_created_notification() -> None:
    inputs = _inputs("fingerprint")
    payload = {
        **dataclasses.asdict(inputs),
        "type": "issue_created",
        "event_properties": {"$exception_list": [{"type": "TypeError", "value": "boom"}]},
    }

    assert ErrorTrackingIssueCreatedWorkflow.parse_inputs([json.dumps(payload)]) == inputs


def test_decode_token_prefix_does_not_emit_replacement_characters() -> None:
    encoding = get_tiktoken_encoding_for_model(LLM_TOKEN_COUNT_PROXY_MODEL)
    tokens = encoding.encode("hello 💥")

    assert encoding.decode(tokens[:2]) == "hello �"
    assert decode_token_prefix(encoding, tokens, max_tokens=2) == "hello"


def test_stacktrace_rendering_matches_cymbal_embedding_content() -> None:
    event_properties: dict[str, object] = {
        "$exception_list": [
            {
                "type": "TypeError",
                "value": "failed",
                "stacktrace": {
                    "type": "resolved",
                    "frames": [
                        {
                            "mangled_name": "fallback",
                            "resolved_name": "",
                            "source": "",
                            "line": 0,
                            "column": 0,
                        },
                        {"mangled_name": "second", "source": "app.py", "line": 4},
                    ],
                },
            },
            {
                "type": "RawError",
                "value": "unresolved",
                "stacktrace": {
                    "type": "raw",
                    "frames": [{"function": "raw_function", "filename": "raw.py", "lineno": 5}],
                },
            },
        ]
    }

    assert render_stacktrace(event_properties, max_tokens=7000) == (
        "TypeError: failed\n in  line 0 column 0\nsecond in app.py line 4\nRawError: unresolved\n"
    )


@patch("products.error_tracking.backend.temporal.lifecycle.issue_created.activities.render_stacktrace")
@patch("products.error_tracking.backend.temporal.lifecycle.issue_created.activities.fetch_event_properties")
@patch("products.error_tracking.backend.temporal.lifecycle.issue_created.activities.Team.objects.get")
@patch("products.error_tracking.backend.temporal.lifecycle.issue_created.activities.generate_embedding")
def test_embedding_service_timeout_is_classified_as_retryable(
    generate_embedding: MagicMock,
    get_team: MagicMock,
    fetch_event_properties: MagicMock,
    render_stacktrace: MagicMock,
) -> None:
    get_team.return_value.organization.is_ai_data_processing_approved = True
    fetch_event_properties.return_value = {"$exception_list": [{"type": "TypeError", "value": "boom"}]}
    render_stacktrace.return_value = "TypeError: boom"
    generate_embedding.side_effect = requests.Timeout("embedding timeout")

    with pytest.raises(ApplicationError) as error:
        generate_issue_created_embedding_activity(_inputs("fingerprint"))

    assert error.value.type == EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE
    assert error.value.non_retryable is False


@patch("products.error_tracking.backend.temporal.lifecycle.issue_created.activities.render_stacktrace")
@patch("products.error_tracking.backend.temporal.lifecycle.issue_created.activities.fetch_event_properties")
@patch("products.error_tracking.backend.temporal.lifecycle.issue_created.activities.Team.objects.get")
@patch("products.error_tracking.backend.temporal.lifecycle.issue_created.activities.generate_embedding")
def test_embedding_service_rejected_request_is_non_retryable(
    generate_embedding: MagicMock,
    get_team: MagicMock,
    fetch_event_properties: MagicMock,
    render_stacktrace: MagicMock,
) -> None:
    get_team.return_value.organization.is_ai_data_processing_approved = True
    fetch_event_properties.return_value = {"$exception_list": [{"type": "TypeError", "value": "boom"}]}
    render_stacktrace.return_value = "TypeError: boom"
    generate_embedding.side_effect = requests.HTTPError(response=MagicMock(status_code=400))

    with pytest.raises(ApplicationError) as error:
        generate_issue_created_embedding_activity(_inputs("fingerprint"))

    assert error.value.type == "EmbeddingRequestRejected"
    assert error.value.non_retryable is True


@override_settings(ERROR_TRACKING_EVENT_PROPERTIES_REDIS_URL="redis://event-properties")
@patch("products.error_tracking.backend.temporal.lifecycle.event_properties.execute_hogql_query")
@patch("products.error_tracking.backend.temporal.lifecycle.event_properties.get_client")
def test_fetches_full_event_properties_from_valkey_without_clickhouse(
    get_client: MagicMock, execute_hogql_query: MagicMock
) -> None:
    inputs = _inputs("fingerprint")
    properties: dict[str, object] = {
        "$exception_list": [{"type": "TypeError", "value": "💥", "metadata": {"nested": [1, None, True]}}],
        "custom": {"large": "value", "number": 3.5},
    }
    get_client.return_value.get.return_value = json.dumps(properties, ensure_ascii=False).encode()

    assert fetch_event_properties(MagicMock(), inputs) == properties
    get_client.return_value.get.assert_called_once_with(error_tracking_event_properties_key(1, inputs.event_uuid))
    execute_hogql_query.assert_not_called()


@override_settings(ERROR_TRACKING_EVENT_PROPERTIES_REDIS_URL="redis://event-properties")
@patch("products.error_tracking.backend.temporal.lifecycle.event_properties.execute_hogql_query")
@patch("products.error_tracking.backend.temporal.lifecycle.event_properties.get_client")
def test_falls_back_to_clickhouse_when_valkey_payload_expired(
    get_client: MagicMock, execute_hogql_query: MagicMock
) -> None:
    inputs = _inputs("fingerprint")
    properties = {"$exception_list": [{"type": "TypeError", "value": "expired"}]}
    get_client.return_value.get.return_value = None
    execute_hogql_query.return_value = SimpleNamespace(results=[[json.dumps(properties)]])

    assert fetch_event_properties(MagicMock(), inputs) == properties
    execute_hogql_query.assert_called_once()


@pytest.mark.asyncio
async def test_only_notifies_for_an_issue_that_was_not_merged() -> None:
    event_issue_ids: list[str] = []
    signal_issue_ids: list[str] = []
    signal_attempts: dict[str, int] = {}

    @activity.defn(name="generate_issue_created_embedding_activity")
    async def generate(inputs: IssueCreatedWorkflowInputs) -> IssueEmbeddingPreparationResult:
        if inputs.fingerprint == "embedding-unavailable":
            raise ApplicationError(
                "embedding unavailable",
                type=EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE,
            )
        return IssueEmbeddingPreparationResult(
            team_exists=True,
            embedding=GeneratedIssueEmbedding(
                merge_inputs=FingerprintEmbeddingResultInputs(
                    team_id=inputs.team_id,
                    fingerprint=inputs.fingerprint,
                    rendering="type_message_and_stack",
                    timestamp=inputs.issue.created_at,
                    model_name="text-embedding-3-large-3072",
                    embedding=[0.1, 0.2],
                    source_issue_id=inputs.issue_id,
                ),
                content="TypeError: Something failed",
            ),
        )

    @activity.defn(name="persist_issue_created_embedding_activity")
    async def persist(_: GeneratedIssueEmbedding) -> None:
        return None

    @activity.defn(name="merge_issue_created_fingerprint_activity")
    async def merge(inputs: FingerprintEmbeddingResultInputs) -> FingerprintEmbeddingMergeResult:
        return FingerprintEmbeddingMergeResult(merged_count=int(inputs.fingerprint == "merged"))

    @activity.defn(name="emit_issue_created_internal_event_activity")
    async def emit_event(inputs: IssueCreatedWorkflowInputs) -> None:
        event_issue_ids.append(inputs.issue_id)

    @activity.defn(name="emit_issue_created_signal_activity")
    async def emit_signal(inputs: IssueCreatedWorkflowInputs) -> None:
        signal_attempts[inputs.issue_id] = signal_attempts.get(inputs.issue_id, 0) + 1
        if signal_attempts[inputs.issue_id] == 1:
            raise RuntimeError("transient signal failure")
        signal_issue_ids.append(inputs.issue_id)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueCreatedWorkflow],
            activities=[generate, persist, merge, emit_event, emit_signal],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            merged_inputs = _inputs("merged")
            unmerged_inputs = _inputs("unmerged")
            embedding_unavailable_inputs = _inputs("embedding-unavailable")
            merged_result = await environment.client.execute_workflow(
                ErrorTrackingIssueCreatedWorkflow.run,
                merged_inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
            unmerged_result = await environment.client.execute_workflow(
                ErrorTrackingIssueCreatedWorkflow.run,
                unmerged_inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
            embedding_unavailable_result = await environment.client.execute_workflow(
                ErrorTrackingIssueCreatedWorkflow.run,
                embedding_unavailable_inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert merged_result == IssueCreatedWorkflowResult(merged=True)
    assert unmerged_result == IssueCreatedWorkflowResult(notified=True)
    assert embedding_unavailable_result == IssueCreatedWorkflowResult(
        notified=True,
        embedding_skipped_reason="embedding_service_unavailable",
    )
    assert event_issue_ids == [unmerged_inputs.issue_id, embedding_unavailable_inputs.issue_id]
    assert signal_issue_ids == [unmerged_inputs.issue_id, embedding_unavailable_inputs.issue_id]
    assert signal_attempts == {
        unmerged_inputs.issue_id: 2,
        embedding_unavailable_inputs.issue_id: 2,
    }
