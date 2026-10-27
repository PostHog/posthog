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
    _fetch_fingerprint_document,
    _merge_fingerprint_into_closest_issue,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.judge import (
    JEEVES_MODEL,
    JEVK5_MODEL,
    AutoMergeConfig,
    JudgeModel,
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


def _inputs(content: str | None = "Error: a") -> FingerprintEmbeddingResultInputs:
    return FingerprintEmbeddingResultInputs(
        team_id=2,
        fingerprint="test-fingerprint",
        rendering="type_message_and_stack",
        timestamp="2026-06-08T00:00:00Z",
        model_name="text-embedding-3-large-3072",
        embedding=[0.1],
        content=content,
    )


class TestAutoMergeConfig:
    def test_no_payload_keeps_todays_rule(self) -> None:
        assert parse_auto_merge_config(None) == AutoMergeConfig(auto_merge_threshold=0.019, judge_enabled=False)

    @parameterized.expand(
        [
            ("no_model", {}, JEEVES_MODEL),
            ("selected_model", {"model": JEVK5_MODEL}, JEVK5_MODEL),
        ]
    )
    def test_full_payload(self, _name: str, model_payload: dict[str, str], expected_model: JudgeModel) -> None:
        payload = {
            "auto_merge_threshold": 0.005,
            "judge": {
                "enabled": True,
                **model_payload,
                "max_distance": 0.3,
                "cutoff": 0.8,
                "shadow": False,
                "timeout_seconds": 5,
            },
        }

        assert parse_auto_merge_config(payload) == AutoMergeConfig(
            auto_merge_threshold=0.005,
            judge_enabled=True,
            judge_model=expected_model,
            judge_max_distance=0.3,
            judge_cutoff=0.8,
            judge_shadow=False,
            judge_timeout_seconds=5.0,
        )

    @parameterized.expand(
        [
            ("out_of_range", {"auto_merge_threshold": 2}, "auto_merge_threshold", 0.019),
            ("not_a_number", {"judge": {"cutoff": "0.8"}}, "judge_cutoff", 0.9),
            ("enabled_must_be_true", {"judge": {"enabled": "yes"}}, "judge_enabled", False),
            ("shadow_unless_false", {"judge": {"shadow": 0}}, "judge_shadow", True),
            ("unknown_model", {"judge": {"enabled": True, "model": "other", "cutoff": 0.8}}, "judge_enabled", False),
            ("model_without_cutoff", {"judge": {"enabled": True, "model": JEVK5_MODEL}}, "judge_enabled", False),
            (
                "model_with_invalid_cutoff",
                {"judge": {"enabled": True, "model": JEVK5_MODEL, "cutoff": "0.8"}},
                "judge_enabled",
                False,
            ),
        ]
    )
    def test_invalid_field_keeps_its_default(self, _name: str, payload: dict, field: str, expected: object) -> None:
        assert getattr(parse_auto_merge_config(payload), field) == expected

    def test_inverted_band_disables_the_judge(self) -> None:
        payload = {"auto_merge_threshold": 0.05, "judge": {"enabled": True, "max_distance": 0.01}}

        assert parse_auto_merge_config(payload).judge_enabled is False

    def test_flag_failure_keeps_todays_rule(self) -> None:
        with patch(f"{JUDGE}.posthoganalytics.get_feature_flag_payload", side_effect=RuntimeError("boom")):
            config = load_auto_merge_config(MagicMock(id=1, uuid=uuid.uuid4(), organization_id=uuid.uuid4()))

        assert config == AutoMergeConfig()


class TestAskJudge:
    def _ask(
        self, result: SystemOneResult | Exception, model: JudgeModel | None = None
    ) -> tuple[JudgeVerdict, MagicMock, MagicMock]:
        client = MagicMock()
        if isinstance(result, Exception):
            client.decide.side_effect = result
        else:
            client.decide.return_value = result
        with patch(f"{JUDGE}.build_system_one_client", return_value=client) as build:
            if model is None:
                verdict = ask_judge(7, "Error: a", "Error: b", timeout_seconds=3)
            else:
                verdict = ask_judge(7, "Error: a", "Error: b", timeout_seconds=3, model=model)
        return verdict, build, client

    @parameterized.expand(
        [
            ("default", None, JEEVES_MODEL),
            ("selected", JEVK5_MODEL, JEVK5_MODEL),
        ]
    )
    def test_returns_the_noul_probability(self, _name: str, model: JudgeModel | None, expected: JudgeModel) -> None:
        verdict, build, client = self._ask(
            SystemOneResult(model=expected, answers={"same_issue": NoulAnswer(probability=0.87)}, input_tokens=10),
            model=model,
        )

        assert verdict.score == pytest.approx(0.87)
        assert build.call_args.kwargs == {
            "model": expected,
            "ai_product": "error_tracking",
            "team_id": 7,
            "timeout": 3,
        }
        assert "<document_a>\nError: a\n</document_a>" in client.decide.call_args.kwargs["state"]

    @parameterized.expand(
        [
            (
                "refusal",
                SystemOneResult(model="jevk5-fp8-0.2", answers={"same_issue": RefusalAnswer()}, input_tokens=1),
            ),
            ("not_configured", SystemOneNotConfigured("no gateway")),
            ("request_failed", SystemOneRequestFailed("rate limited", status_code=429)),
        ]
    )
    def test_no_answer_is_unavailable(self, _name: str, result: SystemOneResult | Exception) -> None:
        with pytest.raises(JudgeUnavailableError):
            self._ask(result)

    def test_long_documents_keep_the_message_and_the_throw_site(self) -> None:
        document = "TypeError: boom\n" + "outer frame\n" * 1000 + "throwSite in app.js line 1"

        state = judge_state(document, "short")

        assert "TypeError: boom" in state
        assert "throwSite in app.js line 1" in state


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
        config: AutoMergeConfig = JUDGE_ON,
        score: float | Exception = 0.95,
        neighbour_document: str | None | Exception = "Error: b",
        inputs: FingerprintEmbeddingResultInputs | None = None,
        consent: bool = True,
    ) -> MergeRun:
        source = MagicMock(issue_id=uuid.uuid4(), fingerprint="test-fingerprint")
        target_issue = MagicMock()
        target_issue.merge.return_value = ErrorTrackingIssueMergeOutcome(ErrorTrackingIssueMergeResult.MERGED)
        target = MagicMock(issue_id=uuid.uuid4(), issue=target_issue, fingerprint="candidate")
        query = MagicMock()
        query.select_related.return_value.order_by.return_value = [target, source]
        capture = MagicMock()
        judge = MagicMock()
        if isinstance(score, Exception):
            judge.side_effect = score
        else:
            judge.return_value = JudgeVerdict(score=score, latency_ms=12.0)
        fetch = MagicMock()
        if isinstance(neighbour_document, Exception):
            fetch.side_effect = neighbour_document
        else:
            fetch.return_value = neighbour_document
        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(f"{ACTIVITIES}.ErrorTrackingIssueFingerprintV2.objects.filter", return_value=query),
            patch(f"{ACTIVITIES}.ph_background_capture", return_value=capture),
            patch(f"{ACTIVITIES}.groups", return_value={}),
            patch(f"{ACTIVITIES}._fetch_fingerprint_document", fetch),
            patch(f"{ACTIVITIES}.capture_exception"),
            patch(f"{ACTIVITIES}.ask_judge", judge),
        ):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=2, uuid=uuid.uuid4(), organization=MagicMock(is_ai_data_processing_approved=consent)),
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="candidate", distance=distance)],
                config=config,
                judge_inputs=inputs or _inputs(),
            )
        events = {call.kwargs["event"]: call.kwargs["properties"] for call in capture.call_args_list}
        return MergeRun(result.merged_count, target_issue, judge, fetch, events)

    def test_below_the_threshold_merges_without_the_judge(self) -> None:
        run = self._merge(0.004)

        assert run.merged_count == 1
        run.judge.assert_not_called()
        assert run.events["error_tracking_issue_merged"]["merge_decision"] == "distance"

    def test_judge_merges_at_the_cutoff(self) -> None:
        run = self._merge(0.05, score=0.8)

        assert run.merged_count == 1
        assert run.fetch.call_args.args[2] == "candidate"
        assert run.judge.call_args.args[1:3] == ("Error: a", "Error: b")
        merged = run.events["error_tracking_issue_merged"]
        assert (merged["merge_decision"], merged["judge_score"]) == ("judge", 0.8)

    def test_selected_model_is_used_and_reported(self) -> None:
        run = self._merge(0.05, config=dataclasses.replace(JUDGE_ON, judge_model=JEVK5_MODEL))

        assert run.judge.call_args.kwargs["model"] == JEVK5_MODEL
        assert run.events["error_tracking_auto_merge_judged"]["judge_model"] == JEVK5_MODEL
        assert run.events["error_tracking_issue_merged"]["judge_model"] == JEVK5_MODEL

    def test_judge_below_the_cutoff_does_not_merge(self) -> None:
        run = self._merge(0.05, score=0.79)

        assert run.merged_count == 0
        assert run.events["error_tracking_auto_merge_judged"]["would_merge"] is False
        assert "error_tracking_issue_merged" not in run.events

    def test_shadow_mode_reports_but_never_merges(self) -> None:
        run = self._merge(0.05, config=dataclasses.replace(JUDGE_ON, judge_shadow=True), score=0.99)

        assert run.merged_count == 0
        run.target_issue.merge.assert_not_called()
        assert run.events["error_tracking_auto_merge_judged"]["would_merge"] is True

    def test_beyond_the_cap_is_never_judged(self) -> None:
        run = self._merge(0.31)

        assert run.merged_count == 0
        run.judge.assert_not_called()
        assert run.events == {}

    @parameterized.expand(
        [
            ("no_ai_consent", {"consent": False}, "ai_processing_not_approved"),
            ("fetch_failed", {"neighbour_document": RuntimeError("clickhouse timeout")}, "document_fetch_failed"),
            ("no_neighbour_document", {"neighbour_document": None}, "missing_document"),
            ("no_source_text", {"inputs": _inputs(content=None)}, "missing_document"),
            ("judge_unavailable", {"score": JudgeUnavailableError("timeout")}, "timeout"),
        ]
    )
    def test_unavailable_judge_leaves_the_fingerprint_unmerged(self, _name: str, kwargs: dict, error: str) -> None:
        run = self._merge(0.05, **kwargs)

        assert run.merged_count == 0
        run.target_issue.merge.assert_not_called()
        judged = run.events["error_tracking_auto_merge_judged"]
        assert (judged["judge_score"], judged["judge_error"]) == (None, error)

    def test_lookup_and_inference_share_the_judge_timeout(self) -> None:
        with patch(f"{ACTIVITIES}.time.monotonic", side_effect=[100.0, 104.0]):
            run = self._merge(0.05)

        assert run.fetch.call_args.kwargs == {"timeout_seconds": 10.0}
        assert run.judge.call_args.args[3] == pytest.approx(6.0)
        assert run.judge.call_args.kwargs["model"] == JUDGE_ON.judge_model

    def test_exhausted_budget_skips_the_inference(self) -> None:
        with patch(f"{ACTIVITIES}.time.monotonic", side_effect=[100.0, 111.0]):
            run = self._merge(0.05)

        run.judge.assert_not_called()
        assert run.events["error_tracking_auto_merge_judged"]["judge_error"] == "judge_timeout"

    def test_cancellation_during_the_document_fetch_is_reraised(self) -> None:
        with pytest.raises(CancelledError):
            self._merge(0.05, neighbour_document=CancelledError("Cancelled"))

    def test_document_query_uses_the_model_table_and_search_window(self) -> None:
        with (
            patch(f"{ACTIVITIES}.parse_select") as parse_select,
            patch(
                f"{ACTIVITIES}.execute_hogql_query", return_value=MagicMock(results=[("candidate", "Error: b")])
            ) as execute,
        ):
            document = _fetch_fingerprint_document(MagicMock(id=2), _inputs(), "candidate", timeout_seconds=2.5)

        assert document == "Error: b"
        assert execute.call_args.kwargs["settings"].max_execution_time == 3
        query = parse_select.call_args.args[0]
        assert "FROM document_embeddings_text_embedding_3_large_3072" in query
        assert "timestamp >= {min_timestamp}" in query
