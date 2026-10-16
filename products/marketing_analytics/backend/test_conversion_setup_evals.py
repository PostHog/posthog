from __future__ import annotations

import os
import json
from typing import Literal

from unittest.mock import AsyncMock, Mock, patch

from django.test import SimpleTestCase

from anthropic.types import Message, TextBlock, Usage
from parameterized import parameterized

from products.marketing_analytics.evals.definition_evidence import DEFINITION_JUDGE_VERSION, DefinitionChecks
from products.marketing_analytics.evals.eval_conversion_definitions import (
    ConversionDefinitionEvidence,
    review_definition,
)
from products.marketing_analytics.evals.scorers import (
    PREVIEW_TOOL,
    ConversionPreviewDefinition,
    ConversionRecommendationEvidence,
    NoConversionSetupWrites,
)
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers.contract import Score

REVENUE_DEFINITION: dict[str, object] = {
    "kind": "EventsNode",
    "event": "paid_bill",
    "math": "sum",
    "math_property": "amount_usd",
    "math_property_revenue_currency": {"static": "USD"},
    "counts_as_revenue": True,
    "counts_as_customer": False,
}


def tool_log(name: str, payload: dict[str, object], *, failed: bool = False) -> str:
    updates = [
        {
            "sessionUpdate": "tool_call",
            "toolCallId": f"{name}-{failed}",
            "title": "mcp__posthog__exec",
            "rawInput": {"command": f"call {name} {json.dumps(payload)}"},
            "_meta": {"claudeCode": {"toolName": "mcp__posthog__exec"}},
        },
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": f"{name}-{failed}",
            "status": "failed" if failed else "completed",
            "rawOutput": "Preview failed"
            if failed
            else '{"total_conversions": 13, "checks_not_performed": ["source_quality"]}',
        },
    ]
    return "\n".join(
        json.dumps(
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "notification": {"method": "session/update", "params": {"update": update}},
            }
        )
        for update in updates
    )


class TestConversionSetupEvalScorers(SimpleTestCase):
    @parameterized.expand(
        [
            ("valid_revenue", {}, {}, False, 1.0),
            (
                "nullable_defaults",
                {"counts_as_customer": None, "math_property_revenue_currency": {"static": "USD", "property": None}},
                {},
                False,
                1.0,
            ),
            ("failed_preview", {}, {}, True, 0.0),
            ("wrong_source", {"event": "logged_in"}, {}, False, 0.0),
            ("file_size_is_not_money", {"math_property": "file_size_b"}, {}, False, 0.0),
            ("repeat_payment_is_not_new_customer", {"counts_as_customer": True}, {}, False, 0.0),
            ("wrong_currency", {"math_property_revenue_currency": {"static": "EUR"}}, {}, False, 0.0),
            ("excludes_repeat_payments", {}, {"allow_multiple_conversions_per_visitor": False}, False, 0.0),
            ("includes_test_accounts", {}, {"filter_test_accounts": False}, False, 0.0),
        ]
    )
    def test_grades_executed_revenue_definition(
        self,
        _name: str,
        goal_changes: dict[str, object],
        preview_changes: dict[str, object],
        failed: bool,
        expected_score: float,
    ) -> None:
        payload = {
            "goal": {**REVENUE_DEFINITION, **goal_changes},
            "filter_test_accounts": True,
            "allow_multiple_conversions_per_visitor": True,
            **preview_changes,
        }
        score = ConversionPreviewDefinition().eval(
            {"raw_log": tool_log(PREVIEW_TOOL, payload, failed=failed)},
            {"conversion_preview_definition": REVENUE_DEFINITION},
        )
        assert score.score == expected_score

    @parameterized.expand([("original_action", 123, 1.0), ("different_action", 124, 0.0)])
    def test_preserves_existing_action(self, _name: str, action_id: int, expected_score: float) -> None:
        definition = {"kind": "ActionsNode", "math": "total", "counts_as_revenue": False, "counts_as_customer": False}
        payload = {
            "goal": {**definition, "id": action_id},
            "filter_test_accounts": True,
            "allow_multiple_conversions_per_visitor": True,
        }
        score = ConversionPreviewDefinition().eval(
            {"raw_log": tool_log(PREVIEW_TOOL, payload), "seed": {"action_id": 123}},
            {"conversion_preview_definition": definition},
        )
        assert score.score == expected_score

    @parameterized.expand(
        [
            ("preview", PREVIEW_TOOL, False, 1.0),
            ("successful_save", "marketing-analytics-create-conversion-goal", False, 0.0),
            ("failed_save_attempt", "marketing-analytics-create-conversion-goal", True, 0.0),
            ("action_write", "action-create", False, 0.0),
        ]
    )
    def test_recommendations_do_not_attempt_writes(
        self, _name: str, tool: str, failed: bool, expected_score: float
    ) -> None:
        score = NoConversionSetupWrites().eval({"raw_log": tool_log(tool, {}, failed=failed)})
        assert score.score == expected_score

    def test_judge_receives_measured_preview_and_fails_on_missing_evidence(self) -> None:
        judge = ConversionRecommendationEvidence()
        expected: dict[str, object] = {"conversion_recommendation_evidence": {"criterion": "Explain paid revenue."}}
        missing_evidence: list[dict[str, object] | None] = [
            None,
            {"last_message": "I previewed it."},
            {"raw_log": "", "last_message": "Done"},
        ]
        for output in missing_evidence:
            prepared = judge._prepare(output, expected)
            assert isinstance(prepared, Score)
            assert prepared.score == 0.0
        prepared = judge._prepare(
            {
                "raw_log": "\n".join(
                    [
                        tool_log("execute-sql", {"query": "SELECT 13 AS total_conversions"}),
                        tool_log("query-trends", {}, failed=True),
                        tool_log("project-get", {}),
                        tool_log(PREVIEW_TOOL, {"goal": REVENUE_DEFINITION}),
                    ]
                ),
                "last_message": "Review the draft.",
            },
            expected,
        )
        assert isinstance(prepared, dict)
        judge_output = prepared["output"]
        assert isinstance(judge_output, dict)
        assert judge_output["previews"][0]["input"]["goal"] == REVENUE_DEFINITION
        assert '"total_conversions": 13' in judge_output["previews"][0]["result"]
        assert [read["tool"] for read in judge_output["supporting_reads"]] == ["execute-sql"]
        assert '"total_conversions": 13' in judge_output["supporting_reads"][0]["result"]


