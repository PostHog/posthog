import os
import sys
import copy
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase, override_settings

import httpx
from openai import AsyncOpenAI
from parameterized import parameterized

from products.posthog_ai.eval_harness.harness.ports import LLM_GATEWAY_PORT
from products.signals.backend.rubrics_judging import (
    TrialEvaluationCriterion,
    TrialEvidenceSource,
    TrialJudgeVerdicts,
    build_rubric_judge_messages,
    coverage,
    parse_trial_judgment,
    pass_rate,
)
from products.signals.evals.agentic.rubric_evidence import build_offline_evidence
from products.signals.evals.agentic.rubric_judge import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_MAX_INPUT_TOKENS,
    PrivateRubricClient,
    RubricModelResponse,
    content_hash,
    judge_rubric,
)


def criterion(criterion_id: str, *, enabled: bool = True) -> dict[str, object]:
    return {
        "id": criterion_id,
        "title": "Synthetic check",
        "description": "Review the invented report.",
        "pass_condition": "Explain the invented observation accurately.",
        "applicability": "When the scout reports an observation.",
        "enabled": enabled,
        "source": "custom",
    }


def verdict(criterion_id: str, status: str = "pass", *, source_id: str = "summary") -> dict[str, object]:
    return {
        "criterion_id": criterion_id,
        "verdict": status,
        "reason": "The synthetic report states the observation.",
        "confidence": "high",
        "evidence": [{"source_id": source_id, "quote": "Invented report"}],
    }


def model_response(rows: list[dict[str, object]]) -> RubricModelResponse:
    return RubricModelResponse(
        requested_model="invented-model",
        text=json.dumps({"summary": "The invented evidence supports the listed conclusions.", "criteria": rows}),
        finish_reason="stop",
    )


