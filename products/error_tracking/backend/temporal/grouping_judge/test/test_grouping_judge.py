import threading
import dataclasses
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import httpx
from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from parameterized import parameterized
from temporalio.exceptions import CancelledError

from posthog.clickhouse.client import sync_execute
from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.error_tracking.backend.temporal.fingerprint_embedding_result.judge import (
    DEFAULT_AUTO_MERGE_THRESHOLD,
    AutoMergeConfig,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    AutoMergeOutcome,
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
)
from products.error_tracking.backend.temporal.grouping_judge.algorithms import (
    EMBEDDING_THRESHOLD_V1_DISTANCE,
    LIVE_ALGORITHM,
    decisions_for,
)
from products.error_tracking.backend.temporal.grouping_judge.config import (
    JUDGE_OFF,
    JudgeConfig,
    current_judge_config,
    parse_judge_config,
)
from products.error_tracking.backend.temporal.grouping_judge.inline import (
    _fetch_document_texts,
    grouping_judge_properties,
)
from products.error_tracking.backend.temporal.grouping_judge.judge import judge_pair
from products.error_tracking.backend.temporal.grouping_judge.sampling import band_for, distance_bucket_for, sample_pair

MODULE = "products.error_tracking.backend.temporal.grouping_judge"
REQUEST = httpx.Request("POST", "http://gateway.example.com/v1/messages")
NEW_TEXT = "TypeError: secret customer message\n  at checkout (app.js)"
NEIGHBOUR_TEXT = "TypeError: other customer message\n  at checkout (app.js)"
ALWAYS_JUDGE = JudgeConfig(sample_rate=1.0)
NO_MERGE = AutoMergeOutcome()


def _inputs(team_id: int = 1) -> FingerprintEmbeddingResultInputs:
    return FingerprintEmbeddingResultInputs(
        team_id=team_id,
        fingerprint="fp-new",
        rendering="type_message_and_stack",
        timestamp="2026-10-14T09:00:00Z",
        model_name="text-embedding-3-large-3072",
        embedding=[0.1],
    )


def _tool_response(same_issue: Any, reasoning: str = "same frames") -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use", name="record_verdict", input={"same_issue": same_issue, "reasoning": reasoning}
            )
        ]
    )


def _client_returning(response: Any = None, error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    create = client.with_options.return_value.messages.create
    if error is not None:
        create.side_effect = error
    else:
        create.return_value = response
    return client


class TestAlgorithms(SimpleTestCase):
    @parameterized.expand([("below", 0.0189, "merge"), ("at_threshold", 0.019, "no_merge")])
    def test_live_algorithm_decides_from_distance(self, _name: str, distance: float, expected: str) -> None:
        assert decisions_for(distance) == {LIVE_ALGORITHM.id: expected}

    def test_v1_matches_the_live_auto_merge_threshold(self) -> None:
        assert EMBEDDING_THRESHOLD_V1_DISTANCE == DEFAULT_AUTO_MERGE_THRESHOLD


class TestSampling(SimpleTestCase):
    @parameterized.expand(
        [
            ("below_low_edge", 0.0189, "low", "0.01-0.019"),
            ("at_low_edge", 0.019, "mid", "0.019-0.03"),
            ("at_high_edge", 0.08, "high", "0.08+"),
        ]
    )
    def test_band_and_bucket_edges(self, _name: str, distance: float, band: str, bucket: str) -> None:
        assert (band_for(distance), distance_bucket_for(distance)) == (band, bucket)

    def test_sampling_is_stable_across_retries(self) -> None:
        first = [sample_pair(1, f"fp-{index}", 0.5) for index in range(200)]
        again = [sample_pair(1, f"fp-{index}", 0.5) for index in range(200)]

        assert first == again
        assert 0 < sum(sample.sampled for sample in first) < 200


class TestJudgeConfig(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "this_region",
                {"EU": {"sample_rate": 0.01, "team_ids": [2]}},
                JudgeConfig(sample_rate=0.01, team_ids=frozenset({2})),
            ),
            ("json_string", '{"EU": {"sample_rate": 0.01}}', JudgeConfig(sample_rate=0.01)),
            ("other_region_only", {"US": {"sample_rate": 0.01}}, JUDGE_OFF),
            ("flag_missing_or_fetch_failed", None, JUDGE_OFF),
            ("rate_above_one", {"EU": {"sample_rate": 5}}, JUDGE_OFF),
            ("rate_as_string", {"EU": {"sample_rate": "0.01"}}, JUDGE_OFF),
            ("team_ids_as_strings", {"EU": {"sample_rate": 0.01, "team_ids": ["2"]}}, JUDGE_OFF),
            ("not_json", "{oops", JUDGE_OFF),
        ]
    )
    def test_anything_but_a_valid_entry_for_this_region_is_off(
        self, _name: str, payload: object, expected: JudgeConfig
    ) -> None:
        assert parse_judge_config(payload, "EU") == expected

    def test_off_without_reading_the_flag_when_no_definitions_are_loaded(self) -> None:
        with (
            patch(f"{MODULE}.config.posthoganalytics.feature_flag_definitions", return_value=None),
            patch(f"{MODULE}.config.posthoganalytics.get_feature_flag_payload") as get_payload,
        ):
            assert current_judge_config() == JUDGE_OFF

        get_payload.assert_not_called()


