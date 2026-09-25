import os
import json
import asyncio
import tempfile
import subprocess
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

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.llm.gateway_client import build_async_anthropic_client
from posthog.models import PersonalAPIKey
from posthog.models.utils import hash_key_value

from products.posthog_ai.eval_harness.base import EvalTaskError
from products.posthog_ai.eval_harness.harness.cli import parse_args
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.ports import LLM_GATEWAY_PORT
from products.posthog_ai.eval_harness.harness.providers import PreflightError
from products.signals.backend.test.test_saved_case import SOURCE, write_case
from products.signals.evals.agentic.datasets import ScoutCase
from products.signals.evals.agentic.saved_case import SavedRepository, SavedScoutCase
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
        saved = Mock(spec=SavedScoutCase)
        saved.to_scout_case.return_value = ScoutCase(
            case_id="fixture", step="scout", skill_name="signals-scout-fixture"
        )
        saved.metadata = {}
        suite = SavedScoutSuite(saved, datetime.now(UTC), Path("unused"), None)
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
        self.assertEqual(len(created_key_ids), 1)
        self.assertFalse(PersonalAPIKey.objects.filter(id__in=created_key_ids).exists())
        self.assertEqual(set(PersonalAPIKey.objects.values_list("id", flat=True)), existing_key_ids)