class TestConversionDefinitionGeneration(SimpleTestCase):
    @parameterized.expand(
        [
            ("complete", "Supported draft.", "end_turn", 0),
            ("empty", "", "end_turn", 1),
            ("whitespace", " \n", "end_turn", 1),
            ("truncated", "Supported", "max_tokens", 1),
            ("other_stop", "Supported", "stop_sequence", 1),
            ("unknown_stop", "Supported", None, 1),
        ]
    )
    async def test_records_generation_completion(
        self,
        _name: str,
        answer: str,
        stop_reason: Literal["end_turn", "max_tokens", "stop_sequence"] | None,
        expected_exit_code: int,
    ) -> None:
        case = BaseEvalCase(name="synthetic_review", prompt="Review the supplied synthetic audit only.")
        ctx = Mock(spec=EvalContext, agent_model="requested-model")
        response = Message(
            id="msg_test",
            content=[TextBlock(type="text", text=answer)],
            model="response-model",
            role="assistant",
            stop_reason=stop_reason,
            stop_sequence=None,
            type="message",
            usage=Usage(input_tokens=123, output_tokens=45),
        )
        with (
            patch.dict(os.environ, {"LLM_GATEWAY_ANTHROPIC_API_KEY": "test-key"}),
            patch("products.marketing_analytics.evals.eval_conversion_definitions.AsyncAnthropic") as client_factory,
        ):
            client = client_factory.return_value.__aenter__.return_value
            client.messages.create = AsyncMock(return_value=response)
            result = await review_definition(case, ctx)

        assert result == {
            "exit_code": expected_exit_code,
            "last_message": answer,
            "prompt": case.prompt,
            "response_model": "response-model",
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 123, "output_tokens": 45},
        }
        assert client.messages.create.await_args.kwargs["max_tokens"] == 4096

    @parameterized.expand(
        [
            ("complete", "Supported draft.", 0, "end_turn", 1.0),
            ("nonzero_exit", "Supported draft.", 1, "end_turn", 0.0),
            ("truncated_with_success_exit", "Supported", 0, "max_tokens", 0.0),
            ("unknown_stop", "Supported", 0, None, 0.0),
            ("empty", "", 1, "end_turn", 0.0),
        ]
    )
    async def test_only_complete_generations_reach_judge(
        self,
        _name: str,
        answer: str,
        exit_code: int,
        stop_reason: str | None,
        expected_score: float,
    ) -> None:
        output = {
            "last_message": answer,
            "prompt": "Review the supplied synthetic audit only.",
            "exit_code": exit_code,
            "stop_reason": stop_reason,
        }
        expected = {"conversion_definition_evidence": {"criterion": "Preserve the supplied definition."}}
        with patch(
            "products.posthog_ai.eval_harness.scorers.judged.LLMClassifier._run_eval_async",
            new_callable=AsyncMock,
            return_value=Score(name="conversion_definition_evidence", score=1.0),
        ) as judge_call:
            score = await ConversionDefinitionEvidence().eval_async(output, expected)

        assert score.score == expected_score
        if expected_score == 1.0:
            judge_call.assert_awaited_once()
        else:
            assert score.metadata == {"reason": "Incomplete generation"}
            judge_call.assert_not_awaited()