class TestJudgeOutcome(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "server_error",
                APIStatusError("down", response=httpx.Response(503, request=REQUEST), body=None),
                "unavailable",
            ),
            (
                "rate_limited",
                APIStatusError("slow", response=httpx.Response(429, request=REQUEST), body=None),
                "unavailable",
            ),
            ("transport", APIConnectionError(request=REQUEST), "unavailable"),
            ("timeout", APITimeoutError(request=REQUEST), "timeout"),
            (
                "client_error",
                APIStatusError("bad", response=httpx.Response(400, request=REQUEST), body=None),
                "rejected",
            ),
        ]
    )
    def test_errors_are_not_verdicts(self, _name: str, error: Exception, outcome: str) -> None:
        verdict = judge_pair(_client_returning(error=error), document_a="a", document_b="b", timeout_seconds=5)

        assert (verdict.outcome, verdict.same_issue) == (outcome, None)

    @parameterized.expand(
        [
            ("non_bool_answer", _tool_response("yes"), "invalid", None),
            ("no_tool_call", SimpleNamespace(content=[SimpleNamespace(type="text", text="yes")]), "invalid", None),
            ("tool_answer", _tool_response(False), "judged", False),
        ]
    )
    def test_answer_parsing(self, _name: str, response: SimpleNamespace, outcome: str, same_issue: bool | None) -> None:
        verdict = judge_pair(_client_returning(response), document_a="a", document_b="b", timeout_seconds=5)

        assert (verdict.outcome, verdict.same_issue) == (outcome, same_issue)


