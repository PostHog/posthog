from datetime import UTC, datetime

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from products.mcp_analytics.backend.facade.contracts import IntentGenerationUnavailable
from products.mcp_analytics.backend.intent_topics.corpus import DistinctIntent
from products.mcp_analytics.backend.intent_topics.embedding_sync import emit_intent_embeddings, select_intents_to_emit


def _intent(text: str, calls: int = 1) -> DistinctIntent:
    return DistinctIntent(hash=f"hash-{text}", text=text, calls=calls)


NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)


class TestSelectIntentsToEmit:
    def test_drops_hashes_that_already_have_a_vector(self) -> None:
        intents = [_intent("a"), _intent("b"), _intent("c")]

        selected = select_intents_to_emit(intents, seen={"hash-b"})

        assert [i.text for i in selected] == ["a", "c"]


class TestEmitIntentEmbeddings(APIBaseTest):
    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_emits_one_request_per_intent_with_the_256_model_and_only_the_call_count(self, mock_emit) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        now = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

        emitted = emit_intent_embeddings(self.team, [_intent("list flags", calls=3)], now=now)

        assert emitted == 1
        mock_emit.assert_called_once_with(
            content="list flags",
            team_id=self.team.pk,
            product="mcp_analytics",
            document_type="mcp-intent",
            rendering="raw",
            document_id="hash-list flags",
            models=["text-embedding-3-small-256"],
            timestamp=now,
            metadata={"calls": 3},
        )

    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_refuses_without_ai_data_processing_consent(self, mock_emit) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        try:
            emit_intent_embeddings(self.team, [_intent("a")], now=NOW)
        except IntentGenerationUnavailable:
            pass
        else:
            raise AssertionError("expected IntentGenerationUnavailable")
        mock_emit.assert_not_called()

    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_empty_input_emits_nothing(self, mock_emit) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        assert emit_intent_embeddings(self.team, [], now=NOW) == 0
        mock_emit.assert_not_called()

    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_raises_when_kafka_did_not_deliver_a_request(self, mock_emit) -> None:
        from confluent_kafka import KafkaException

        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        delivered, failed = MagicMock(), MagicMock()
        failed.get.side_effect = KafkaException("broker down")
        mock_emit.side_effect = [delivered, failed]

        with pytest.raises(KafkaException):
            emit_intent_embeddings(self.team, [_intent("a"), _intent("b")], now=NOW)

        delivered.get.assert_called_once()
