import os
import json
import asyncio
import hashlib
import tempfile
import subprocess
from collections.abc import Sequence
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

import httpx
from asgiref.sync import async_to_sync
from openai import AsyncOpenAI
from parameterized import parameterized

from posthog.llm.gateway_client import build_async_anthropic_client
from posthog.models import PersonalAPIKey
from posthog.models.utils import hash_key_value

from products.posthog_ai.eval_harness.base import EvalTaskError
from products.posthog_ai.eval_harness.harness.cli import HarnessOptions, parse_args
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.discovery import EvalSuite
from products.posthog_ai.eval_harness.harness.ports import LLM_GATEWAY_PORT
from products.posthog_ai.eval_harness.harness.providers import PreflightError
from products.posthog_ai.eval_harness.harness.services import start_mcp_server
from products.signals.backend.rubrics_schema import default_criteria
from products.signals.backend.test.test_saved_case import SOURCE, TARGET, file_reference, write_case
from products.signals.evals.agentic.rubric_session import RubricSession, RubricSnapshot, SessionRubric
from products.signals.evals.agentic.saved_case import SavedRepository, SavedScoutCase, SavedScoutInstructions
from products.signals.evals.saved_scout import SavedScoutSuite, main, require_private_path, run_saved_case


def test_private_case_rejects_tracked_file_and_symlink_to_it(tmp_path: Path) -> None:
    tracked = Path(__file__).resolve()
    alias = tmp_path / "case.json"
    alias.symlink_to(tracked)
    for path in (tracked, alias):
        with pytest.raises(ValueError, match="outside Git or ignored"):
            require_private_path(path)
    assert require_private_path(tmp_path / "results") == tmp_path / "results"
    sibling = tmp_path / "other-repository"
    subprocess.run(["git", "init", str(sibling)], check=True, capture_output=True)
    (sibling / ".gitignore").write_text("private/\n")
    with pytest.raises(ValueError, match="outside Git or ignored"):
        require_private_path(sibling / "results")
    assert require_private_path(sibling / "private" / "results") == sibling / "private" / "results"


