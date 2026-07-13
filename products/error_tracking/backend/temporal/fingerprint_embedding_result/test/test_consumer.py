import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from django.test import override_settings

from confluent_kafka import KafkaError, KafkaException
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from products.error_tracking.backend.management.commands.et_consume_embeddings import (
    Command,
    FingerprintEmbeddingResultOutcome,
    _commit_message,
    fingerprint_embedding_result_inputs_from_message,
    handle_embedding_result_message,
    start_fingerprint_embedding_result_workflow,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import FingerprintEmbeddingResultInputs
from products.error_tracking.backend.temporal.fingerprint_embedding_result.workflow import (
    ErrorTrackingFingerprintEmbeddingResultWorkflow,
)


def _embedding_result_message(**overrides: object) -> bytes:
    message: dict[str, object] = {
        "team_id": 1,
        "product": "error_tracking",
        "document_type": "fingerprint",
        "rendering": "type_message_and_stack",
        "document_id": "fingerprint-1",
        "timestamp": "2026-06-08T00:00:00Z",
        "content": "TypeError: failed",
        "models": ["text-embedding-3-large-3072"],
        "results": [
            {
                "model": "text-embedding-3-large-3072",
                "outcome": "success",
                "embedding": [0.1, 0.2, 0.3],
            },
            {
                "model": "text-embedding-3-small-1536",
                "outcome": "failure",
                "error": "rate limited",
            },
        ],
    }
    message.update(overrides)
    return json.dumps(message).encode("utf-8")


class TestFingerprintEmbeddingResultConsumer:
    def test_extracts_minimal_workflow_inputs(self) -> None:
        inputs = fingerprint_embedding_result_inputs_from_message(_embedding_result_message())

        assert inputs == FingerprintEmbeddingResultInputs(
            team_id=1,
            fingerprint="fingerprint-1",
            rendering="type_message_and_stack",
            timestamp="2026-06-08T00:00:00Z",
            model_name="text-embedding-3-large-3072",
            model_names=["text-embedding-3-large-3072"],
            embedding=[0.1, 0.2, 0.3],
        )

    def test_keeps_successful_model_names_without_embedding_for_backwards_compatibility(self) -> None:
        inputs = fingerprint_embedding_result_inputs_from_message(
            _embedding_result_message(results=[{"model": "text-embedding-3-large-3072", "outcome": "success"}])
        )

        assert inputs == FingerprintEmbeddingResultInputs(
            team_id=1,
            fingerprint="fingerprint-1",
            rendering="type_message_and_stack",
            timestamp="2026-06-08T00:00:00Z",
            model_name="text-embedding-3-large-3072",
            model_names=["text-embedding-3-large-3072"],
        )

    def test_extracts_only_selected_model_embedding(self) -> None:
        inputs = fingerprint_embedding_result_inputs_from_message(
            _embedding_result_message(
                results=[
                    {"model": "text-embedding-3-small-1536", "outcome": "success", "embedding": [0.4, 0.5]},
                    {"model": "text-embedding-3-large-3072", "outcome": "success", "embedding": [0.1, 0.2, 0.3]},
                ]
            )
        )

        assert inputs is not None
        assert inputs.model_name == "text-embedding-3-large-3072"
        assert inputs.model_names == ["text-embedding-3-small-1536", "text-embedding-3-large-3072"]
        assert inputs.embedding == [0.1, 0.2, 0.3]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"product": "llm_analytics"},
            {"document_type": "trace"},
        ],
    )
    def test_skips_unrelated_messages(self, overrides: dict[str, object]) -> None:
        assert fingerprint_embedding_result_inputs_from_message(_embedding_result_message(**overrides)) is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"team_id": "1"},
            {"document_id": None},
            {"rendering": None},
            {"timestamp": None},
            {"results": [{"model": "text-embedding-3-large-3072", "outcome": "failure", "error": "failed"}]},
        ],
    )
    def test_raises_for_malformed_fingerprint_messages(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValueError, match="Invalid error tracking fingerprint embedding result message"):
            fingerprint_embedding_result_inputs_from_message(_embedding_result_message(**overrides))

    @override_settings(ERROR_TRACKING_TASK_QUEUE="error-tracking-task-queue")
    @pytest.mark.asyncio
    async def test_start_workflow(self) -> None:
        client = AsyncMock()
        inputs = FingerprintEmbeddingResultInputs(
            team_id=1,
            fingerprint="fingerprint-1",
            rendering="type_message_and_stack",
            timestamp="2026-06-08T00:00:00Z",
            model_names=["text-embedding-3-large-3072"],
        )

        outcome = await start_fingerprint_embedding_result_workflow(client, inputs)

        assert outcome == FingerprintEmbeddingResultOutcome.STARTED
        client.start_workflow.assert_awaited_once_with(
            ErrorTrackingFingerprintEmbeddingResultWorkflow.run,
            inputs,
            id=ErrorTrackingFingerprintEmbeddingResultWorkflow.workflow_id_for(
                team_id=1,
                fingerprint="fingerprint-1",
                rendering="type_message_and_stack",
                timestamp="2026-06-08T00:00:00Z",
            ),
            task_queue="error-tracking-task-queue",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )

    @pytest.mark.asyncio
    async def test_start_workflow_handles_duplicates(self) -> None:
        client = AsyncMock()
        client.start_workflow.side_effect = WorkflowAlreadyStartedError("already started", "workflow-id")
        inputs = FingerprintEmbeddingResultInputs(
            team_id=1,
            fingerprint="fingerprint-1",
            rendering="type_message_and_stack",
            timestamp="2026-06-08T00:00:00Z",
            model_names=["text-embedding-3-large-3072"],
        )

        outcome = await start_fingerprint_embedding_result_workflow(client, inputs)

        assert outcome == FingerprintEmbeddingResultOutcome.ALREADY_STARTED

    @pytest.mark.asyncio
    async def test_handle_embedding_result_message_skips_unrelated_messages(self) -> None:
        client = AsyncMock()

        outcome = await handle_embedding_result_message(client, _embedding_result_message(product="llm_analytics"))

        assert outcome == FingerprintEmbeddingResultOutcome.SKIPPED
        client.start_workflow.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_kafka_message_commits_malformed_fingerprint_messages(self) -> None:
        consumer = MagicMock()
        message = MagicMock()
        message.error.return_value = None
        message.value.return_value = _embedding_result_message(team_id="1")

        await Command()._handle_kafka_message(consumer, AsyncMock(), message)

        consumer.commit.assert_called_once_with(message=message, asynchronous=False)

    @pytest.mark.parametrize(
        "error_code",
        [
            KafkaError.ILLEGAL_GENERATION,  # type: ignore[attr-defined]
            KafkaError.UNKNOWN_MEMBER_ID,  # type: ignore[attr-defined]
            KafkaError.REBALANCE_IN_PROGRESS,  # type: ignore[attr-defined]
        ],
    )
    @pytest.mark.asyncio
    async def test_commit_tolerates_rebalance_errors(self, error_code: int) -> None:
        consumer = MagicMock()
        consumer.commit.side_effect = KafkaException(KafkaError(error_code))

        await _commit_message(consumer, MagicMock())

        consumer.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_reraises_non_rebalance_errors(self) -> None:
        consumer = MagicMock()
        consumer.commit.side_effect = KafkaException(KafkaError(KafkaError.OFFSET_METADATA_TOO_LARGE))  # type: ignore[attr-defined]

        with pytest.raises(KafkaException):
            await _commit_message(consumer, MagicMock())