class TestSavedScoutJudgment(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.output: dict[str, object] = {
            "summary": "Invented report: no change in the demonstration metric.",
            "prompt": "Invented report must describe the observed delivery count.",
            "raw_log": "invented transcript beginning\ncomplete invented transcript ending",
            "artifacts": {"task_run": {"status": "completed"}, "before": {"reports": []}},
        }
        self.references: dict[str, object] = {"instructions": "Report material changes; otherwise remain silent."}
        self.enterContext(
            patch(
                "posthog.helpers.tiktoken_encoding.get_tiktoken_encoding_for_model",
                return_value=SimpleNamespace(encode=lambda text, **kwargs: text.split()),
            )
        )
        self.evidence = build_offline_evidence(self.output)
        self.summary_id = next(
            source_id
            for source_id, locations in self.evidence.source_locations.items()
            if "output:/summary" in locations
        )

    def test_module_import_does_not_initialize_django(self) -> None:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; "
                "import products.signals.backend.rubrics_judging; "
                "import products.signals.evals.agentic.rubric_judge; "
                "import products.signals.evals.saved_scout; "
                "assert 'django.db.models' not in sys.modules",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[4],
        )

    async def test_recorded_response_matches_shared_verdicts_scores_and_coverage(self) -> None:
        statuses = ["pass", "fail", "unknown", "not_applicable"]
        criteria = [criterion(status) for status in statuses] + [criterion("disabled", enabled=False)]
        response = model_response([verdict(status, status, source_id=self.summary_id) for status in reversed(statuses)])
        ask = AsyncMock(return_value=response)
        original = copy.deepcopy(self.output)

        result = await judge_rubric(self.output, criteria, self.references, ask)

        assert ask.await_args is not None
        messages = ask.await_args.args[0]
        envelope = json.loads(messages[-1]["content"])
        shared = parse_trial_judgment(
            response.text,
            criteria=[TrialEvaluationCriterion.model_validate(row) for row in envelope["criteria"]],
            sources=[TrialEvidenceSource.model_validate(row) for row in envelope["sources"]],
        )
        self.assertEqual(result.status, "judged")
        self.assertEqual(result.criteria, shared.criteria)
        self.assertEqual([row.verdict for row in result.criteria], statuses)
        self.assertEqual(result.score, pass_rate(shared.criteria))
        self.assertEqual(result.coverage, coverage(shared.criteria))
        self.assertEqual((result.score, result.coverage), (0.5, 2 / 3))
        self.assertEqual(result.request_messages, messages)
        self.assertEqual(result.messages_sha256, content_hash(messages))
        self.assertEqual(result.judge_prompt_version, "7")
        self.assertEqual(result.disabled_criterion_ids, ["disabled"])
        self.assertEqual(result.output_sha256, content_hash(self.output))
        self.assertEqual(result.rubric_sha256, content_hash(criteria))
        self.assertEqual(result.reference_sha256, content_hash(self.references))
        self.assertEqual(envelope["rubric_reference_context"], self.references)
        self.assertEqual(result.model_response, response)
        self.assertEqual(self.output, original)
        ask.assert_awaited_once()

    @parameterized.expand(["nonliteral", "instruction_only", "reference_is_not_execution"])
    async def test_invalid_citation_preserves_other_verdicts_without_retry(self, failure: str) -> None:
        unsupported = verdict("unsupported", source_id=self.summary_id)
        if failure == "instruction_only":
            source_id = next(source.id for source in self.evidence.sources if source.kind == "instructions")
            unsupported["evidence"] = [{"source_id": source_id, "quote": "Invented report"}]
        elif failure == "reference_is_not_execution":
            unsupported["evidence"] = [{"source_id": "rubric_reference_context", "quote": "Report material changes"}]
        else:
            unsupported["evidence"] = [{"source_id": self.summary_id, "quote": "Text absent from this source"}]
        response = model_response([verdict("supported", source_id=self.summary_id), unsupported])
        ask = AsyncMock(return_value=response)

        result = await judge_rubric(
            self.output, [criterion("supported"), criterion("unsupported")], self.references, ask
        )

        self.assertEqual(result.status, "judged")
        self.assertEqual([row.verdict for row in result.criteria], ["pass", "unknown"])
        self.assertEqual(result.criteria[1].confidence, "low")
        self.assertEqual((result.score, result.coverage), (1.0, 0.5))
        self.assertEqual(result.model_response, response)
        self.assertIsNone(result.error)
        ask.assert_awaited_once()

    @parameterized.expand(["malformed", "missing", "duplicate", "provider", "exception", "truncated", "missing_finish"])
    async def test_judge_failure_has_no_quality_verdicts_or_retry(self, failure: str) -> None:
        row = verdict("check", source_id=self.summary_id)
        response = model_response([row])
        if failure == "malformed":
            response = response.model_copy(update={"text": "Incomplete JSON: {"})
        elif failure == "missing":
            response = model_response([verdict("another", source_id=self.summary_id)])
        elif failure == "duplicate":
            response = model_response([row, row])
        elif failure == "provider":
            response = response.model_copy(update={"error": "Invented provider unavailable", "error_type": "Provider"})
        elif failure in {"truncated", "missing_finish"}:
            response = response.model_copy(update={"finish_reason": "length" if failure == "truncated" else None})
        ask = AsyncMock(return_value=response)
        if failure == "exception":
            ask.side_effect = TimeoutError("Invented timeout")

        result = await judge_rubric(self.output, [criterion("check")], self.references, ask)

        self.assertEqual(result.status, "judge_error")
        self.assertEqual(result.criteria, [])
        self.assertIsNone(result.score)
        self.assertIsNone(result.coverage)
        self.assertTrue(result.error)
        self.assertEqual(result.model_response, None if failure == "exception" else response)
        ask.assert_awaited_once()

    @parameterized.expand(["bytes", "tokens"])
    async def test_oversized_evidence_is_retained_without_calling_model(self, budget: str) -> None:
        ask = AsyncMock()
        result = await judge_rubric(
            self.output,
            [criterion("check")],
            self.references,
            ask,
            max_input_bytes=50 if budget == "bytes" else DEFAULT_MAX_INPUT_BYTES,
            max_input_tokens=2 if budget == "tokens" else DEFAULT_MAX_INPUT_TOKENS,
        )

        self.assertEqual(result.status, "judge_error")
        self.assertIn("no evidence was truncated", result.error or "")
        self.assertIsNone(result.score)
        self.assertEqual(result.criteria, [])
        self.assertEqual(result.evidence, self.evidence)
        self.assertIn("complete invented transcript ending", result.request_prompt)
        self.assertEqual(
            result.input_bytes,
            sum(len(message["content"].encode("utf-8")) for message in result.request_messages),
        )
        ask.assert_not_awaited()

    @parameterized.expand(
        [
            "source",
            "task",
            "workflow",
            "workflow_missing",
            "workflow_null",
            "workflow_invalid",
            "task_missing",
            "exit",
            "exit_bool",
            "exit_string",
            "exit_null",
            "empty",
            "unconfirmed",
        ]
    )
    async def test_failed_or_unconfirmed_execution_is_excluded(self, failure: str) -> None:
        output = copy.deepcopy(self.output)
        source_error = None
        if failure == "source":
            source_error = "Invented sandbox failure"
        elif failure == "task":
            output["artifacts"] = {"task_run": {"status": "failed"}}
        elif failure == "workflow":
            output["artifacts"] = {"workflow": {"terminal": False}}
        elif failure.startswith("workflow_"):
            workflow: object = (
                {"terminal": None} if failure == "workflow_null" else {} if failure == "workflow_missing" else None
            )
            output["artifacts"] = {"workflow": workflow, "task_run": {"status": "completed"}}
        elif failure == "task_missing":
            output["artifacts"] = {"task_run": {}}
            output["exit_code"] = 0
        elif failure == "exit":
            output["exit_code"] = 1
        elif failure.startswith("exit_"):
            output["exit_code"] = False if failure == "exit_bool" else "1" if failure == "exit_string" else None
        elif failure == "empty":
            output = {}
        else:
            output = {"summary": "Invented report without confirmed completion"}
        ask = AsyncMock()

        result = await judge_rubric(output, [criterion("check")], self.references, ask, source_error=source_error)

        self.assertEqual(result.status, "excluded")
        self.assertEqual(result.criteria, [])
        self.assertIsNone(result.score)
        self.assertIsNone(result.coverage)
        self.assertIsNone(result.model_response)
        ask.assert_not_awaited()


