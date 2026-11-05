import json
import math
import time
import uuid
import asyncio
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import OperationalError
from django.test import SimpleTestCase
from django.utils import timezone

from asgiref.sync import async_to_sync
from confluent_kafka import KafkaException
from parameterized import parameterized
from prometheus_client import REGISTRY

from products.replay_vision.backend.embeddings import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_PRODUCT,
    OBSERVATION_EMBEDDING_MODEL,
)
from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.models.replay_observation_anchor_similarity import ReplayObservationAnchorSimilarity
from products.replay_vision.backend.models.replay_observation_rank import RankCategory, ReplayObservationRank
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.tests.helpers import axis_anchors, set_rank, snapshot_for
from products.replay_vision.backend.watch_rank import RankRequest
from products.replay_vision.backend.watch_rank_consumer import WatchRankConsumer, parse_rank_request

_WATCH_RANK = "products.replay_vision.backend.watch_rank"
_CONSUMER = "products.replay_vision.backend.watch_rank_consumer"


def _result_message(
    *,
    team_id: int = 7,
    observation_id: str = "obs-1",
    scanner_id: str | None = "scanner-1",
    product: str = EMBEDDING_PRODUCT,
    outcome: str = "success",
    vector: list[float] | None = None,
) -> bytes:
    result: dict[str, Any] = {"model": OBSERVATION_EMBEDDING_MODEL.value, "outcome": outcome}
    if outcome == "success":
        result["embedding"] = [1.0, 0.1, 0.0] if vector is None else vector
    else:
        result["error"] = "provider refused"
    return json.dumps(
        {
            "team_id": team_id,
            "product": product,
            "document_type": EMBEDDING_DOCUMENT_TYPE,
            "rendering": "reasoning",
            "document_id": observation_id,
            "timestamp": "2026-10-24T12:00:00Z",
            "content": "the payment form errored",
            "models": [OBSERVATION_EMBEDDING_MODEL.value],
            "metadata": {} if scanner_id is None else {"scanner_id": scanner_id},
            "results": [result],
        },
        separators=(",", ":"),
    ).encode()


class TestParseRankRequest(SimpleTestCase):
    def test_reads_an_observation_result(self) -> None:
        assert parse_rank_request(_result_message()) == RankRequest(
            team_id=7, scanner_id="scanner-1", observation_id="obs-1", vector=[1.0, 0.1, 0.0]
        )

    @parameterized.expand(
        [
            ("another_product", _result_message(product="error-tracking")),
            ("failed_embedding", _result_message(outcome="failure")),
            ("no_scanner", _result_message(scanner_id=None)),
            ("zero_vector", _result_message(vector=[0.0, 0.0, 0.0])),
            ("not_json", b'{"document_type":"replay-observation"'),
        ]
    )
    def test_skips_what_it_cannot_rank(self, _name: str, value: bytes) -> None:
        assert parse_rank_request(value) is None