class TestGroupingJudgeProperties(SimpleTestCase):
    def _run(
        self,
        client: MagicMock,
        *,
        approved: bool | None = True,
        text_rows: list[tuple[str, str]] | None = None,
        rejudge_rate: float = 0.0,
        merge_outcome: AutoMergeOutcome | None = NO_MERGE,
        config: JudgeConfig = ALWAYS_JUDGE,
        input_content: str | None = None,
        closest: list[SimilarFingerprintDistance] | None = None,
    ) -> tuple[dict[str, object], MagicMock, MagicMock]:
        team = MagicMock(id=1)
        team.organization.is_ai_data_processing_approved = approved
        rows = text_rows if text_rows is not None else [("fp-new", NEW_TEXT), ("fp-old", NEIGHBOUR_TEXT)]
        with (
            patch(f"{MODULE}.inline.execute_hogql_query", return_value=MagicMock(results=rows)) as hogql,
            patch(f"{MODULE}.inline.build_ai_gateway_anthropic_client", return_value=client) as build_client,
            patch(f"{MODULE}.sampling.REJUDGE_RATE", rejudge_rate),
            patch(f"{MODULE}.inline.current_judge_config", return_value=config),
        ):
            properties = grouping_judge_properties(
                team,
                dataclasses.replace(_inputs(), content=input_content),
                closest or [SimilarFingerprintDistance(fingerprint="fp-old", distance=0.01)],
                merge_outcome,
            )
        return properties, hogql, build_client

    @parameterized.expand(
        [
            ("disabled", JUDGE_OFF, NO_MERGE),
            ("team_not_listed", JudgeConfig(sample_rate=1.0, team_ids=frozenset({2})), NO_MERGE),
            ("merge_raised", ALWAYS_JUDGE, None),
        ]
    )
    def test_off_makes_no_text_fetch_and_no_call(
        self, _name: str, config: JudgeConfig, merge_outcome: AutoMergeOutcome | None
    ) -> None:
        client = _client_returning(_tool_response(True))

        properties, hogql, build_client = self._run(client, merge_outcome=merge_outcome, config=config)

        assert properties["judge_sampled"] is False
        assert "judge_outcome" not in properties
        hogql.assert_not_called()
        build_client.assert_not_called()

    @parameterized.expand([("not_approved", False), ("unset", None)])
    def test_team_without_ai_consent_is_not_judged(self, _name: str, approved: bool | None) -> None:
        client = _client_returning(_tool_response(True))

        properties, hogql, _ = self._run(client, approved=approved)

        assert properties["judge_outcome"] == "no_consent"
        hogql.assert_not_called()
        client.with_options.return_value.messages.create.assert_not_called()

    @parameterized.expand(
        [
            ("neighbour_missing", [("fp-new", NEW_TEXT)], NEW_TEXT, "no_text"),
            ("new_text_missing_and_not_in_input", [("fp-old", NEIGHBOUR_TEXT)], None, "no_text"),
            ("new_text_not_in_clickhouse_yet", [("fp-old", NEIGHBOUR_TEXT)], NEW_TEXT, "judged"),
        ]
    )
    def test_judges_only_with_both_texts(
        self, _name: str, text_rows: list[tuple[str, str]], input_content: str | None, outcome: str
    ) -> None:
        client = _client_returning(_tool_response(True))

        properties, _, _ = self._run(client, text_rows=text_rows, input_content=input_content)

        create = client.with_options.return_value.messages.create
        assert properties["judge_outcome"] == outcome
        assert create.called is (outcome == "judged")
        if create.called:
            assert "secret customer" in create.call_args.kwargs["messages"][0]["content"]

    def test_rejudge_swaps_order_and_event_carries_no_text_or_reasoning(self) -> None:
        client = _client_returning(_tool_response(True, reasoning="REASONING-MARKER"))

        properties, _, _ = self._run(
            client,
            rejudge_rate=1.0,
            merge_outcome=AutoMergeOutcome(merged_count=1, target_fingerprint="fp-old"),
        )

        first_prompt, second_prompt = (
            call.kwargs["messages"][0]["content"]
            for call in client.with_options.return_value.messages.create.call_args_list
        )
        new_first_in_first_prompt = first_prompt.index("secret customer") < first_prompt.index("other customer")
        assert new_first_in_first_prompt is not properties["judge_swapped"]
        assert new_first_in_first_prompt != (
            second_prompt.index("secret customer") < second_prompt.index("other customer")
        )
        assert {key: value for key, value in properties.items() if key != "judge_duration_ms"} == {
            "live_decision": "merge",
            "live_target_fingerprint": "fp-old",
            "live_merge_decision": None,
            "live_algorithm": "embedding_threshold_v1",
            "live_auto_merge_threshold": 0.019,
            "live_judge_enabled": False,
            "live_judge_shadow": True,
            "live_judge_cutoff": 0.9,
            "live_judge_max_distance": 0.1,
            "decisions": {"embedding_threshold_v1": "merge"},
            "judge_band": "low",
            "distance_bucket": "0.01-0.019",
            "judge_sampled": True,
            "judge_target_fingerprint": "fp-old",
            "judge_outcome": "judged",
            "judge_same_issue": True,
            "judge_swapped": properties["judge_swapped"],
            "judge_rejudge_same_issue": True,
            "judge_model": "claude-haiku-4-5",
            "judge_view": "type_message_and_stack",
        }
        serialized = repr(properties)
        for leaked in ("customer message", "app.js", "REASONING-MARKER"):
            assert leaked not in serialized

    def test_judges_the_pair_the_merge_used_when_it_skipped_rank_one(self) -> None:
        client = _client_returning(_tool_response(True))

        properties, _, _ = self._run(
            client,
            text_rows=[("fp-new", NEW_TEXT), ("fp-old", NEIGHBOUR_TEXT), ("fp-merged", "TypeError: merged target")],
            merge_outcome=AutoMergeOutcome(merged_count=1, target_fingerprint="fp-merged"),
            closest=[
                SimilarFingerprintDistance(fingerprint="fp-old", distance=0.01),
                SimilarFingerprintDistance(fingerprint="fp-merged", distance=0.015),
            ],
        )

        prompt = client.with_options.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
        assert properties["judge_target_fingerprint"] == "fp-merged"
        assert "merged target" in prompt
        assert "other customer" not in prompt

    def test_long_documents_keep_their_throw_site(self) -> None:
        client = _client_returning(_tool_response(True))
        long_stack = "TypeError: boom\n" + "  at outer_caller (app.js)\n" * 500 + "  at THROW_SITE (app.js)\n"

        self._run(client, input_content=long_stack)

        prompt = client.with_options.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "TypeError: boom" in prompt
        assert "THROW_SITE" in prompt

    def test_records_the_merge_config_that_made_the_decision(self) -> None:
        merge_config = AutoMergeConfig(judge_enabled=True, judge_shadow=False)

        with patch(f"{MODULE}.inline.current_judge_config", return_value=JUDGE_OFF):
            properties = grouping_judge_properties(
                MagicMock(id=1),
                _inputs(),
                [SimilarFingerprintDistance(fingerprint="fp-old", distance=0.05)],
                AutoMergeOutcome(merged_count=1, target_fingerprint="fp-old", merge_decision="judge"),
                merge_config,
            )

        assert properties["live_algorithm"] == "auto_merge_config"
        assert properties["live_merge_decision"] == "judge"
        assert (properties["live_judge_enabled"], properties["live_judge_shadow"]) == (True, False)

    @parameterized.expand(
        [
            ("temporal_cancel", CancelledError("Cancelled")),
            ("worker_shutdown", WorkerShuttingDownError("activity-1", "merge", "queue", 1, None, None)),
        ]
    )
    def test_a_drain_during_the_judge_ends_the_judge_not_the_activity(self, _name: str, error: Exception) -> None:
        properties, _, _ = self._run(_client_returning(error=error))

        assert properties["judge_outcome"] == "cancelled"

    def test_skips_the_judge_when_every_worker_is_busy(self) -> None:
        client = _client_returning(_tool_response(True))
        no_free_workers = threading.BoundedSemaphore(1)
        no_free_workers.acquire()

        with patch(f"{MODULE}.inline._free_workers", no_free_workers):
            properties, hogql, _ = self._run(client)

        assert properties["judge_outcome"] == "unavailable"
        hogql.assert_not_called()


class TestFetchDocumentTexts(ClickhouseTestMixin, BaseTest):
    def _insert(self, team_id: int, document_id: str, content: str, timestamp: datetime, inserted_at: datetime) -> None:
        sync_execute(
            """
            INSERT INTO distributed_posthog_document_embeddings_text_embedding_3_large_3072 (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                (
                    team_id,
                    "error_tracking",
                    "fingerprint",
                    "type_message_and_stack",
                    document_id,
                    timestamp,
                    inserted_at,
                    content,
                    "{}",
                    [0.0] * 3072,
                    inserted_at,
                    0,
                    0,
                )
            ],
            flush=False,
            team_id=team_id,
        )

    def test_reads_latest_text_for_this_team_only(self) -> None:
        created = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
        self._insert(self.team.id, "fp-new", "old render", created, created)
        self._insert(self.team.id, "fp-new", "x" * 7000, created, created + timedelta(minutes=1))
        self._insert(self.team.id + 1, "fp-old", "other team text", created - timedelta(days=1), created)

        texts = _fetch_document_texts(self.team, _inputs(self.team.id), "fp-old")

        assert texts == {"fp-new": "x" * 7000}
