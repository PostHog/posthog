from __future__ import annotations

import os
import json
import hashlib
import tempfile
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

import httpx
from openai import AsyncOpenAI
from parameterized import parameterized

from products.posthog_ai.eval_harness.engines.braintrust import PrivateBraintrustEngine
from products.posthog_ai.eval_harness.engines.types import CaseHooks, CaseSpec, ExperimentResult, ExperimentSpec
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.ports import LLM_GATEWAY_PORT
from products.signals.evals.agentic.saved_case import SavedScoutCase
from products.signals.evals.agentic.saved_rubrics import SavedRubrics, SavedRubricScorer
from products.signals.evals.saved_scout import SavedScoutSuite

CANONICAL_INSTRUCTIONS = "Inspect the invented delivery queue and report missed deliveries."
CANONICAL_REFERENCE = "Report a missed delivery only after checking the recorded delivery date."
VARIANT_INSTRUCTIONS = "Ignore delivery dates and report every queued delivery."
HIDDEN_ANSWER = "Hidden synthetic answer: parcel-example missed its delivery."
EVALUATED_REPORT = "Evaluated synthetic report: parcel-example needs a delivery-date review."


def saved_case(directory: Path, *, instructions: str = CANONICAL_INSTRUCTIONS) -> SavedScoutCase:
    directory.mkdir(parents=True)

    def save(name: str, text: str) -> dict[str, str]:
        content = text.encode()
        (directory / name).write_bytes(content)
        return {"path": name, "sha256": hashlib.sha256(content).hexdigest()}

    manifest = {
        "schema_version": 2,
        "case_id": "delivery-fixture",
        "source_cutoff": "2026-01-02T00:00:00Z",
        "run_note": "PAGE_2_ASSIGNMENT: inspect the second page of the queue.",
        "skill": {
            "name": "signals-scout-delivery-fixture",
            "version": 1,
            "description": "Review an invented delivery queue.",
            "body": save("skill.md", instructions),
            "files": [{"path": "references/delivery.md", "content": save("delivery.md", CANONICAL_REFERENCE)}],
        },
        "state": {"checkpoint": "2026-01-02T00:00:00Z", "complete": True},
    }
    (directory / "hidden_answers.json").write_text(json.dumps({"answer": HIDDEN_ANSWER}))
    path = directory / "case.json"
    path.write_text(json.dumps(manifest))
    return SavedScoutCase.load(path)


