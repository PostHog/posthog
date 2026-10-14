import uuid
import dataclasses
from typing import NamedTuple

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.llm.system_one import (
    NoulAnswer,
    RefusalAnswer,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
    SystemOneResult,
)

from products.error_tracking.backend.models import ErrorTrackingIssueMergeOutcome, ErrorTrackingIssueMergeResult
from products.error_tracking.backend.temporal.fingerprint_embedding_result.activities import (
    _merge_fingerprint_into_closest_issue,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.judge import (
    AutoMergeConfig,
    JudgeUnavailableError,
    JudgeVerdict,
    ask_judge,
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
                f"{ACTIVITIES}.fetch_fingerprint_documents",
                return_value={"candidate": "Error: b"} if documents is None else documents,
            ) as fetch,
            patch(f"{ACTIVITIES}.ask_judge", judge),
        ):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=2, uuid=uuid.uuid4()),
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

        assert run.fetch.call_args.args[1] == "document_embeddings_text_embedding_3_large_3072"
        assert run.fetch.call_args.args[3] == ["candidate"]
        assert run.judge.call_args.args[1:3] == ("Error: a", "Error: b")

    def test_source_text_is_fetched_when_inputs_lack_it(self) -> None:
        run = self._merge(
            0.05,
            JUDGE_ON,
            inputs=_judge_inputs(content=None),
            documents={"test-fingerprint": "Error: stored", "candidate": "Error: b"},
        )

        assert run.fetch.call_args.args[3] == ["test-fingerprint", "candidate"]
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