class TestSavedScoutPreflight(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(os.umask, os.umask(0o077))
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.case_path = write_case(self.directory)
        self.output_dir = self.directory / "results"
        self.env_file = self.directory / ".env"
        self.env_file.write_text(
            "SANDBOX_JWT_PRIVATE_KEY=test-signing-key\n"
            "LLM_GATEWAY_ANTHROPIC_API_KEY=test-anthropic-key\n"
            "LLM_GATEWAY_OPENAI_API_KEY=test-openai-key\n"
        )
        self.gateway = self.directory / "services" / "llm-gateway" / ".venv" / "bin" / "uvicorn"
        self.gateway.parent.mkdir(parents=True)
        self.gateway.write_text("#!/bin/sh\nexit 0\n")
        self.gateway.chmod(0o700)
        self.docker = self.directory / "bin" / "docker"
        self.docker.parent.mkdir()
        self.docker.write_text('#!/bin/sh\n[ "$1" = info ]\n')
        self.docker.chmod(0o700)
        self.enterContext(patch.dict(os.environ, {"PATH": f"{self.docker.parent}:{os.defpath}"}, clear=True))
        self.enterContext(patch("products.signals.evals.saved_scout.REPO_ROOT", self.directory))
        self.enterContext(patch("products.posthog_ai.eval_harness.harness.env_preflight.REPO_ROOT", self.directory))
        self.enterContext(
            patch(
                "products.signals.evals.saved_scout.setup_django", side_effect=AssertionError("Django must not start")
            )
        )

    def _cache_rubric(self) -> RubricSnapshot:
        saved = SavedScoutInstructions.load(self.case_path)

        async def fixed_rubric() -> SessionRubric:
            return SessionRubric(
                scout_name=saved.skill_name,
                generated_at=SOURCE,
                criteria=default_criteria(),
                canonical_references={
                    "instructions": saved.manifest.skill.body.resolve(saved.path.parent).read_text(),
                    "source_cutoff": saved.manifest.source_cutoff.isoformat(),
                },
                source=saved.metadata,
                generation={"model": "fixture-model"},
            )

        return async_to_sync(RubricSession(self.output_dir).get_or_create)(saved.skill_name, fixed_rubric)

    @parameterized.expand(
        [
            ("skill", "checksum"),
            ("skill", "missing"),
            ("skill", "traversal"),
            ("skill", "non_utf8"),
            ("reference", "checksum"),
            ("reference", "missing"),
            ("reference", "traversal"),
            ("reference", "non_utf8"),
            ("reference", "duplicate"),
            ("reference", "support_path"),
        ]
    )
    def test_cached_rubric_does_not_bypass_instruction_file_validation(self, target: str, failure: str) -> None:
        reference_path = self.directory / "reference.md"
        reference_path.write_text("Inspect the invented API response before reporting a defect.")
        manifest = json.loads(self.case_path.read_text())
        manifest["skill"]["files"] = [{"path": "references/rules.md", "content": file_reference(reference_path)}]
        self.case_path.write_text(json.dumps(manifest))
        rubric = self._cache_rubric()
        original_rubric = rubric.path.read_bytes()
        original_pin = rubric.path.with_suffix(".lock").read_bytes()
        reference = manifest["skill"]["body"] if target == "skill" else manifest["skill"]["files"][0]["content"]
        path = self.directory / reference["path"]
        if failure == "checksum":
            path.write_text("Changed instructions without changing the recorded checksum.")
        elif failure == "missing":
            path.unlink()
        elif failure == "traversal":
            reference["path"] = "../outside.md"
        elif failure == "non_utf8":
            path.write_bytes(b"\xff")
            reference["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif failure == "duplicate":
            manifest["skill"]["files"].append(manifest["skill"]["files"][0])
        elif failure == "support_path":
            manifest["skill"]["files"][0]["path"] = "../rules.md"
        self.case_path.write_text(json.dumps(manifest))

        with self.assertRaises((ValueError, FileNotFoundError)):
            main(["--case", str(self.case_path), "--output-dir", str(self.output_dir), "--rubric-only"])

        self.assertEqual(rubric.path.read_bytes(), original_rubric)
        self.assertEqual(rubric.path.with_suffix(".lock").read_bytes(), original_pin)

    @parameterized.expand(["launcher", "suite"])
    def test_execution_rejects_an_instructions_only_source(self, entrypoint: str) -> None:
        saved = SavedScoutInstructions.load(self.case_path)
        with self.assertRaisesRegex(TypeError, "Scout execution requires a fully validated SavedScoutCase"):
            if entrypoint == "launcher":
                run_saved_case(saved, parse_args(["--agent-runtime", "codex"]), SOURCE, self.output_dir)
            else:
                suite = SavedScoutSuite(saved, SOURCE, self.output_dir, None)
                async_to_sync(suite.run)(Mock(spec=EvalContext))

    @parameterized.expand(["rubric_only", "judge_results"])
    def test_historical_modes_accept_unrestorable_history_and_preserve_provenance(self, mode: str) -> None:
        report_id = "00000000-0000-4000-8000-000000000001"
        write_case(
            self.directory,
            state={
                "checkpoint": SOURCE.isoformat(),
                "complete": True,
                "reports": [{"id": report_id, "created_at": SOURCE.isoformat(), "status": "ready"}],
                "report_artefacts": [
                    {
                        "id": "00000000-0000-4000-8000-000000000002",
                        "created_at": SOURCE.isoformat(),
                        "report_id": report_id,
                        "type": "task_run",
                        "content": json.dumps({"run_id": "00000000-0000-4000-8000-000000000003"}),
                    }
                ],
            },
        )
        rubric = self._cache_rubric()
        original_manifest = self.case_path.read_bytes()
        original_rubric = rubric.path.read_bytes()
        result_path = self.directory / "historical-result.json"
        original_result = (
            json.dumps(
                {
                    "metadata": {
                        "skill_name": "signals-scout-fixture",
                        "source_cutoff": SOURCE.isoformat(),
                        "target_cutoff": TARGET.isoformat(),
                    },
                    "output": None,
                    "error": "Invented historical execution failure.",
                },
                indent=3,
            )
            + "\n\n"
        ).encode()
        result_path.write_bytes(original_result)

        def capture_source(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes | str]:
            if command == ["git", "rev-parse", "--show-toplevel"]:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="not a git repository")
            outputs: dict[tuple[str, ...], bytes | str] = {
                ("docker", "info"): b"",
                ("git", "diff", "HEAD", "--binary"): b"",
                ("git", "rev-parse", "HEAD"): "a" * 40,
                ("git", "ls-files", "--others", "--exclude-standard", "-z"): "",
            }
            return subprocess.CompletedProcess(command, 0, stdout=outputs[tuple(command)])

        def harness(_options: HarnessOptions, *, engine: object, suites: Sequence[EvalSuite]) -> SimpleNamespace:
            def run() -> int:
                for suite in suites:
                    async_to_sync(suite.fn)(Mock(spec=EvalContext))
                return 0

            return SimpleNamespace(run=run)

        def unexpected_request(_request: httpx.Request) -> httpx.Response:
            raise AssertionError("Cached rubrics and failed historical executions need no model call")

        def client(_product: str) -> AsyncOpenAI:
            return AsyncOpenAI(
                api_key="invented-token",
                base_url="http://localhost/signals/v1",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)),
            )

        with (
            override_settings(
                TEST=True,
                LLM_GATEWAY_URL=f"http://localhost:{LLM_GATEWAY_PORT}",
                LLM_GATEWAY_API_KEY="phx_invented_test_key",
                AI_GATEWAY_URL="",
                AI_GATEWAY_API_KEY="",
            ),
            patch("products.signals.evals.saved_scout.subprocess.run", side_effect=capture_source),
            patch("products.signals.evals.saved_scout.setup_django"),
            patch("products.signals.evals.saved_scout.configure_logging"),
            patch("products.signals.evals.saved_scout.logging.shutdown"),
            patch("products.signals.evals.saved_scout.private_backend_gateway", return_value=nullcontext()),
            patch("products.posthog_ai.eval_harness.harness.lifecycle.SandboxedEvalHarness", new=harness),
            patch("posthog.llm.gateway_client.build_async_openai_client", side_effect=client),
        ):
            self.assertEqual(
                main(
                    [
                        "--case",
                        str(self.case_path),
                        "--output-dir",
                        str(self.output_dir),
                        "--target-cutoff",
                        TARGET.isoformat(),
                        "--agent-runtime",
                        "codex",
                        *(["--rubric-only"] if mode == "rubric_only" else ["--judge-results", str(result_path)]),
                    ]
                ),
                0,
            )

        history_paths = list(self.output_dir.glob("invocations/*/invocation.json"))
        self.assertEqual(len(history_paths), 1)
        history = json.loads(history_paths[0].read_text())
        self.assertEqual(history["mode"], mode)
        self.assertIsNone(history["target_cutoff"])
        self.assertEqual(history["case"]["validation_scope"], "instructions")
        self.assertEqual(history["case"]["source_cutoff"], SOURCE.isoformat())
        self.assertEqual(history["case_sha256"], hashlib.sha256(original_manifest).hexdigest())
        self.assertEqual(history["source_commit"], "a" * 40)
        judgments = list(self.output_dir.glob("invocations/*/judgments/*.json"))
        self.assertEqual(len(judgments), int(mode == "judge_results"))
        if judgments:
            judgment = json.loads(judgments[0].read_text())
            self.assertEqual(judgment["source_result_sha256"], hashlib.sha256(original_result).hexdigest())
            self.assertEqual(judgment["source_result_path"], str(result_path))
            self.assertEqual(judgment["execution_status"], "failed")
        self.assertEqual(self.case_path.read_bytes(), original_manifest)
        self.assertEqual(result_path.read_bytes(), original_result)
        self.assertEqual(rubric.path.read_bytes(), original_rubric)

    @parameterized.expand(["--validate-only", "--preflight-only"])
    def test_read_only_modes_do_not_start_execution(self, mode: str) -> None:
        if mode == "--validate-only":
            self.env_file.unlink()
            self.gateway.unlink()
            self.docker.unlink()

        assert (
            main(
                [
                    "--case",
                    str(self.case_path),
                    "--output-dir",
                    str(self.output_dir),
                    "--target-cutoff",
                    SOURCE.isoformat(),
                    "--agent-runtime",
                    "codex",
                    mode,
                ]
            )
            == 0
        )
        assert not self.output_dir.exists()

    @parameterized.expand(
        [
            ("missing_environment", "LLM_GATEWAY_OPENAI_API_KEY"),
            ("missing_gateway", "local LLM gateway executable"),
            ("nonexecutable_gateway", "local LLM gateway executable"),
            ("unavailable_docker", "Docker daemon is not reachable"),
            ("repository_with_modal", "require --provider docker"),
        ]
    )
    def test_run_rejects_missing_prerequisites_before_django(self, failure: str, message: str) -> None:
        saved = SavedScoutCase.load(self.case_path)
        options = parse_args(["--agent-runtime", "codex"])
        if failure == "missing_environment":
            self.env_file.write_text(
                self.env_file.read_text().replace("LLM_GATEWAY_OPENAI_API_KEY=test-openai-key\n", "")
            )
        elif failure == "missing_gateway":
            self.gateway.unlink()
        elif failure == "nonexecutable_gateway":
            self.gateway.chmod(0o600)
        elif failure == "unavailable_docker":
            self.docker.write_text("#!/bin/sh\nexit 1\n")
        elif failure == "repository_with_modal":
            saved = SavedScoutCase(
                saved.path,
                saved.manifest.model_copy(
                    update={"repository": SavedRepository(source_path=str(self.directory), commit="a" * 40)}
                ),
                saved.state,
            )
            options = parse_args(["--provider", "modal"])

        with self.assertRaisesRegex(PreflightError, message) as error:
            run_saved_case(saved, options, SOURCE, self.output_dir)
        if failure == "missing_environment":
            self.assertIn(str(self.env_file), str(error.exception))
            self.assertNotIn("hogli evals:sandboxed", str(error.exception))
        elif failure == "missing_gateway":

            def capture_source(
                command: list[str], **_kwargs: object
            ) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
                if command == ["git", "rev-parse", "--show-toplevel"]:
                    return subprocess.CompletedProcess(command, 1, stdout="", stderr="not a git repository")
                if command == ["git", "diff", "HEAD", "--binary"]:
                    self.case_path.write_text(self.case_path.read_text() + "\n")
                    return subprocess.CompletedProcess(command, 0, stdout=b"")
                if command == ["git", "rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(command, 0, stdout="a" * 40)
                if command == ["git", "ls-files", "--others", "--exclude-standard", "-z"]:
                    return subprocess.CompletedProcess(command, 0, stdout="")
                raise AssertionError(f"Unexpected source command: {command}")

            with (
                patch("products.signals.evals.saved_scout.subprocess.run", side_effect=capture_source),
                patch("products.signals.evals.saved_scout.logging.basicConfig"),
                patch("products.signals.evals.saved_scout.logging.shutdown"),
            ):
                self.assertEqual(
                    main(
                        [
                            "--case",
                            str(self.case_path),
                            "--output-dir",
                            str(self.output_dir),
                            "--target-cutoff",
                            SOURCE.isoformat(),
                            "--agent-runtime",
                            "codex",
                        ]
                    ),
                    1,
                )
            history_paths = list(self.output_dir.glob("invocations/*/invocation.json"))
            self.assertEqual(len(history_paths), 1)
            history = json.loads(history_paths[0].read_text())
            self.assertEqual(history["case_sha256"], saved.manifest_sha256)
            self.assertEqual(history["case"]["manifest_sha256"], saved.manifest_sha256)

    def test_private_run_disables_inherited_mcp_capture_and_preserves_accounting_settings(self) -> None:
        saved = SavedScoutCase.load(self.case_path)
        options = parse_args(["--agent-runtime", "codex"])
        (self.directory / "services" / "mcp" / "node_modules").mkdir(parents=True)

        def start_services() -> int:
            start_mcp_server("http://localhost:18000", None, exec_skills_enabled=False)
            return 0

        with (
            patch.dict(
                os.environ,
                {
                    "POSTHOG_ANALYTICS_API_KEY": "phc_invented_fixture",
                    "POSTHOG_ANALYTICS_HOST": "https://analytics.example.com",
                    "LLM_GATEWAY_METRICS_ENABLED": "true",
                    "LLM_GATEWAY_REDIS_URL": "redis://localhost:6379/5",
                },
            ),
            patch("products.signals.evals.saved_scout.setup_django"),
            patch("products.signals.evals.saved_scout.configure_logging"),
            patch("products.posthog_ai.eval_harness.harness.services.settings.BASE_DIR", self.directory),
            patch(
                "products.posthog_ai.eval_harness.harness.lifecycle.SandboxedEvalHarness.run",
                side_effect=start_services,
            ),
            patch(
                "products.posthog_ai.eval_harness.harness.services.LONG_LIVED_SUBPROCESSES.start",
                return_value=(Mock(), Mock()),
            ) as start,
        ):
            self.assertEqual(run_saved_case(saved, options, SOURCE, self.output_dir), 0)

        environment = start.call_args.kwargs["env"]
        self.assertEqual(environment["POSTHOG_ANALYTICS_API_KEY"], "")
        self.assertEqual(environment["POSTHOG_ANALYTICS_HOST"], "")
        self.assertEqual(environment["LLM_GATEWAY_METRICS_ENABLED"], "true")
        self.assertEqual(environment["LLM_GATEWAY_REDIS_URL"], "redis://localhost:6379/5")
        self.assertEqual(environment["LLM_GATEWAY_ANTHROPIC_API_KEY"], "test-anthropic-key")
        self.assertEqual(environment["LLM_GATEWAY_OPENAI_API_KEY"], "test-openai-key")


class TestSavedScoutSuite(BaseTest):
    @parameterized.expand(
        [
            ("skipped", {"summary": "preflight skipped", "run_id": None}, EvalTaskError),
            ("missing_log", {"run_id": "run", "task_run_id": "task", "raw_log": ""}, EvalTaskError),
            (
                "failed",
                {
                    "run_id": "run",
                    "task_run_id": "task",
                    "raw_log": "log",
                    "artifacts": {"task_run": {"status": "failed"}},
                },
                EvalTaskError,
            ),
            (
                "completed",
                {
                    "run_id": "run",
                    "task_run_id": "task",
                    "raw_log": "log",
                    "artifacts": {"task_run": {"status": "completed"}},
                },
                None,
            ),
            ("workflow_error", {}, RuntimeError),
            ("cancelled", {}, asyncio.CancelledError),
        ]
    )
    def test_saved_scout_routes_backend_privately_and_cleans_up(
        self, ending: str, output: dict[str, Any], error: type[BaseException] | None
    ) -> None:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        saved = SavedScoutCase.load(write_case(directory))
        suite = SavedScoutSuite(saved, datetime.now(UTC), directory / "session", None)

        async def fixed_rubric() -> SessionRubric:
            return SessionRubric(
                scout_name=saved.skill_name,
                generated_at=datetime.now(UTC),
                criteria=default_criteria(),
                canonical_references={"instructions": "Review the fixture."},
                source={},
                generation={"model": "fixture-model"},
            )

        async_to_sync(RubricSession(suite.session_dir).get_or_create)(saved.skill_name, fixed_rubric)
        ctx = Mock(spec=EvalContext, demo_data=SimpleNamespace(master_team_id=self.team.id))
        created_key_ids: list[str] = []
        existing_key_ids = set(PersonalAPIKey.objects.values_list("id", flat=True))

        async def execute(**kwargs: Any) -> SimpleNamespace:
            async with build_async_anthropic_client(
                product="signals", ai_product="signals_safety", team_id=self.team.id, use_bedrock_fallback=True
            ) as client:
                self.assertEqual(str(client.base_url), f"http://localhost:{LLM_GATEWAY_PORT}/signals/")
                self.assertEqual(settings.AI_GATEWAY_URL, "")
                self.assertEqual(settings.AI_GATEWAY_API_KEY, "")
                self.assertEqual(settings.SANDBOX_AI_GATEWAY_URL, "")
                self.assertEqual(settings.SANDBOX_AI_GATEWAY_PRODUCTS, [])
                assert isinstance(client.api_key, str)
                self.assertNotEqual(client.api_key, "original-dev-token")
                key = await PersonalAPIKey.objects.aget(secure_value=hash_key_value(client.api_key))
                self.assertEqual(key.user_id, self.user.id)
                self.assertEqual(key.scopes, ["llm_gateway:read"])
                self.assertEqual(key.scoped_teams, [self.team.id])
                created_key_ids.append(key.id)
                self.assertNotIn(client.api_key, repr(kwargs))
                if ending == "workflow_error":
                    raise RuntimeError("workflow failed")
                if ending == "cancelled":
                    raise asyncio.CancelledError("workflow cancelled")
                result = await kwargs["task"](kwargs["cases"][0], Mock(), ctx, SimpleNamespace(metadata={}))
                self.assertNotIn(client.api_key, repr(result))
                return SimpleNamespace(results=[SimpleNamespace(error=None, output=result)])

        with (
            override_settings(
                LLM_GATEWAY_URL="https://dev-gateway.example.com",
                LLM_GATEWAY_API_KEY="original-dev-token",
                AI_GATEWAY_URL="https://go-gateway.example.com/v1",
                AI_GATEWAY_API_KEY="original-go-token",
                SANDBOX_AI_GATEWAY_URL="https://go-gateway.example.com/v1",
                SANDBOX_AI_GATEWAY_PRODUCTS="signals_scout",
            ),
            patch("products.signals.evals.agentic.runners.run_scout", new=AsyncMock(return_value=output)),
            patch("products.posthog_ai.eval_harness.workflow.WorkflowPrivateEval", new=execute),
        ):
            with self.assertRaises(error) if error is not None else nullcontext():
                async_to_sync(suite.run)(ctx)
            self.assertEqual(settings.LLM_GATEWAY_URL, "https://dev-gateway.example.com")
            self.assertEqual(settings.LLM_GATEWAY_API_KEY, "original-dev-token")
            self.assertEqual(settings.AI_GATEWAY_URL, "https://go-gateway.example.com/v1")
            self.assertEqual(settings.AI_GATEWAY_API_KEY, "original-go-token")
            self.assertEqual(settings.SANDBOX_AI_GATEWAY_URL, "https://go-gateway.example.com/v1")
            self.assertEqual(settings.SANDBOX_AI_GATEWAY_PRODUCTS, "signals_scout")
        self.assertEqual(len(created_key_ids), 1)
        self.assertFalse(PersonalAPIKey.objects.filter(id__in=created_key_ids).exists())
        self.assertEqual(set(PersonalAPIKey.objects.values_list("id", flat=True)), existing_key_ids)