class TestWatchRankConsumer(BaseTest):
    _ANCHORS = axis_anchors()

    def _observation(self, scanner: ReplayScanner, session_id: str, **overrides: Any) -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=session_id,
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_snapshot=snapshot_for(scanner),
            **overrides,
        )

    @parameterized.expand(
        [
            ("issue_row_gets_a_rank_and_a_feed_group", None, None, "ranked", RankCategory.FAILURE),
            ("ranking_failure_leaves_no_rank", None, RuntimeError("cache down"), "failed", None),
            ("redelivery_keeps_the_current_rank", "struggle", None, "already_ranked", RankCategory.STRUGGLE),
            ("deleted_observation_is_skipped", None, None, "missing", None),
        ]
    )
    def test_ranks_the_observation_in_a_result(
        self,
        _name: str,
        existing_category: str | None,
        anchor_error: Exception | None,
        outcome: str,
        expected_category: int | None,
    ) -> None:
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name="s",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        observation = self._observation(scanner, "sess-new")
        kept_group = uuid.uuid4()
        if existing_category:
            set_rank(observation, category=existing_category, contrast=0.2, group=kept_group)
        message = _result_message(team_id=self.team.id, observation_id=str(observation.id), scanner_id=str(scanner.id))
        if outcome == "missing":
            observation.delete()

        with (
            patch(f"{_WATCH_RANK}.anchor_vectors", AsyncMock(side_effect=anchor_error, return_value=self._ANCHORS)),
            patch(f"{_CONSUMER}._RETRY_WINDOW_S", 0),
            patch(f"{_CONSUMER}._ERROR_RETRY_WINDOW_S", 0),
            # It would close the connection that holds the test transaction.
            patch(f"{_CONSUMER}.close_old_connections"),
        ):
            assert async_to_sync(WatchRankConsumer(MagicMock()).handle)(message, math.inf) == outcome

        if outcome == "missing":
            return
        rank = ReplayObservationRank.objects.for_team(self.team.id).filter(observation_id=observation.id).first()
        if expected_category is None:
            assert rank is None
            return
        assert rank is not None
        assert rank.category == expected_category
        assert rank.feed_group_id is not None and (rank.feed_group_id == kept_group) == bool(existing_category)
        # A redelivery returns before ranking, so only a fresh rank writes the similarity row.
        assert ReplayObservationAnchorSimilarity.objects.for_team(self.team.id).filter(
            observation=observation
        ).exists() == (outcome == "ranked")

    @parameterized.expand(
        [
            # A revoked partition stops the batch, and the rest of it is read again rather than skipped.
            ("revoked_partition", KafkaException("partition revoked"), "ranked", [0], 1),
            # A message still failing at the end of the batch budget goes back to Kafka unstored.
            ("deferred_retry", None, "deferred", [], 0),
        ]
    )
    def test_unfinished_messages_are_read_again(
        self, _name: str, store_error: Exception | None, outcome: str, stored: list[int], rewind_from: int
    ) -> None:
        messages = [
            MagicMock(
                **{
                    "error.return_value": None,
                    "timestamp.return_value": (1, 0),
                    "value.return_value": b"{}",
                    "topic.return_value": "results",
                    "partition.return_value": 0,
                    "offset.return_value": offset,
                }
            )
            for offset in range(3)
        ]
        consumer = MagicMock(**{"store_offsets.side_effect": store_error})

        with patch.object(WatchRankConsumer, "handle", AsyncMock(return_value=outcome)):
            async_to_sync(WatchRankConsumer(MagicMock()).process_batch)(consumer, messages)

        assert [c.kwargs["message"] for c in consumer.store_offsets.call_args_list] == [messages[i] for i in stored]
        (seek,) = consumer.seek.call_args_list
        assert seek.args[0].offset == rewind_from

    def test_a_deferred_failure_keeps_its_retry_window_in_the_next_batch(self) -> None:
        consumer = WatchRankConsumer(MagicMock())
        message = _result_message()

        with (
            patch(f"{_CONSUMER}.rank_observation", AsyncMock(side_effect=RuntimeError("postgres down"))),
            patch(f"{_CONSUMER}.close_old_connections"),
        ):
            for _ in range(2):
                assert async_to_sync(consumer.handle)(message, time.monotonic()) == "deferred"


class TestWatchRankConsumerRetries(SimpleTestCase):
    @parameterized.expand(
        [
            # The database being away waits out the full window, so a short outage costs no ranks.
            ("database_error_keeps_retrying", OperationalError("server closed the connection"), "deferred"),
            # Any other error holds every partition behind it, so it gives up after the short window.
            ("other_error_gives_up_sooner", ValueError("bad vector"), "failed"),
        ]
    )
    def test_a_failure_gives_up_after_the_window_for_its_kind(self, _name: str, error: Exception, outcome: str) -> None:
        consumer = WatchRankConsumer(MagicMock())
        consumer._first_failed_at["obs-1"] = time.monotonic() - 90

        with (
            patch(f"{_CONSUMER}.rank_observation", AsyncMock(side_effect=error)),
            patch(f"{_CONSUMER}.close_old_connections"),
        ):
            assert async_to_sync(consumer.handle)(_result_message(), time.monotonic()) == outcome

    def test_a_hung_naming_call_counts_a_timeout(self) -> None:
        async def never_returns(*_args: Any) -> None:
            await asyncio.Event().wait()

        def timeouts() -> float:
            labels = {"outcome": "timeout"}
            return REGISTRY.get_sample_value("replay_vision_watch_rank_consumer_theme_naming_total", labels) or 0.0

        before = timeouts()
        with (
            patch(f"{_CONSUMER}.name_theme", never_returns),
            patch(f"{_CONSUMER}._NAMING_TIMEOUT_S", 0.01),
        ):
            async_to_sync(WatchRankConsumer._name)(7, uuid.uuid4(), timezone.now())

        assert timeouts() == before + 1
