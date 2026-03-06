"""Tests for sandbox/executor.py — run_sandbox_review and semaphore."""

import json
import asyncio
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel

from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review


class DummyModel(BaseModel):
    result: str


class TestRunSandboxReview:
    """Test run_sandbox_review function."""

    @pytest.mark.asyncio
    async def test_success(self, tmp_path: Path) -> None:
        output_path = tmp_path / "output.json"
        mock_run = AsyncMock(return_value=('{"result": "ok"}', "full log content"))

        with patch("products.review_hog.backend.reviewer.sandbox.executor.run_review", mock_run):
            result = await run_sandbox_review(
                prompt="user prompt",
                system_prompt="system prompt",
                branch="test-branch",
                output_path=str(output_path),
                model_to_validate=DummyModel,
            )

        assert result is True
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["result"] == "ok"

        # Verify combined prompt was passed
        call_kwargs = mock_run.call_args.kwargs
        assert "system prompt" in call_kwargs["prompt"]
        assert "user prompt" in call_kwargs["prompt"]
        assert call_kwargs["branch"] == "test-branch"

    @pytest.mark.asyncio
    async def test_saves_logs(self, tmp_path: Path) -> None:
        output_path = tmp_path / "output.json"
        mock_run = AsyncMock(return_value=('{"result": "ok"}', "line1\nline2\n"))

        with patch("products.review_hog.backend.reviewer.sandbox.executor.run_review", mock_run):
            await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                output_path=str(output_path),
                model_to_validate=DummyModel,
            )

        log_path = tmp_path / "output_logs.txt"
        assert log_path.exists()
        assert log_path.read_text() == "line1\nline2\n"

    @pytest.mark.asyncio
    async def test_sandbox_execution_failure(self, tmp_path: Path) -> None:
        output_path = tmp_path / "output.json"
        mock_run = AsyncMock(side_effect=RuntimeError("sandbox crashed"))

        with patch("products.review_hog.backend.reviewer.sandbox.executor.run_review", mock_run):
            result = await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                output_path=str(output_path),
                model_to_validate=DummyModel,
            )

        assert result is False
        assert not output_path.exists()

    @pytest.mark.asyncio
    async def test_empty_agent_message(self, tmp_path: Path) -> None:
        output_path = tmp_path / "output.json"
        mock_run = AsyncMock(return_value=("", "some log"))

        with patch("products.review_hog.backend.reviewer.sandbox.executor.run_review", mock_run):
            result = await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                output_path=str(output_path),
                model_to_validate=DummyModel,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_invalid_json_in_response(self, tmp_path: Path) -> None:
        output_path = tmp_path / "output.json"
        mock_run = AsyncMock(return_value=("not valid json at all", "log"))

        with patch("products.review_hog.backend.reviewer.sandbox.executor.run_review", mock_run):
            result = await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                output_path=str(output_path),
                model_to_validate=DummyModel,
            )

        assert result is False
        # Error file should be saved
        error_path = tmp_path / "output_error.txt"
        assert error_path.exists()
        assert error_path.read_text() == "not valid json at all"

    @pytest.mark.asyncio
    async def test_validation_failure(self, tmp_path: Path) -> None:
        output_path = tmp_path / "output.json"
        # Valid JSON but doesn't match DummyModel (missing required field)
        mock_run = AsyncMock(return_value=('{"wrong_field": "value"}', "log"))

        with patch("products.review_hog.backend.reviewer.sandbox.executor.run_review", mock_run):
            result = await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                output_path=str(output_path),
                model_to_validate=DummyModel,
            )

        assert result is False


class TestSemaphore:
    """Test semaphore rate limiting."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_executions(self, tmp_path: Path) -> None:
        concurrent_count = 0
        max_concurrent_seen = 0

        async def tracked_run(**kwargs: Any) -> tuple[str, str]:
            nonlocal concurrent_count, max_concurrent_seen
            concurrent_count += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return '{"result": "ok"}', "log"

        with (
            patch("products.review_hog.backend.reviewer.sandbox.executor.run_review", side_effect=tracked_run),
            patch("products.review_hog.backend.reviewer.sandbox.executor._sandbox_semaphore", asyncio.Semaphore(2)),
        ):
            tasks = []
            for i in range(5):
                output_path = tmp_path / f"output_{i}.json"
                task = run_sandbox_review(
                    prompt="p",
                    system_prompt="s",
                    branch="b",
                    output_path=str(output_path),
                    model_to_validate=DummyModel,
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks)

        assert all(results)
        assert max_concurrent_seen == 2

    @pytest.mark.asyncio
    async def test_semaphore_releases_on_error(self, tmp_path: Path) -> None:
        call_count = 0

        async def failing_then_succeeding(**kwargs: Any) -> tuple[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            return '{"result": "ok"}', "log"

        with (
            patch(
                "products.review_hog.backend.reviewer.sandbox.executor.run_review",
                side_effect=failing_then_succeeding,
            ),
            patch("products.review_hog.backend.reviewer.sandbox.executor._sandbox_semaphore", asyncio.Semaphore(1)),
        ):
            # First call fails
            result1 = await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                output_path=str(tmp_path / "out1.json"),
                model_to_validate=DummyModel,
            )
            assert result1 is False

            # Second call should succeed (semaphore released)
            result2 = await run_sandbox_review(
                prompt="p",
                system_prompt="s",
                branch="b",
                output_path=str(tmp_path / "out2.json"),
                model_to_validate=DummyModel,
            )
            assert result2 is True