class TestPrivateRubricClient(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            override_settings(
                TEST=True,
                LLM_GATEWAY_URL=f"http://localhost:{LLM_GATEWAY_PORT}",
                LLM_GATEWAY_API_KEY="phx_invented_test_key",
                AI_GATEWAY_URL="",
                AI_GATEWAY_API_KEY="",
            )
        )
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "OPT_OUT_CAPTURE": "1",
                    "LLM_GATEWAY_POSTHOG_AI_LANE_CAPTURE": "false",
                    "LLM_GATEWAY_POSTHOG_PROJECT_TOKEN": "",
                    "LLM_GATEWAY_POSTHOG_SECONDARY_PROJECT_TOKEN": "",
                    "POSTHOG_ANALYTICS_API_KEY": "",
                    "POSTHOG_ANALYTICS_HOST": "",
                },
            )
        )

    @parameterized.expand(["remote_gateway", "go_gateway", "capture_enabled", "not_test"])
    def test_rejects_nonprivate_context_before_constructing_client(self, failure: str) -> None:
        overrides: dict[str, object] = {}
        if failure == "remote_gateway":
            overrides["LLM_GATEWAY_URL"] = "https://gateway.example.com"
        elif failure == "go_gateway":
            overrides["AI_GATEWAY_URL"] = "https://gateway.example.com/v1"
        elif failure == "not_test":
            overrides["TEST"] = False
        else:
            os.environ["LLM_GATEWAY_POSTHOG_AI_LANE_CAPTURE"] = "true"
        with (
            override_settings(**overrides),
            patch("posthog.llm.gateway_client.build_async_openai_client") as build_client,
        ):
            with self.assertRaisesRegex(ValueError, "private eval gateway"):
                PrivateRubricClient()
            build_client.assert_not_called()

    @parameterized.expand(
        [
            ("success", "gpt-6-sol", ["reasoning_effort"]),
            ("success", "gpt-6-astra", ["reasoning_effort"]),
            ("success", "openai/gpt-6-sol", ["reasoning_effort"]),
            ("success", "claude-sonnet-4-6", None),
            ("gateway_error", "gpt-6-sol", ["reasoning_effort"]),
            ("truncated", "gpt-6-sol", ["reasoning_effort"]),
        ]
    )
    async def test_plain_sdk_retains_usage_and_errors_without_claiming_dollar_cost(
        self, outcome: str, model: str, allowed_openai_params: list[str] | None
    ) -> None:
        requests: list[Mapping[str, object]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            if outcome == "gateway_error":
                return httpx.Response(
                    503,
                    headers={"x-request-id": "invented-request"},
                    json={"error": {"message": "Invented unavailable provider"}},
                )
            return httpx.Response(
                200,
                headers={"x-request-id": "invented-request"},
                json={
                    "id": "invented-response",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "invented-resolved-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": '{"suggestions":[]}'},
                            "finish_reason": "length" if outcome == "truncated" else "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
                },
            )

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        sdk = AsyncOpenAI(api_key="invented-token", base_url="http://localhost/signals/v1", http_client=http_client)
        with patch("posthog.llm.gateway_client.build_async_openai_client", return_value=sdk):
            async with PrivateRubricClient(model=model, max_output_tokens=123) as client:
                if outcome == "success":
                    self.assertEqual(await client.ask("Return synthetic rubric JSON"), '{"suggestions":[]}')
                else:
                    with self.assertRaises(RuntimeError):
                        await client.ask("Return synthetic rubric JSON")

        self.assertTrue(http_client.is_closed)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["model"], model)
        self.assertEqual(requests[0]["reasoning_effort"], "high")
        self.assertEqual(requests[0]["max_completion_tokens"], 123)
        self.assertEqual(requests[0].get("allowed_openai_params"), allowed_openai_params)
        self.assertNotIn("drop_params", requests[0])
        self.assertEqual(len(client.calls), 1)
        response = client.calls[0]
        self.assertIsNone(response.cost_usd)
        self.assertEqual(response.cost_source, "unavailable")
        self.assertEqual(response.prompt, "Return synthetic rubric JSON")
        self.assertEqual(response.request_id, "invented-request")
        if outcome == "gateway_error":
            self.assertTrue(response.error)
        else:
            self.assertEqual(response.actual_model, "invented-resolved-model")
            self.assertEqual((response.usage or {})["total_tokens"], 25)

    async def test_generator_corrections_keep_context_and_judgments_start_fresh(self) -> None:
        requests: list[dict[str, object]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "invented-response",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "invented-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"summary": "Invented summary", "criteria": [verdict("check")]})
                                if len(requests) == 3
                                else '{"suggestions":[]}',
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

        sdk = AsyncOpenAI(
            api_key="invented-token",
            base_url="http://localhost/signals/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        judge_messages = build_rubric_judge_messages(
            criteria=[
                TrialEvaluationCriterion.model_validate(
                    {key: value for key, value in criterion("check").items() if key not in {"enabled", "source"}}
                )
            ],
            sources=[TrialEvidenceSource(id="summary", kind="summary", text="Invented report")],
            reference_context={"instructions": "Review the invented report."},
            limitations=[],
        )
        with patch("posthog.llm.gateway_client.build_async_openai_client", return_value=sdk):
            async with PrivateRubricClient() as client:
                await client.ask("Initial canonical scout instructions")
                await client.ask("Select the useful generated criteria")
                await client.complete(judge_messages)

        self.assertEqual(len(requests), 3)
        self.assertEqual(
            client.calls[1].messages[1:],
            [
                {"role": "user", "content": "Initial canonical scout instructions"},
                {"role": "assistant", "content": '{"suggestions":[]}'},
                {"role": "user", "content": "Select the useful generated criteria"},
            ],
        )
        self.assertEqual(client.calls[1].messages, requests[1]["messages"])
        self.assertEqual(client.calls[1].messages_sha256, content_hash(requests[1]["messages"]))
        self.assertEqual(len(client.calls[0].messages), 2)
        self.assertEqual(client.calls[2].messages, judge_messages)
        self.assertEqual(requests[2]["messages"], judge_messages)
        self.assertEqual(client.calls[2].system_prompt, judge_messages[0]["content"])
        self.assertEqual([request["response_format"] for request in requests[:2]], [{"type": "json_object"}] * 2)
        for call, request in zip(client.calls, requests):
            self.assertEqual(call.response_format, request["response_format"])
        self.assertEqual(requests[2]["response_format"], {"type": "json_object"})
        TrialJudgeVerdicts.model_validate_json(client.calls[2].text)
