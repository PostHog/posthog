import asyncio
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
from django.test import override_settings

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.llm.gateway_client import build_async_anthropic_client
from posthog.models import PersonalAPIKey
from posthog.models.utils import hash_key_value

from products.posthog_ai.eval_harness.base import EvalTaskError
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.ports import LLM_GATEWAY_PORT
from products.signals.evals.agentic.datasets import ScoutCase
from products.signals.evals.agentic.saved_case import SavedScoutCase
from products.signals.evals.saved_scout import SavedScoutSuite, require_private_path


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
