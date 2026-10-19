from __future__ import annotations

import os
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

import httpx
from autoevals import init
from openai import AsyncOpenAI
from parameterized import parameterized
from posthoganalytics import Posthog

from products.marketing_analytics.evals.definition_calibration_cases import definition_calibration_cases
from products.marketing_analytics.evals.definition_evidence import (
    DEFINITION_JUDGE_VERSION,
    ConversionDefinitionEvidence,
    DefinitionChecks,
)
from products.marketing_analytics.evals.run_definition_calibration import (
    CalibrationJudgment,
    _write_report,
    calibration_summary,
    confusion_matrix,
    run_calibration,
)
from products.posthog_ai.eval_harness.scorers import JUDGE_MODEL
from products.posthog_ai.eval_harness.scorers.contract import Score
from products.posthog_ai.eval_harness.scorers.tracing import TracedScorer, create_traced_scorer_clients
from products.posthog_ai.eval_harness.trace_events import DISTINCT_ID


class TestDefinitionCalibration(SimpleTestCase):
    def test_confusion_matrix_excludes_judge_errors_from_quality(self) -> None:
        judgments = [
            CalibrationJudgment(case_name="tp", error_class="filters", gold_pass=True, actual_pass=True, metadata={}),
            CalibrationJudgment(case_name="tn", error_class="filters", gold_pass=False, actual_pass=False, metadata={}),
            CalibrationJudgment(case_name="fp", error_class="filters", gold_pass=False, actual_pass=True, metadata={}),
            CalibrationJudgment(case_name="fn", error_class="filters", gold_pass=True, actual_pass=False, metadata={}),
            CalibrationJudgment(
                case_name="error", error_class="filters", gold_pass=False, actual_pass=None, metadata={}, error="Quota"
            ),
        ]
        assert confusion_matrix(judgments) == {
            "true_positive": 1,
            "true_negative": 1,
            "false_positive": 1,
            "false_negative": 1,
            "measured": 4,
            "errors": 1,
            "accuracy": 0.5,
            "false_positive_rate": 0.5,
            "false_negative_rate": 0.5,
        }
        report = calibration_summary(judgments, planned=5, sources_unchanged=True)
        assert report["complete"] is False
        assert report["calibration_passed"] is False
        assert report["by_error_class"] == {"filters": report["confusion_matrix"]}

    @parameterized.expand(
        [
            ("all_correct", 0, 0, 20, True, True),
            ("false_positive_limit", 1, 0, 20, True, False),
            ("false_negative_boundary", 0, 1, 20, True, True),
            ("accuracy_boundary", 0, 2, 20, True, False),
            ("incomplete", 0, 0, 21, True, False),
            ("changed_sources", 0, 0, 20, False, False),
        ]
    )
    def test_gate_requires_completion_and_both_error_rates(
        self, _name: str, fp: int, fn: int, planned: int, unchanged: bool, expected: bool
    ) -> None:
        judgments = [
            CalibrationJudgment(
                case_name=f"case_{index}",
                error_class="synthetic",
                gold_pass=index < 10,
                actual_pass=index >= fn if index < 10 else index < 10 + fp,
                metadata={},
            )
            for index in range(20)
        ]
        assert (
            calibration_summary(judgments, planned=planned, sources_unchanged=unchanged)["calibration_passed"]
            is expected
        )

    @parameterized.expand([("interrupted", KeyboardInterrupt), ("write_failure", OSError)])
    def test_failed_checkpoint_preserves_previous_report(self, _name: str, failure: type[BaseException]) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            _write_report(path, {"trials": [{"case": "completed"}]})
            with patch("products.marketing_analytics.evals.report_writer.os.fsync", side_effect=failure):
                with self.assertRaises(failure):
                    _write_report(path, {"trials": [{"case": "completed"}, {"case": "next"}]})
            assert json.loads(path.read_text()) == {"trials": [{"case": "completed"}]}
            assert list(Path(directory).iterdir()) == [path]
            _write_report(path, {"trials": [{"case": "completed"}, {"case": "next"}]})
            assert len(json.loads(path.read_text())["trials"]) == 2

    async def test_dry_run_leaves_calibration_unmeasured(self) -> None:
        with (
            TemporaryDirectory() as directory,
            patch("products.marketing_analytics.evals.run_definition_calibration.AsyncOpenAI") as client_factory,
        ):
            path = Path(directory) / "report.json"
            report = await run_calibration(
                definition_calibration_cases(),
                judge=None,
                report_path=path,
                judge_model=JUDGE_MODEL,
                judge_version=DEFINITION_JUDGE_VERSION,
            )
            assert json.loads(path.read_text()) == report
        client_factory.assert_not_called()
        assert report["status"] == "pending_real_calibration"
        assert report["planned_trials"] == 24
        assert report["completed_trials"] == 0
        assert report["calibration_passed"] is None
        assert report["confusion_matrix"] is None
        assert report["trials"] == []

    async def test_only_audit_answer_and_criterion_reach_the_judge(self) -> None:
        cases = definition_calibration_cases()[:2]
        judge = AsyncMock()
        judge.eval_async.side_effect = [Score(name="test", score=1.0), Score(name="test", score=0.0)] * 3
        with TemporaryDirectory() as directory:
            report = await run_calibration(
                cases,
                judge=judge,
                report_path=Path(directory) / "report.json",
                judge_model=JUDGE_MODEL,
                judge_version=DEFINITION_JUDGE_VERSION,
                trials=3,
            )
        assert report["calibration_passed"] is True
        assert report["planned_trials"] == report["completed_trials"] == 6
        trials = report["trials"]
        assert isinstance(trials, list)
        assert len({item["trial_id"] for item in trials}) == 6
        for case, call in zip(cases * 3, judge.eval_async.await_args_list, strict=True):
            output, expected = call.args
            assert output == {
                "prompt": case.prompt,
                "last_message": case.metadata["answer"],
                "exit_code": 0,
                "stop_reason": "end_turn",
            }
            assert expected == case.expected

    @parameterized.expand([("quota", 429), ("billing", 402), ("invalid_request", 400)])
    async def test_provider_error_aborts_after_one_request(self, _name: str, status_code: int) -> None:
        requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                status_code,
                json={"error": {"message": "Synthetic provider failure", "type": "insufficient_quota"}},
            )

        async with AsyncOpenAI(
            api_key="synthetic-calibration-key",
            base_url="https://calibration.example.com/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            with TemporaryDirectory() as directory:
                report = await run_calibration(
                    definition_calibration_cases(),
                    judge=ConversionDefinitionEvidence(client=client),
                    report_path=Path(directory) / "report.json",
                    judge_model=JUDGE_MODEL,
                    judge_version=DEFINITION_JUDGE_VERSION,
                )
        assert len(requests) == 1
        assert report["status"] == "judge_error"
        assert report["completed_trials"] == 1
        assert report["complete"] is False
        assert report["calibration_passed"] is False
        assert report["confusion_matrix"] == {
            "true_positive": 0,
            "true_negative": 0,
            "false_positive": 0,
            "false_negative": 0,
            "measured": 0,
            "errors": 1,
            "accuracy": None,
            "false_positive_rate": None,
            "false_negative_rate": None,
        }

    @parameterized.expand(
        [
            ("explicit_complete", True, "completed", "completed", 1.0),
            ("explicit_incomplete", True, "incomplete", "completed", 0.0),
            ("explicit_incomplete_tool", True, "completed", "in_progress", 0.0),
            ("default_complete", False, "completed", "completed", 1.0),
            ("default_incomplete", False, "incomplete", "completed", 0.0),
            ("default_incomplete_tool", False, "completed", "in_progress", 0.0),
        ]
    )
    async def test_preserves_responses_completion_and_budget(
        self, _name: str, explicit_client: bool, response_status: str, tool_status: str, expected_score: float
    ) -> None:
        self.enterContext(
            patch(
                "posthoganalytics.ai.openai.openai_async.setup", side_effect=AssertionError("Unexpected global capture")
            )
        )
        requests: list[httpx.Request] = []
        verdict = {
            "choice": "yes",
            "checks": {
                name: {"passed": True, "reason": "Synthetic check evidence"} for name in DefinitionChecks.model_fields
            },
        }

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "resp_synthetic",
                    "object": "response",
                    "created_at": 0,
                    "status": response_status,
                    "model": JUDGE_MODEL,
                    "output": [
                        {
                            "type": "function_call",
                            "id": "fc_synthetic",
                            "call_id": "call_synthetic",
                            "name": "select_choice",
                            "arguments": json.dumps(verdict),
                            "status": tool_status,
                        }
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "required",
                    "tools": [],
                },
            )

        async with AsyncOpenAI(
            api_key="synthetic-calibration-key",
            base_url="https://calibration.example.com/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            case = definition_calibration_cases()[0]
            try:
                if not explicit_client:
                    init(client=client, is_async=True)
                score = await ConversionDefinitionEvidence(client=client if explicit_client else None).eval_async(
                    {
                        "prompt": case.prompt,
                        "last_message": case.metadata["answer"],
                        "exit_code": 0,
                        "stop_reason": "end_turn",
                    },
                    case.expected,
                )
            finally:
                init()
        assert len(requests) == 1, score.metadata
        assert requests[0].url.path == "/v1/responses"
        request_body = json.loads(requests[0].content)
        assert request_body["model"] == JUDGE_MODEL
        assert request_body["max_output_tokens"] == 3000
        assert request_body["reasoning"] == {"effort": "low"}
        assert requests[0].extensions["timeout"]["read"] == 60.0
        assert score.score == expected_score
        if expected_score == 0.0:
            assert "Incomplete definition judge" in score.metadata["reason"]

    async def test_harness_judge_generations_keep_the_explicit_sink_and_trial_traces(self) -> None:
        requests: list[httpx.Request] = []
        verdict = {
            "choice": "yes",
            "checks": {
                name: {"passed": True, "reason": "Synthetic check evidence"} for name in DefinitionChecks.model_fields
            },
        }

        async def respond(_transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "resp_synthetic",
                    "object": "response",
                    "created_at": 0,
                    "status": "completed",
                    "model": JUDGE_MODEL,
                    "output": [
                        {
                            "type": "function_call",
                            "id": "fc_synthetic",
                            "call_id": "call_synthetic",
                            "name": "select_choice",
                            "arguments": json.dumps(verdict),
                            "status": "completed",
                        }
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "required",
                    "tools": [],
                },
            )

        posthog_client = Posthog("synthetic-tracing-key", disabled=True)
        scorer_traces: dict[tuple[str, str], str] = {}
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "synthetic-calibration-key",
                    "OPENAI_BASE_URL": "https://calibration.example.com/v1",
                    "ANTHROPIC_API_KEY": "synthetic-generation-key",
                },
            ),
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", autospec=True, side_effect=respond),
            patch(
                "posthoganalytics.ai.openai.openai_async.setup", side_effect=AssertionError("Unexpected global capture")
            ),
            patch.object(posthog_client, "capture") as capture,
        ):
            traced_clients = create_traced_scorer_clients(posthog_client)
            try:
                scorer = TracedScorer(
                    ConversionDefinitionEvidence(),
                    traced_clients,
                    {
                        "experiment_id": "synthetic-experiment",
                        "experiment_name": "synthetic-definition-review",
                        "run_metadata": {"git_sha": "synthetic-revision", "trials": 2},
                    },
                    scorer_traces,
                    posthog_client=posthog_client,
                )
                case = definition_calibration_cases()[0]
                for trial_id in ("trial-1", "trial-2"):
                    score = await scorer.eval_async(
                        {
                            "prompt": case.prompt,
                            "last_message": case.metadata["answer"],
                            "exit_code": 0,
                            "stop_reason": "end_turn",
                        },
                        case.expected,
                        metadata={"trial_id": trial_id},
                    )
                    assert score.score == 1.0, score.metadata
            finally:
                await traced_clients.openai_llm_client.openai.close()
                await traced_clients.anthropic_client.close()

        assert len(requests) == capture.call_count == 2
        trace_ids = [scorer_traces[(trial_id, "conversion_definition_evidence")] for trial_id in ("trial-1", "trial-2")]
        assert len(set(trace_ids)) == 2
        for request, call, trace_id in zip(requests, capture.call_args_list, trace_ids, strict=True):
            assert request.url.path == "/v1/responses"
            request_body = json.loads(request.content)
            assert request_body["model"] == JUDGE_MODEL
            assert request_body["max_output_tokens"] == 3000
            assert request_body["reasoning"] == {"effort": "low"}
            assert request.extensions["timeout"]["read"] == 60.0
            assert call.kwargs["event"] == "$ai_generation"
            assert call.kwargs["distinct_id"] == DISTINCT_ID
            properties = call.kwargs["properties"]
            assert properties["$ai_trace_id"] == properties["$ai_parent_id"] == trace_id
            assert properties["$ai_experiment_id"] == "synthetic-experiment"
            assert properties["$ai_experiment_name"] == "synthetic-definition-review"
            assert properties["$ai_span_name"] == "Scorer"
            assert properties["git_sha"] == "synthetic-revision"
            assert properties["trials"] == 2
