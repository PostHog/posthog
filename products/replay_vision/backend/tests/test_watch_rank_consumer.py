import json
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

import numpy as np
from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.replay_vision.backend.embeddings import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_PRODUCT,
    OBSERVATION_EMBEDDING_MODEL,
)
from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.tests.helpers import snapshot_for
from products.replay_vision.backend.watch_rank_consumer import RankRequest, WatchRankConsumer, parse_rank_request

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
        result["embedding"] = vector or [1.0, 0.1, 0.0]
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
        }
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
            ("not_json", b"{"),
        ]
    )
    def test_skips_what_it_cannot_rank(self, _name: str, value: bytes) -> None:
        assert parse_rank_request(value) is None


class TestWatchRankConsumer(BaseTest):
    _ANCHORS = {
        "failure": np.array([[1.0, 0.0, 0.0]]),
        "struggle": np.array([[0.0, 1.0, 0.0]]),
        "revenue": np.array([[0.0, -1.0, 0.0]]),
        "routine": np.array([[0.0, 0.0, 1.0]]),
    }

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
            ("duplicate_points_at_the_group_root", None, "ranked", "root-id"),
            ("ranking_failure_leaves_no_rank", RuntimeError("clickhouse down"), "failed", None),
        ]
    )
    def test_ranks_the_observation_in_a_result(
        self, _name: str, nearest_error: Exception | None, outcome: str, expected_duplicate_of: str | None
    ) -> None:
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name="s",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        neighbour = self._observation(scanner, "sess-earlier", watch_rank={"duplicate_of": "root-id"})
        observation = self._observation(scanner, "sess-new")
        nearest = MagicMock(side_effect=nearest_error, return_value=(str(neighbour.id), 0.05))
        message = _result_message(team_id=self.team.id, observation_id=str(observation.id), scanner_id=str(scanner.id))

        with (
            patch(f"{_WATCH_RANK}.anchor_vectors", AsyncMock(return_value=self._ANCHORS)),
            patch(f"{_WATCH_RANK}.nearest_earlier_observation", nearest),
            patch(f"{_CONSUMER}.asyncio.sleep", AsyncMock()),
        ):
            assert async_to_sync(WatchRankConsumer(MagicMock()).handle)(message) == outcome

        observation.refresh_from_db()
        if expected_duplicate_of is None:
            assert observation.watch_rank is None
        else:
            rank = observation.watch_rank
            assert rank is not None
            assert rank["category"] == "failure"
            assert rank["duplicate_of"] == expected_duplicate_of