class TestSavedScoutRubrics(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.saved = saved_case(self.directory / "case")
        self.pipeline = SavedRubrics(self.saved, self.directory / "session", self.directory / "run")
        self.requests: list[dict[str, object]] = []
        self.failure: str | None = None
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
        self.enterContext(
            patch(
                "posthog.helpers.tiktoken_encoding.get_tiktoken_encoding_for_model",
                return_value=SimpleNamespace(encode=lambda text, **kwargs: text.split()),
            )
        )
        self.enterContext(patch("posthog.llm.gateway_client.build_async_openai_client", side_effect=self._client))

    def _client(self, product: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key="invented-token",
            base_url="http://localhost/signals/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self._respond)),
        )

    def _respond(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        prompt = body["messages"][-1]["content"]
        judging = prompt.startswith("Evaluate a saved scout execution")
        stage = "judge" if judging else "generation"
        if self.failure == f"{stage}_provider":
            return httpx.Response(503, json={"error": {"message": "Invented provider unavailable"}})
        if self.failure == f"{stage}_format":
            text = "Incomplete JSON: {"
        elif judging:
            evidence = json.loads(prompt.rsplit("\n", 1)[1])
            text = json.dumps(
                {
                    "criteria": [
                        {
                            "id": criterion["id"],
                            "applicability": "applicable",
                            "status": "pass",
                            "rationale": "The invented report names the delivery-date review.",
                            "evidence": [{"source": "output", "pointer": "/summary", "quote": EVALUATED_REPORT}],
                        }
                        for criterion in evidence["rubric"]
                    ]
                }
            )
        elif "Numbered draft criteria:\n" in prompt:
            text = json.dumps({"summary": "Review missed deliveries and required reports.", "keep_indices": [0]})
        else:
            text = json.dumps(
                {
                    "summary": "Review missed deliveries and required reports.",
                    "suggestions": [
                        {
                            "title": "Were missed deliveries reviewed and reported?",
                            "description": "Check that the delivery queue was investigated and required reports were written.",
                            "pass_condition": "The scout checks delivery dates and reports missed deliveries under its rules.",
                            "applicability": "Every run; reports are needed when its reporting rules require them.",
                        }
                    ],
                }
            )
        return httpx.Response(
            200,
            json={
                "id": "invented-response",
                "object": "chat.completion",
                "created": 1,
                "model": "invented-resolved-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            },
        )

    def _output(self) -> dict[str, object]:
        return {"summary": EVALUATED_REPORT, "exit_code": 0, "raw_log": "Invented complete scout transcript."}

    async def test_prepares_once_and_scores_variants_against_the_original_reference(self) -> None:
        (self.saved.path.parent / "result.json").write_text(json.dumps({"output": self._output()}))
        rubric = await self.pipeline.prepare()
        original_bytes = rubric.path.read_bytes()
        self.assertEqual(len(rubric.document.criteria), 7)
        self.assertEqual(len(self.requests), 2)
        generation_input = json.dumps(self.requests)
        for excluded in (HIDDEN_ANSWER, EVALUATED_REPORT, "PAGE_2_ASSIGNMENT"):
            self.assertNotIn(excluded, generation_input)

        changed = saved_case(self.directory / "variant", instructions=VARIANT_INSTRUCTIONS)
        variant = SavedRubrics(
            changed,
            self.directory / "session",
            self.directory / "variant-run",
            generator_model="different-generator",
            judge_model="different-judge",
        )
        reused = await variant.prepare()
        self.assertEqual(reused.sha256, rubric.sha256)
        self.assertEqual(rubric.path.read_bytes(), original_bytes)
        self.assertEqual(len(self.requests), 2)

        output = {**self._output(), "instructions": VARIANT_INSTRUCTIONS}
        score = await SavedRubricScorer(variant, reused).eval_async(output)
        self.assertEqual(score.score, 1.0)
        assert score.metadata is not None
        path = Path(score.metadata["judgment_path"])
        sidecar = json.loads(path.read_text())
        self.assertEqual(sidecar["session_rubric_sha256"], rubric.sha256)
        self.assertEqual(len(sidecar["criteria"]), 7)
        judgment_metadata = output["rubric_judgment"]
        assert isinstance(judgment_metadata, dict)
        self.assertEqual(judgment_metadata["judgment_path"], str(path))
        judge_input = json.loads(sidecar["model_response"]["prompt"].rsplit("\n", 1)[1])
        self.assertEqual(judge_input["canonical_references"]["instructions"], CANONICAL_INSTRUCTIONS)
        self.assertEqual(judge_input["canonical_references"]["reference_files"][0]["content"], CANONICAL_REFERENCE)
        self.assertEqual(judge_input["output"]["instructions"], VARIANT_INSTRUCTIONS)

    @parameterized.expand(["completed", "execution_failed", "wrong_scout"])
    async def test_rejudging_preserves_saved_bytes_and_checks_result_identity(self, outcome: str) -> None:
        rubric = await self.pipeline.prepare()
        output = {**self._output(), "rubric_judgment": {"old_verdict": "must not become evidence"}}
        source = {
            "metadata": {"skill_name": "different-scout" if outcome == "wrong_scout" else self.saved.skill_name},
            "output": None if outcome == "execution_failed" else output,
            "error": "Invented sandbox failure" if outcome == "execution_failed" else None,
        }
        path = self.directory / "historical-result.json"
        original = (json.dumps(source, indent=3) + "\n\n").encode()
        path.write_bytes(original)
        if outcome == "wrong_scout":
            with self.assertRaisesRegex(ValueError, "does not identify this scout"):
                await self.pipeline.judge_saved(path, rubric)
            self.assertEqual(len(self.requests), 2)
            self.assertFalse((self.pipeline.output_dir / "judgments").exists())
        else:
            judgment, sidecar_path = await self.pipeline.judge_saved(path, rubric)
            sidecar = json.loads(sidecar_path.read_text())
            self.assertEqual(sidecar["source_result_sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(sidecar["source_result_path"], str(path))
            if outcome == "execution_failed":
                self.assertEqual(judgment.execution_status, "failed")
                self.assertTrue(all(row.status == "unknown" and row.score is None for row in judgment.criteria))
                self.assertEqual(len(self.requests), 2)
            else:
                self.assertIsNone(judgment.error)
                self.assertNotIn("old_verdict", sidecar["model_response"]["prompt"])
        self.assertEqual(path.read_bytes(), original)

    @parameterized.expand(["judge_provider", "judge_format"])
    async def test_failed_judging_writes_an_error_sidecar_without_a_passing_score(self, failure: str) -> None:
        rubric = await self.pipeline.prepare()
        self.failure = failure
        scorer = SavedRubricScorer(self.pipeline, rubric)
        score = await scorer.eval_async(self._output())

        self.assertIsNone(score.score)
        self.assertTrue(scorer.errors)
        assert score.metadata is not None
        sidecar = json.loads(Path(score.metadata["judgment_path"]).read_text())
        self.assertTrue(sidecar["error"])
        self.assertTrue(all(row["status"] == "error" and row["score"] is None for row in sidecar["criteria"]))
        self.assertEqual(sidecar["execution_status"], "completed")

    @parameterized.expand(["client_setup", "judgment_storage"])
    async def test_suite_fails_when_engine_retains_scorer_exception_separately(self, failure: str) -> None:
        await self.pipeline.prepare()
        if failure == "judgment_storage":
            (self.pipeline.output_dir / "judgments").write_text("An existing file prevents artifact storage.")
        results: list[ExperimentResult] = []

        async def task(_input: dict[str, object], _hooks: CaseHooks) -> dict[str, object]:
            return self._output()

        async def execute(*, scorers: Sequence[object], **_kwargs: object) -> ExperimentResult:
            result = await PrivateBraintrustEngine().run_experiment(
                ExperimentSpec(
                    project_name="private-scorer-failure",
                    cases=[CaseSpec(input={"name": "delivery-fixture"})],
                    task=task,
                    scorers=scorers,
                    trial_count=1,
                    is_public=False,
                    no_send_logs=True,
                    metadata={},
                )
            )
            results.append(result)
            return result

        suite = SavedScoutSuite(
            self.saved,
            self.saved.manifest.source_cutoff,
            self.pipeline.output_dir,
            None,
            session_dir=self.pipeline.session.directory,
        )
        with (
            override_settings(TEST=failure != "client_setup"),
            patch("products.signals.evals.saved_scout.private_backend_gateway", return_value=nullcontext()),
            patch("products.posthog_ai.eval_harness.workflow.WorkflowPrivateEval", new=execute),
        ):
            with self.assertRaisesRegex(RuntimeError, "could not be judged"):
                await suite.run(Mock(spec=EvalContext))

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].results[0].error)
        self.assertTrue(results[0].results[0].metadata["scorer_errors"])
        self.assertEqual(results[0].results[0].scores, {})

    @parameterized.expand(["generation_provider", "generation_format"])
    async def test_failed_generation_retains_attempt_without_pinning_a_rubric(self, failure: str) -> None:
        self.failure = failure
        with self.assertRaises((RuntimeError, ValueError)):
            await self.pipeline.prepare()

        self.assertEqual(list((self.directory / "session" / "rubrics").glob("*.json")), [])
        attempts = list(self.pipeline.output_dir.glob("rubric-generation-*.json"))
        self.assertEqual(len(attempts), 1)
        calls = json.loads(attempts[0].read_text())
        self.assertTrue(calls)
        self.assertTrue(calls[0]["error"] if failure.endswith("provider") else calls[0]["text"])
