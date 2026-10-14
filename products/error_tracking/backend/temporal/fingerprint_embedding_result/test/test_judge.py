import uuid
import dataclasses
from typing import NamedTuple

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from temporalio.exceptions import CancelledError

from posthog.llm.system_one import (
    NoulAnswer,
    RefusalAnswer,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
    SystemOneResult,
)

from products.error_tracking.backend.models import ErrorTrackingIssueMergeOutcome, ErrorTrackingIssueMergeResult
from products.error_tracking.backend.temporal.fingerprint_embedding_result.activities import (
    _fetch_fingerprint_documents,
    _merge_fingerprint_into_closest_issue,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.judge import (
    AutoMergeConfig,
    JudgeUnavailableError,
    JudgeVerdict,
    ask_judge,
    judge_state,
    load_auto_merge_config,
    parse_auto_merge_config,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
)

ACTIVITIES = "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities"
JUDGE = "products.error_tracking.backend.temporal.fingerprint_embedding_result.judge"

JUDGE_ON = AutoMergeConfig(
    auto_merge_threshold=0.005, judge_enabled=True, judge_max_distance=0.3, judge_cutoff=0.8, judge_shadow=False
)


class TestParseAutoMergeConfig:
    def test_no_payload_keeps_todays_rule(self) -> None:
        config = parse_auto_merge_config(None)

        assert config == AutoMergeConfig()
        assert config.auto_merge_threshold == 0.019
        assert config.judge_enabled is False

    def test_full_payload(self) -> None:
        config = parse_auto_merge_config(
            {
                "auto_merge_threshold": 0.005,
                "judge": {"enabled": True, "max_distance": 0.3, "cutoff": 0.8, "shadow": False, "timeout_seconds": 5},
            }
        )

        assert config == AutoMergeConfig(
            auto_merge_threshold=0.005,
            judge_enabled=True,
            judge_max_distance=0.3,
            judge_cutoff=0.8,
            judge_shadow=False,
            judge_timeout_seconds=5.0,
        )

    @parameterized.expand(
        [
            ("threshold_out_of_range", {"auto_merge_threshold": 2}, "auto_merge_threshold", 0.019),
            ("threshold_not_a_number", {"auto_merge_threshold": "0.01"}, "auto_merge_threshold", 0.019),
            ("cutoff_bool", {"judge": {"cutoff": True}}, "judge_cutoff", 0.9),
            ("enabled_must_be_true", {"judge": {"enabled": "yes"}}, "judge_enabled", False),
            ("shadow_on_unless_false", {"judge": {"shadow": 0}}, "judge_shadow", True),
            ("timeout_too_long", {"judge": {"timeout_seconds": 600}}, "judge_timeout_seconds", 10.0),
        ]
    )
    def test_invalid_field_falls_back_to_default(self, _name: str, payload: dict, field: str, expected: object) -> None:
        assert getattr(parse_auto_merge_config(payload), field) == expected

    def test_inverted_band_disables_the_judge(self) -> None:
        config = parse_auto_merge_config(
            {"auto_merge_threshold": 0.05, "judge": {"enabled": True, "max_distance": 0.01}}
        )

        assert config.judge_enabled is False

    def test_load_falls_back_when_flag_evaluation_fails(self) -> None:
        with patch(f"{JUDGE}.posthoganalytics.get_feature_flag_payload", side_effect=RuntimeError("boom")):
            assert load_auto_merge_config(MagicMock(id=1, uuid=uuid.uuid4(), organization_id=uuid.uuid4())) == (
                AutoMergeConfig()
            )


def _judge_inputs(content: str | None = "Error: a") -> FingerprintEmbeddingResultInputs:
    return FingerprintEmbeddingResultInputs(
        team_id=2,
        fingerprint="test-fingerprint",
        rendering="type_message_and_stack",
        timestamp="2026-06-08T00:00:00Z",
        model_name="text-embedding-3-large-3072",
        embedding=[0.1],
        content=content,
    )


class TestAskJudge:
    def _ask(self, result: SystemOneResult | Exception) -> tuple[JudgeVerdict, MagicMock, MagicMock]:
        client = MagicMock()
        if isinstance(result, Exception):
            client.decide.side_effect = result
        else:
            client.decide.return_value = result
        with patch(f"{JUDGE}.build_system_one_client", return_value=client) as build:
            verdict = ask_judge(7, "Error: a", "Error: b", timeout_seconds=3)
        return verdict, build, client

    def test_returns_the_noul_probability(self) -> None:
        verdict, build, client = self._ask(
            SystemOneResult(model="jeeves-0.1", answers={"same_issue": NoulAnswer(probability=0.87)}, input_tokens=10)
        )

        assert verdict.score == pytest.approx(0.87)
        assert build.call_args.kwargs == {
            "model": "posthog/hogference/jeeves-0.1",
            "ai_product": "error_tracking",
            "team_id": 7,
            "timeout": 3,
        }
        assert "<document_a>\nError: a\n</document_a>" in client.decide.call_args.kwargs["state"]

    def test_refusal_is_unavailable(self) -> None:
        with pytest.raises(JudgeUnavailableError, match="refused"):
            self._ask(SystemOneResult(model="jeeves-0.1", answers={"same_issue": RefusalAnswer()}, input_tokens=10))

    @parameterized.expand(
        [
            ("not_configured", SystemOneNotConfigured("no gateway")),
            ("request_failed", SystemOneRequestFailed("rate limited", status_code=429)),
        ]
    )
    def test_gateway_failures_are_unavailable(self, _name: str, error: Exception) -> None:
        with pytest.raises(JudgeUnavailableError):
            self._ask(error)


class MergeRun(NamedTuple):
    merged_count: int
    target_issue: MagicMock
    judge: MagicMock
    fetch: MagicMock
    events: dict[str, dict]


class TestMergeWithJudge:
    def _merge(
        self,
        distance: float,
        config: AutoMergeConfig,
        score: float | Exception = 0.95,
        documents: dict[str, str] | None = None,
        inputs: FingerprintEmbeddingResultInputs | None = None,
        consent: bool = True,
        fetch_error: Exception | None = None,
    ) -> MergeRun:
        source = MagicMock(issue_id=uuid.uuid4(), fingerprint="test-fingerprint")
        target_issue = MagicMock()
        target_issue.merge.return_value = ErrorTrackingIssueMergeOutcome(ErrorTrackingIssueMergeResult.MERGED)
        target = MagicMock(issue_id=uuid.uuid4(), issue=target_issue, fingerprint="candidate")
        query = MagicMock()
        query.select_related.return_value.order_by.return_value = [target, source]
        capture = MagicMock()
        judge = (
            MagicMock(side_effect=score)
            if isinstance(score, Exception)
            else MagicMock(return_value=JudgeVerdict(score=score, latency_ms=12.0))
        )
        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(f"{ACTIVITIES}.ErrorTrackingIssueFingerprintV2.objects.filter", return_value=query),
            patch(f"{ACTIVITIES}.ph_background_capture", return_value=capture),
            patch(f"{ACTIVITIES}.groups", return_value={}),
            patch(
                f"{ACTIVITIES}._fetch_fingerprint_documents",
                return_value={"candidate": "Error: b"} if documents is None else documents,
                side_effect=fetch_error,
            ) as fetch,
            patch(f"{ACTIVITIES}.capture_exception"),
            patch(f"{ACTIVITIES}.ask_judge", judge),
        ):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=2, uuid=uuid.uuid4(), organization=MagicMock(is_ai_data_processing_approved=consent)),
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="candidate", distance=distance)],
                config=config,
                judge_inputs=inputs or _judge_inputs(),
            )
        events = {call.kwargs["event"]: call.kwargs["properties"] for call in capture.call_args_list}
        return MergeRun(result.merged_count, target_issue, judge, fetch, events)

    def test_auto_merge_below_threshold_skips_the_judge(self) -> None:
        run = self._merge(0.004, JUDGE_ON)

        assert run.merged_count == 1
        run.judge.assert_not_called()
        assert run.events["error_tracking_issue_merged"]["merge_decision"] == "distance"

    def test_judge_merges_at_or_above_cutoff(self) -> None:
        run = self._merge(0.05, JUDGE_ON, score=0.8)

        assert run.merged_count == 1
        run.target_issue.merge.assert_called_once()
        merged = run.events["error_tracking_issue_merged"]
        assert merged["merge_decision"] == "judge"
        assert merged["judge_score"] == 0.8
        assert run.events["error_tracking_auto_merge_judged"]["would_merge"] is True

    def test_source_text_from_inputs_is_not_read_back(self) -> None:
        run = self._merge(0.05, JUDGE_ON)

        assert run.fetch.call_args.args[2] == ["candidate"]
        assert run.judge.call_args.args[1:3] == ("Error: a", "Error: b")

    def test_source_text_is_fetched_when_inputs_lack_it(self) -> None:
        run = self._merge(
            0.05,
            JUDGE_ON,
            inputs=_judge_inputs(content=None),
            documents={"test-fingerprint": "Error: stored", "candidate": "Error: b"},
        )

        assert run.fetch.call_args.args[2] == ["test-fingerprint", "candidate"]
        assert run.judge.call_args.args[1] == "Error: stored"

    def test_judge_below_cutoff_does_not_merge(self) -> None:
        run = self._merge(0.05, JUDGE_ON, score=0.79)

        assert run.merged_count == 0
        run.target_issue.merge.assert_not_called()
        assert run.events["error_tracking_auto_merge_judged"]["would_merge"] is False
        assert "error_tracking_issue_merged" not in run.events

    def test_shadow_mode_reports_but_never_merges(self) -> None:
        run = self._merge(0.05, dataclasses.replace(JUDGE_ON, judge_shadow=True), score=0.99)

        assert run.merged_count == 0
        run.target_issue.merge.assert_not_called()
        judged = run.events["error_tracking_auto_merge_judged"]
        assert judged["would_merge"] is True
        assert judged["judge_shadow"] is True

    def test_beyond_max_distance_is_never_judged(self) -> None:
        run = self._merge(0.31, JUDGE_ON)

        assert run.merged_count == 0
        run.judge.assert_not_called()
        run.fetch.assert_not_called()
        assert run.events == {}

    def test_judge_disabled_keeps_todays_rule(self) -> None:
        run = self._merge(0.05, AutoMergeConfig())

        assert run.merged_count == 0
        run.judge.assert_not_called()

    def test_judge_failure_leaves_fingerprint_unmerged(self) -> None:
        run = self._merge(0.05, JUDGE_ON, score=JudgeUnavailableError("timeout"))

        assert run.merged_count == 0
        run.target_issue.merge.assert_not_called()
        judged = run.events["error_tracking_auto_merge_judged"]
        assert judged["judge_score"] is None
        assert judged["judge_error"] == "timeout"

    def test_missing_neighbour_document_is_reported_without_calling_the_judge(self) -> None:
        run = self._merge(0.05, JUDGE_ON, documents={})

        assert run.merged_count == 0
        run.judge.assert_not_called()
        assert run.events["error_tracking_auto_merge_judged"]["judge_error"] == "missing_document"

    def test_without_ai_consent_no_document_is_sent(self) -> None:
        run = self._merge(0.05, JUDGE_ON, consent=False)

        assert run.merged_count == 0
        run.fetch.assert_not_called()
        run.judge.assert_not_called()
        assert run.events["error_tracking_auto_merge_judged"]["judge_error"] == "ai_processing_not_approved"

    def test_document_fetch_failure_is_an_unavailable_verdict(self) -> None:
        run = self._merge(0.05, JUDGE_ON, fetch_error=RuntimeError("clickhouse timeout"))

        assert run.merged_count == 0
        run.judge.assert_not_called()
        assert run.events["error_tracking_auto_merge_judged"]["judge_error"] == "document_fetch_failed"

    def test_cancellation_during_document_fetch_is_reraised(self) -> None:
        with pytest.raises(CancelledError):
            self._merge(0.05, JUDGE_ON, fetch_error=CancelledError("Cancelled"))


class TestJudgeDocuments:
    def test_documents_query_uses_the_model_table_and_search_window(self) -> None:
        with (
            patch(f"{ACTIVITIES}.parse_select") as parse_select,
            patch(f"{ACTIVITIES}.execute_hogql_query", return_value=MagicMock(results=[("candidate", "Error: b")])),
        ):
            documents = _fetch_fingerprint_documents(MagicMock(id=2), _judge_inputs(), ["candidate"])

        assert documents == {"candidate": "Error: b"}
        query = parse_select.call_args.args[0]
        assert "FROM document_embeddings_text_embedding_3_large_3072" in query
        assert "timestamp >= {min_timestamp}" in query
        assert parse_select.call_args.kwargs["placeholders"]["fingerprints"].value == ["candidate"]

    def test_long_documents_keep_the_message_and_the_throw_site(self) -> None:
        document = "TypeError: boom\n" + "outer frame\n" * 1000 + "throwSite in app.js line 1"

        state = judge_state(document, "short")

        assert "TypeError: boom" in state
        assert "throwSite in app.js line 1" in state
        assert "[... frames omitted ...]" in state
