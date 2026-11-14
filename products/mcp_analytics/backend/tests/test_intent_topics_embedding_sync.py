import json
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import override_settings

import responses
from parameterized import parameterized
from requests import HTTPError

from posthog.schema import HogQLQueryModifiers

from posthog.api.embedding_worker import _EMBEDDING_URL
from posthog.clickhouse.client import sync_execute
from posthog.models.event.new_events_schema import events_route_scope

from products.mcp_analytics.backend.facade.contracts import IntentGenerationUnavailable
from products.mcp_analytics.backend.intent_hash import intent_hash
from products.mcp_analytics.backend.intent_topics.constants import MAX_EMBEDDING_TEXT_LENGTH
from products.mcp_analytics.backend.intent_topics.corpus import DistinctIntent
from products.mcp_analytics.backend.intent_topics.embedding_sync import (
    _EMBEDDING_TABLE,
    select_intents_to_emit,
    write_intent_embeddings,
)
from products.mcp_analytics.backend.tests.intent_topics_helpers import recent_hour, unit_vector

NOW = recent_hour(days_ago=0)


def _intent(text: str, calls: int = 1) -> DistinctIntent:
    return DistinctIntent(hash=intent_hash(text), text=text, calls=calls, source_min_timestamp=NOW - timedelta(days=3))


class TestSelectIntentsToEmit:
    def test_drops_hashes_that_already_have_a_vector(self) -> None:
        selected = select_intents_to_emit([_intent("a"), _intent("b"), _intent("c")], seen={intent_hash("b")})
        assert [i.text for i in selected] == ["a", "c"]


class TestWriteIntentEmbeddings(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.worker = responses.RequestsMock(assert_all_requests_are_fired=False)
        self.worker.start()
        self.addCleanup(self.worker.stop)
        self.worker.add(
            responses.POST,
            _EMBEDDING_URL,
            json={"embedding": unit_vector(0), "tokens_used": 3, "did_truncate": False},
        )

    def _rows(self) -> list:
        return sync_execute(
            f"SELECT document_id, timestamp, content, metadata, embedding FROM {_EMBEDDING_TABLE} WHERE team_id = %(team)s",
            {"team": self.team.pk},
        )

    def test_catch_up_preserves_source_age_and_writes_on_the_main_cluster(self) -> None:
        with (
            override_settings(CLICKHOUSE_EVENTS_OFFLINE_HOST="events.example.invalid"),
            events_route_scope(HogQLQueryModifiers(useNewEventsSchema=True)),
        ):
            written = write_intent_embeddings(self.team, [_intent("list flags", calls=3)])

        assert written == 1
        row = self._rows()[0]
        assert row[:3] == (intent_hash("list flags"), NOW - timedelta(days=3), "list flags")
        assert json.loads(row[3]) == {"calls": 3, "source_min_timestamp": (NOW - timedelta(days=3)).isoformat()}
        assert row[4] == unit_vector(0)

    def test_oversized_input_is_bounded_without_changing_the_document_identity(self) -> None:
        huge = _intent("🦔" * 90_000)

        write_intent_embeddings(self.team, [huge])

        row = self._rows()[0]
        assert (row[0], len(row[2])) == (huge.hash, MAX_EMBEDDING_TEXT_LENGTH)
        request = json.loads(self.worker.calls[0].request.body)
        assert request["content"] == row[2]

    def test_refuses_without_ai_data_processing_consent(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        with pytest.raises(IntentGenerationUnavailable):
            write_intent_embeddings(self.team, [_intent("a")])

        assert not self.worker.calls and not self._rows()

    def test_empty_input_writes_nothing(self) -> None:
        assert write_intent_embeddings(self.team, []) == 0
        assert not self.worker.calls and not self._rows()

    @parameterized.expand([("wrong_dimension", [1.0]), ("non_finite", [float("inf")] * 256)])
    def test_rejects_invalid_vectors_before_storing_text(self, _name: str, vector: list[float]) -> None:
        self.worker.replace(
            responses.POST,
            _EMBEDDING_URL,
            body=json.dumps({"embedding": vector, "tokens_used": 3, "did_truncate": False}).replace(
                "Infinity", "1e999"
            ),
        )

        with pytest.raises(ValueError, match="Invalid intent embedding vector"):
            write_intent_embeddings(self.team, [_intent("a")])

        assert not self._rows()

    def test_worker_failure_does_not_store_a_partial_batch(self) -> None:
        self.worker.add(responses.POST, _EMBEDDING_URL, status=500)

        with pytest.raises(HTTPError):
            write_intent_embeddings(self.team, [_intent("a"), _intent("b")])

        assert not self._rows()
