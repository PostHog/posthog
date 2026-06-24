"""Tests for sandbox/executor.py — run_sandbox_review, _run_prompt teardown, and the semaphore."""

import asyncio
from typing import Any

import pytest
from unittest.mock import AsyncMock, Mock, patch

from pydantic import BaseModel

from products.review_hog.backend.reviewer.sandbox import executor
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

_DUMMY_CONTEXT = CustomPromptSandboxContext(team_id=1, user_id=1, repository="test/repo")
# _sandbox_context_for is sync (it reads the run-scoped identity contextvar), so a plain Mock stands in.
_MOCK_SANDBOX_CTX = Mock(return_value=_DUMMY_CONTEXT)
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

        with (
            patch(f"{_EXECUTOR_PREFIX}.MultiTurnSession.start", mock_start),
            patch(f"{_EXECUTOR_PREFIX}._sandbox_context_for", _MOCK_SANDBOX_CTX),
        ):
            result = await run_sandbox_review(
                prompt="user prompt",
                system_prompt="system prompt",
                branch="test-branch",
                repository="test/repo",
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
    async def test_start_failure_returns_none(self) -> None:
        # start() ends its own session on failure and raises; _run_prompt swallows it and returns None.
        mock_start = AsyncMock(side_effect=RuntimeError("sandbox crashed"))

        with (
            patch(f"{_EXECUTOR_PREFIX}.MultiTurnSession.start", mock_start),
            patch(f"{_EXECUTOR_PREFIX}._sandbox_context_for", _MOCK_SANDBOX_CTX),
        ):
            result = await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                repository="test/repo",
                model_to_validate=DummyModel,
            )

        assert result is None


class TestSandboxIdentity:
    """The run-scoped identity binds (team_id, user_id) for every sandbox call in a run."""

    @pytest.mark.asyncio
    async def test_context_reflects_bound_identity(self) -> None:
        # _sandbox_context_for assembles the context from the bound identity + the call's repo —
        # a team_id/user_id swap or a dropped repo would surface here.
        token = executor._sandbox_identity.set((7, 9))
        try:
            ctx = executor._sandbox_context_for("acme/app")
        finally:
            executor._sandbox_identity.reset(token)
        assert (ctx.team_id, ctx.user_id, ctx.repository) == (7, 9, "acme/app")


class TestSemaphore:
    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_executions(self) -> None:
        concurrent_count = 0
        max_concurrent_seen = 0

        async def tracked_run(*args: Any, **kwargs: Any) -> DummyModel:
            nonlocal concurrent_count, max_concurrent_seen
            concurrent_count += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return DummyModel(result="ok")

        with (
            patch(f"{_EXECUTOR_PREFIX}._run_prompt", side_effect=tracked_run),
            patch(f"{_EXECUTOR_PREFIX}._sandbox_semaphore", asyncio.Semaphore(2)),
            patch(f"{_EXECUTOR_PREFIX}._sandbox_context_for", _MOCK_SANDBOX_CTX),
        ):
            tasks = [
                run_sandbox_review(
                    prompt="p",
                    system_prompt="s",
                    branch="b",
                    repository="test/repo",
                    model_to_validate=DummyModel,
                )
                for _ in range(5)
            ]
            results = await asyncio.gather(*tasks)

        assert all(isinstance(r, DummyModel) for r in results)
        assert max_concurrent_seen == 2

    @pytest.mark.asyncio
    async def test_semaphore_releases_on_error(self) -> None:
        # Drive the real _run_prompt so the failure path runs under the real `async with` release:
        # start() raises on the first call (run_sandbox_review returns None), and the semaphore slot
        # must be freed for the second call to acquire it — a leaked slot would deadlock this await.
        call_count = 0
        mock_session = AsyncMock()
        parsed = DummyModel(result="ok")

        async def failing_then_succeeding(*args: Any, **kwargs: Any) -> tuple[AsyncMock, DummyModel]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            return mock_session, parsed

        with (
            patch(f"{_EXECUTOR_PREFIX}.MultiTurnSession.start", side_effect=failing_then_succeeding),
            patch(f"{_EXECUTOR_PREFIX}._sandbox_semaphore", asyncio.Semaphore(1)),
            patch(f"{_EXECUTOR_PREFIX}._sandbox_context_for", _MOCK_SANDBOX_CTX),
        ):
            result1 = await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                repository="test/repo",
                model_to_validate=DummyModel,
            )
            result2 = await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                repository="test/repo",
                model_to_validate=DummyModel,
            )

        assert result1 is None
        assert result2 is parsed
