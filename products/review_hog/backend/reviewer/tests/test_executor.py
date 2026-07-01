"""Tests for sandbox/executor.py — run_sandbox_review: inline identity, prompt combine, teardown."""

import pytest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized
from pydantic import BaseModel

from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

_EXECUTOR_PREFIX = "products.review_hog.backend.reviewer.sandbox.executor"


class DummyModel(BaseModel):
    result: str


class TestRunSandboxReview:
    @pytest.mark.asyncio
    async def test_success_returns_model_and_ends_session(self) -> None:
        # start() returns (session, parsed); the single-turn caller must end() the session afterwards
        # or the sandbox lingers until its TTL — assert both the return value and the teardown.
        mock_session = AsyncMock()
        parsed = DummyModel(result="ok")
        mock_start = AsyncMock(return_value=(mock_session, parsed))

        with patch(f"{_EXECUTOR_PREFIX}.MultiTurnSession.start", mock_start):
            result = await run_sandbox_review(
                team_id=1,
                user_id=2,
                repository="test/repo",
                branch="test-branch",
                prompt="user prompt",
                system_prompt="system prompt",
                model_to_validate=DummyModel,
                step_name="split",
            )

        assert result is parsed
        mock_session.end.assert_awaited_once()

        # System and user prompts are combined and the branch/step pass through to start().
        call_kwargs = mock_start.call_args.kwargs
        assert "system prompt" in call_kwargs["prompt"]
        assert "user prompt" in call_kwargs["prompt"]
        assert call_kwargs["branch"] == "test-branch"
        assert call_kwargs["step_name"] == "split"

    @pytest.mark.asyncio
    async def test_context_built_from_explicit_identity(self) -> None:
        # The sandbox context is assembled inline from the call's (team_id, user_id, repository) — no
        # ambient contextvar — so a team_id/user_id swap or a dropped repo would surface here. This is
        # the regression guard for threading identity explicitly across the Temporal worker boundary.
        mock_start = AsyncMock(return_value=(AsyncMock(), DummyModel(result="ok")))

        with patch(f"{_EXECUTOR_PREFIX}.MultiTurnSession.start", mock_start):
            await run_sandbox_review(
                team_id=7,
                user_id=9,
                repository="acme/app",
                branch="b",
                prompt="p",
                system_prompt="s",
                model_to_validate=DummyModel,
            )

        context = mock_start.call_args.kwargs["context"]
        assert (context.team_id, context.user_id, context.repository) == (7, 9, "acme/app")

    @parameterized.expand(
        [
            ("codex_pinned", "codex", "gpt-5.5", "xhigh", "full-access"),
            ("server_default", None, None, None, None),
        ]
    )
    @pytest.mark.asyncio
    async def test_model_pins_thread_into_context(
        self, _name, runtime_adapter, model, reasoning_effort, initial_permission_mode
    ) -> None:
        # The perspective review pins Codex + full-access on the sandbox context; a refactor that drops
        # one silently reverts the step to the agent server's default (Claude / prompting "auto"). The
        # unset case (chunk/dedup, which pass none) must stay None so those steps keep the default.
        mock_start = AsyncMock(return_value=(AsyncMock(), DummyModel(result="ok")))

        with patch(f"{_EXECUTOR_PREFIX}.MultiTurnSession.start", mock_start):
            await run_sandbox_review(
                team_id=1,
                user_id=2,
                repository="test/repo",
                branch="b",
                prompt="p",
                system_prompt="s",
                model_to_validate=DummyModel,
                runtime_adapter=runtime_adapter,
                model=model,
                reasoning_effort=reasoning_effort,
                initial_permission_mode=initial_permission_mode,
            )

        context = mock_start.call_args.kwargs["context"]
        assert (context.runtime_adapter, context.model, context.reasoning_effort, context.initial_permission_mode) == (
            runtime_adapter,
            model,
            reasoning_effort,
            initial_permission_mode,
        )

    @pytest.mark.asyncio
    async def test_start_failure_propagates(self) -> None:
        # start() ends its own session on failure and raises; run_sandbox_review re-raises (it must NOT
        # swallow, or the Temporal activity would see a success and never retry the transient flake).
        mock_start = AsyncMock(side_effect=RuntimeError("sandbox crashed"))

        with patch(f"{_EXECUTOR_PREFIX}.MultiTurnSession.start", mock_start):
            with pytest.raises(RuntimeError, match="sandbox crashed"):
                await run_sandbox_review(
                    team_id=1,
                    user_id=2,
                    repository="test/repo",
                    branch="b",
                    prompt="p",
                    system_prompt="s",
                    model_to_validate=DummyModel,
                )