class TestConversionDefinitionChecklist(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        transport = patch(
            "products.marketing_analytics.evals.definition_evidence.definition_judge_client", return_value=None
        )
        transport.start()
        self.addCleanup(transport.stop)

    def verdict_response(self, *, failed_check: str | None = None) -> dict[str, object]:
        checks = {
            name: {
                "passed": name != failed_check,
                "reason": "Evidence matches." if name != failed_check else "Required evidence is missing.",
            }
            for name in DefinitionChecks.model_fields
        }
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "select_choice",
                                    "arguments": json.dumps(
                                        {"choice": "yes" if failed_check is None else "no", "checks": checks}
                                    ),
                                }
                            }
                        ]
                    },
                }
            ]
        }

    @parameterized.expand([(None,), *((name,) for name in DefinitionChecks.model_fields)])
    async def test_any_failed_evidence_check_rejects_answer(self, failed_check: str | None) -> None:
        with patch(
            "autoevals.llm.arun_cached_request",
            new_callable=AsyncMock,
            return_value=self.verdict_response(failed_check=failed_check),
        ):
            score = await ConversionDefinitionEvidence().eval_async(
                {"exit_code": 0, "stop_reason": "end_turn", "prompt": "Synthetic audit.", "last_message": "Review."},
                {"conversion_definition_evidence": {"criterion": "Preserve the source definition."}},
            )
        assert score.score == (1.0 if failed_check is None else 0.0)
        assert score.metadata["judge_version"] == DEFINITION_JUDGE_VERSION
        assert {name for name, result in score.metadata["checks"].items() if not result["passed"]} == (
            {failed_check} if failed_check else set()
        )

    @parameterized.expand(
        [
            ("missing_check",),
            ("extra_check",),
            ("string_boolean",),
            ("blank_reason",),
            ("contradictory_choice",),
            ("duplicate_key",),
            ("multiple_tools",),
            ("truncated",),
            ("invalid_json",),
            ("unexpected_tool",),
        ]
    )
    async def test_malformed_judge_verdict_is_measurement_error(self, failure: str) -> None:
        response = self.verdict_response()
        choices = response["choices"]
        assert isinstance(choices, list)
        choice = choices[0]
        tools = choice["message"]["tool_calls"]
        function = tools[0]["function"]
        verdict = json.loads(function["arguments"])
        if failure == "missing_check":
            del verdict["checks"]["source_contract"]
        elif failure == "extra_check":
            verdict["checks"]["invented_check"] = {"passed": True, "reason": "Accepted."}
        elif failure == "string_boolean":
            verdict["checks"]["source_contract"]["passed"] = "false"
        elif failure == "blank_reason":
            verdict["checks"]["source_contract"]["reason"] = "   "
        elif failure == "contradictory_choice":
            verdict["checks"]["source_contract"]["passed"] = False
        elif failure == "multiple_tools":
            tools.append(tools[0])
        elif failure == "truncated":
            choice["finish_reason"] = "length"
        elif failure == "unexpected_tool":
            function["name"] = "unrelated_tool"
        function["arguments"] = json.dumps(verdict)
        if failure == "duplicate_key":
            function["arguments"] = function["arguments"].replace('"choice": "yes"', '"choice": "no", "choice": "yes"')
        elif failure == "invalid_json":
            function["arguments"] = "{"
        with patch("autoevals.llm.arun_cached_request", new_callable=AsyncMock, return_value=response):
            score = await ConversionDefinitionEvidence().eval_async(
                {"exit_code": 0, "stop_reason": "end_turn", "prompt": "Synthetic audit.", "last_message": "Review."},
                {"conversion_definition_evidence": {"criterion": "Preserve the source definition."}},
            )
        assert score.score == 0.0
        assert score.metadata["reason"].startswith("judge error:")

    async def test_calibration_labels_never_reach_the_judge(self) -> None:
        with patch(
            "autoevals.llm.arun_cached_request", new_callable=AsyncMock, return_value=self.verdict_response()
        ) as request:
            score = await ConversionDefinitionEvidence().eval_async(
                {
                    "exit_code": 0,
                    "stop_reason": "end_turn",
                    "prompt": "Synthetic audit.",
                    "last_message": "Review.",
                    "gold_pass": "SECRET_LABEL",
                },
                {
                    "conversion_definition_evidence": {
                        "criterion": "Preserve the source definition.",
                        "gold_pass": "SECRET_LABEL",
                    },
                    "metadata": {"gold_pass": "SECRET_LABEL"},
                },
            )
        assert score.score == 1.0
        assert request.await_args is not None
        assert "SECRET_LABEL" not in json.dumps(request.await_args.kwargs)
        assert "Synthetic audit." in json.dumps(request.await_args.kwargs)

    async def test_blank_answer_cannot_reach_the_judge_with_success_metadata(self) -> None:
        with patch("autoevals.llm.arun_cached_request", new_callable=AsyncMock) as request:
            score = await ConversionDefinitionEvidence().eval_async(
                {"exit_code": 0, "stop_reason": "end_turn", "prompt": "Synthetic audit.", "last_message": " \n"},
                {"conversion_definition_evidence": {"criterion": "Preserve the source definition."}},
            )
        assert score.score == 0.0
        request.assert_not_awaited()
