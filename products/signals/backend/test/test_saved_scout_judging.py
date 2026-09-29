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
import jsonschema
from openai import AsyncOpenAI
from parameterized import parameterized

from products.posthog_ai.eval_harness.harness.ports import LLM_GATEWAY_PORT
from products.signals.evals.agentic.rubric_judge import (
    STATE_REFERENCE_KEY,
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


def verdict(criterion_id: str, status: str = "pass") -> dict[str, object]:
    return {
        "id": criterion_id,
        "applicability": "not_applicable" if status == "not_applicable" else "applicable",
        "status": status,
        "rationale": "The synthetic report states the observation.",
        "evidence": [{"source": "output", "pointer": "/summary", "quote": "Invented report"}],
    }


class TestSavedScoutJudgment(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.output: dict[str, object] = {
            "summary": "Invented report: no change in the demonstration metric.",
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

    def test_module_import_does_not_initialize_django(self) -> None:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import products.signals.evals.agentic.rubric_judge; assert 'django.db.models' not in sys.modules",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[4],
        )

    async def test_judges_all_enabled_criteria_once_with_complete_evidence_and_separate_scores(self) -> None:
        statuses = ["pass", "fail", "unknown", "not_applicable"]
        criteria = [criterion(status) for status in statuses] + [criterion("disabled", enabled=False)]
        ask = AsyncMock(
            return_value=RubricModelResponse(
                requested_model="invented-model",
                text=json.dumps({"criteria": [verdict(status, status) for status in reversed(statuses)]}),
            )
        )

        result = await judge_rubric(self.output, criteria, self.references, ask)

        self.assertEqual([row.status for row in result.criteria], statuses)
        self.assertEqual([row.score for row in result.criteria], [1.0, 0.0, None, None])
        self.assertEqual(result.execution_status, "completed")
        self.assertIsNone(result.error)
        self.assertEqual(result.disabled_criterion_ids, ["disabled"])
        self.assertEqual(result.output_sha256, content_hash(self.output))
        self.assertEqual(result.rubric_sha256, content_hash(criteria))
        self.assertEqual(result.reference_sha256, content_hash(self.references))
        ask.assert_awaited_once()
        prompt = ask.call_args.args[0]
        self.assertIn("complete invented transcript ending", prompt)
        self.assertIn(str(self.references["instructions"]), prompt)
        self.assertNotIn('"id":"disabled"', prompt)

    @parameterized.expand(
        [
            "missing",
            "duplicate",
            "extra",
            "invalid_json",
            "wrong_quote",
            "missing_pointer",
            "contradiction",
            "truncated",
            "model_error",
            "empty_rationale",
        ]
    )
    async def test_rejects_incomplete_or_unsupported_judgments(self, failure: str) -> None:
        rows = [verdict("first"), verdict("second")]
        finish_reason = "stop"
        if failure == "missing":
            rows.pop()
        elif failure == "duplicate":
            rows[1] = verdict("first")
        elif failure == "extra":
            rows.append(verdict("extra"))
        elif failure == "wrong_quote":
            rows[0]["evidence"] = [{"source": "output", "pointer": "/summary", "quote": "Fabricated quotation"}]
        elif failure == "missing_pointer":
            rows[0]["evidence"] = [{"source": "output", "pointer": "/missing", "quote": "Invented report"}]
        elif failure == "contradiction":
            rows[0]["applicability"] = "not_applicable"
        elif failure == "truncated":
            finish_reason = "length"
        elif failure == "empty_rationale":
            rows[0]["rationale"] = "   "
        ask = AsyncMock(
            return_value=RubricModelResponse(
                requested_model="invented-model",
                text="not json" if failure == "invalid_json" else json.dumps({"criteria": rows}),
                finish_reason=finish_reason,
                error="Synthetic provider error" if failure == "model_error" else None,
            )
        )

        result = await judge_rubric(self.output, [criterion("first"), criterion("second")], self.references, ask)

        self.assertTrue(result.error)
        self.assertEqual([row.status for row in result.criteria], ["error", "error"])
        self.assertEqual([row.score for row in result.criteria], [None, None])
        self.assertIsNotNone(result.model_response)
        self.assertEqual(result.execution_status, "completed")

    @parameterized.expand(
        [
            "byte_limit",
            "token_limit",
            "execution_failed",
            "task_failed",
            "workflow_unfinished",
            "exit_failed",
            "no_output",
        ]
    )
    async def test_no_model_call_when_input_cannot_be_graded(self, reason: str) -> None:
        ask = AsyncMock(side_effect=AssertionError("No model call expected"))
        if reason == "task_failed":
            self.output["artifacts"] = {"task_run": {"status": "failed", "error_message": "Invented task failure"}}
        elif reason == "workflow_unfinished":
            self.output["artifacts"] = {"task_run": {"status": "completed"}, "workflow": {"terminal": False}}
        elif reason == "exit_failed":
            self.output["exit_code"] = 1
        result = await judge_rubric(
            {} if reason == "no_output" else self.output,
            [criterion("check")],
            self.references,
            ask,
            max_input_bytes=1 if reason == "byte_limit" else 100_000,
            max_input_tokens=1 if reason == "token_limit" else 20_000,
            source_error="Synthetic infrastructure error" if reason == "execution_failed" else None,
        )

        ask.assert_not_awaited()
        self.assertEqual(result.criteria[0].status, "error" if reason.endswith("limit") else "unknown")
        self.assertIsNone(result.criteria[0].score)
        self.assertEqual(
            result.execution_status,
            "failed"
            if reason in ("execution_failed", "task_failed", "workflow_unfinished", "exit_failed")
            else "unknown"
            if reason == "no_output"
            else "completed",
        )
        if reason.endswith("limit"):
            self.assertIn("no evidence was truncated", result.error or "")
        else:
            self.assertIsNone(result.error)

    async def test_no_report_can_be_not_applicable_with_literal_empty_state_evidence(self) -> None:
        row = verdict("check", "not_applicable")
        row["evidence"] = [
            {"source": "output", "pointer": "/artifacts/before/reports", "quote": "[]"},
            {"source": "canonical_references", "pointer": "/instructions", "quote": "otherwise remain silent"},
        ]
        ask = AsyncMock(
            return_value=RubricModelResponse(requested_model="invented-model", text=json.dumps({"criteria": [row]}))
        )

        result = await judge_rubric(self.output, [criterion("check")], self.references, ask)

        self.assertIsNone(result.error)
        self.assertEqual(result.criteria[0].status, "not_applicable")
        self.assertEqual(result.criteria[0].evidence[1].quote, "otherwise remain silent")

    @parameterized.expand(
        ["multiline_text", "decoded_jsonl_text", "wrong_decoded_text", "mixed_jsonl", "duplicate_keys"]
    )
    async def test_citations_preserve_literal_quotes_newlines_and_jsonl_escaping(self, source: str) -> None:
        observed = 'Invented "blue" metric\nSecond invented observation'
        raw_log = json.dumps({"content": observed}) + "\n"
        fallback = source in ("mixed_jsonl", "duplicate_keys")
        if source == "mixed_jsonl":
            raw_log += "not a JSON entry\n"
        elif source == "duplicate_keys":
            raw_log = '{"content":"first invented value","content":"second invented value"}\n'
        self.output.update(summary=observed, raw_log=raw_log)
        row = verdict("check")
        row["evidence"] = [
            {
                "source": "output" if source == "multiline_text" or fallback else "transcript",
                "pointer": "/summary" if source == "multiline_text" else "/raw_log" if fallback else "/0/content",
                "quote": raw_log if fallback else "wrong invented text" if source == "wrong_decoded_text" else observed,
            }
        ]
        ask = AsyncMock(
            return_value=RubricModelResponse(requested_model="invented-model", text=json.dumps({"criteria": [row]}))
        )

        result = await judge_rubric(self.output, [criterion("check")], self.references, ask)

        self.assertEqual(result.criteria[0].status, "error" if source == "wrong_decoded_text" else "pass")
        self.assertEqual(result.output_sha256, content_hash(self.output))
        self.assertEqual(self.output["raw_log"], raw_log)
        self.assertEqual(result.evidence_representation, "saved-output-v1" if fallback else "decoded-jsonl-v1")
        if fallback:
            self.assertIn('"raw_log":', result.request_prompt)
            self.assertIsNone(result.transcript_sha256)
        else:
            self.assertNotIn('"raw_log":', result.request_prompt)
            self.assertEqual(result.transcript_sha256, content_hash([{"content": observed}]))
        if source != "wrong_decoded_text":
            self.assertEqual(result.criteria[0].evidence[0].quote, raw_log if fallback else observed)

    async def test_shared_state_expands_to_original_and_citations_follow_only_generated_references(self) -> None:
        before = [
            {"id": "stable", "summary": "The invented observation stays the same."},
            {"id": "changed", "summary": "The original invented observation."},
            {"id": "deleted", "summary": "A deleted invented observation."},
        ]
        after = [
            {"id": "changed", "summary": "The updated invented observation."},
            before[0],
            {"id": "new", "summary": "A new invented observation."},
        ]
        self.output.update(
            raw_log=json.dumps({"content": "Invented transcript"}) + "\n",
            artifacts={
                "task_run": {"status": "completed"},
                "before": {"reports": before},
                "after": {"reports": after},
                "changes": {"reports": {"created": [], "updated": [], "deleted": []}},
            },
        )
        original = copy.deepcopy(self.output)
        row = verdict("check")
        row["evidence"] = [
            {"source": "output", "pointer": "/artifacts/after/reports/1/summary", "quote": "stays the same"},
            {"source": "output", "pointer": "/artifacts/before/reports/0/summary", "quote": "stays the same"},
            {"source": "output", "pointer": "/artifacts/after/reports/0/summary", "quote": "updated invented"},
        ]
        ask = AsyncMock(
            return_value=RubricModelResponse(requested_model="invented-model", text=json.dumps({"criteria": [row]}))
        )

        result = await judge_rubric(self.output, [criterion("check")], self.references, ask)

        self.assertEqual(result.criteria[0].status, "pass")
        self.assertEqual(result.evidence_representation, "decoded-jsonl-shared-state-v1")
        self.assertEqual(self.output, original)
        self.assertEqual(result.output_sha256, content_hash(original))
        self.assertEqual(result.state_references, {"/artifacts/after/reports/1": "/artifacts/before/reports/0"})
        evidence = json.loads(result.request_prompt.rsplit("\n", 1)[1])["output"]["artifacts"]
        self.assertEqual(evidence["after"]["reports"][1], {STATE_REFERENCE_KEY: "/artifacts/before/reports/0"})
        evidence["after"]["reports"][1] = evidence["before"]["reports"][0]
        self.assertEqual(evidence, original["artifacts"])


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
                                "content": json.dumps({"criteria": [verdict("check")]})
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
        with patch("posthog.llm.gateway_client.build_async_openai_client", return_value=sdk):
            async with PrivateRubricClient() as client:
                await client.ask("Initial canonical scout instructions")
                await client.ask("Select the useful generated criteria")
                await client.complete("Judge this independent result")

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
        self.assertEqual(client.calls[2].messages[1:], [{"role": "user", "content": "Judge this independent result"}])
        self.assertEqual([request["response_format"] for request in requests[:2]], [{"type": "json_object"}] * 2)
        for call, request in zip(client.calls, requests):
            self.assertEqual(call.response_format, request["response_format"])
        response_format = requests[2]["response_format"]
        assert isinstance(response_format, dict)
        self.assertEqual(response_format["type"], "json_schema")
        schema = response_format["json_schema"]
        self.assertTrue(schema["strict"])
        validator = jsonschema.Draft202012Validator(schema["schema"])
        validator.validate(json.loads(client.calls[2].text))
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate({"verdicts": [verdict("check")]})
