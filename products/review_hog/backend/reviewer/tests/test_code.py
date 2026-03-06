"""Tests for app.llm.code module with focus on semaphore functionality."""

import asyncio
import importlib
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel

import products.review_hog.backend.reviewer.llm.code as code_module


class DummyModel(BaseModel):
    """Dummy model for testing."""

    result: str


class TestSemaphoreFunctionality:
    """Test semaphore rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_executions(self, tmp_path: Path) -> None:
        """Test that semaphore properly limits concurrent executions."""
        # Patch the constants and reload module
        with (
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CODEX", 2),
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CLAUDE", 2),
        ):
            importlib.reload(code_module)

            # Track concurrent executions
            concurrent_count = 0
            max_concurrent_seen = 0

            async def tracked_mock(self: Any) -> bool:
                nonlocal concurrent_count, max_concurrent_seen
                concurrent_count += 1
                max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
                # Simulate processing
                await asyncio.sleep(0.1)
                output_path = str(self.output_path)
                if output_path:
                    with Path(output_path).open("w") as f:
                        f.write('{"result": "success"}')
                concurrent_count -= 1
                return True

            with patch("app.llm.code.CodeExecutor._run_claude_code", tracked_mock):
                # Create 5 tasks that should be limited to 2 concurrent
                tasks = []
                for i in range(5):
                    output_path = tmp_path / f"output_{i}.json"
                    task = code_module.CodeExecutor(
                        prompt="test",
                        system_prompt="test",
                        project_dir=str(tmp_path),
                        output_path=str(output_path),
                        model_to_validate=DummyModel,
                    ).run_code()
                    tasks.append(task)

                # Run all tasks concurrently
                results = await asyncio.gather(*tasks)

                # Verify all succeeded
                assert all(results)
                # Verify max concurrent was limited to 2
                assert max_concurrent_seen == 2

    @pytest.mark.asyncio
    async def test_semaphore_queues_requests(self, tmp_path: Path) -> None:
        """Test that requests are queued when limit is reached."""
        with (
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CODEX", 1),
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CLAUDE", 1),
        ):
            importlib.reload(code_module)

            # Track execution order
            execution_order = []

            async def ordered_mock(self: Any) -> bool:
                output_path = str(self.output_path)
                task_id = output_path.split("_")[-1].replace(".json", "")
                execution_order.append(f"start_{task_id}")
                await asyncio.sleep(0.05)
                if output_path:
                    with Path(output_path).open("w") as f:
                        f.write('{"result": "success"}')
                execution_order.append(f"end_{task_id}")
                return True

            with patch("app.llm.code.CodeExecutor._run_claude_code", ordered_mock):
                # Create 3 tasks with semaphore limit of 1
                tasks = []
                for i in range(3):
                    output_path = tmp_path / f"output_{i}.json"
                    task = code_module.CodeExecutor(
                        prompt="test",
                        system_prompt="test",
                        project_dir=str(tmp_path),
                        output_path=str(output_path),
                        model_to_validate=DummyModel,
                    ).run_code()
                    tasks.append(task)

                await asyncio.gather(*tasks)

                # With limit of 1, executions should not overlap
                # Each task should complete before next starts
                for i in range(len(execution_order) - 1):
                    if execution_order[i].startswith("end_") and i + 1 < len(
                        execution_order
                    ):
                        # After an end, next should be a start (not another end)
                        assert execution_order[i + 1].startswith("start_")

    @pytest.mark.asyncio
    async def test_semaphore_works_with_codex(self, tmp_path: Path) -> None:
        """Test that semaphore works with OpenAI Codex backend."""
        with (
            patch.dict(
                os.environ,
                {
                    "USE_CODEX": "1",
                },
            ),
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CODEX", 2),
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CLAUDE", 2),
        ):
            importlib.reload(code_module)

            concurrent_count = 0
            max_concurrent_seen = 0

            async def tracked_mock(self: Any) -> bool:
                nonlocal concurrent_count, max_concurrent_seen
                concurrent_count += 1
                max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
                await asyncio.sleep(0.1)
                output_path = str(self.output_path)
                if output_path:
                    with Path(output_path).open("w") as f:
                        f.write('{"result": "success"}')
                concurrent_count -= 1
                return True

            with patch("app.llm.code.CodeExecutor._run_openai_codex", tracked_mock):
                tasks = []
                for i in range(4):
                    output_path = tmp_path / f"output_{i}.json"
                    task = code_module.CodeExecutor(
                        prompt="test",
                        system_prompt="test",
                        project_dir=str(tmp_path),
                        output_path=str(output_path),
                        model_to_validate=DummyModel,
                    ).run_code()
                    tasks.append(task)

                results = await asyncio.gather(*tasks)
                assert all(results)
                assert max_concurrent_seen == 2

    @pytest.mark.asyncio
    async def test_semaphore_releases_on_error(self, tmp_path: Path) -> None:
        """Test that semaphore is properly released even on errors."""
        with (
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CODEX", 1),
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CLAUDE", 1),
        ):
            importlib.reload(code_module)

            call_count = 0

            async def failing_mock(self: Any) -> bool:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # First call fails
                    raise Exception("Test error")
                # Second call succeeds
                output_path = str(self.output_path)
                if output_path:
                    with Path(output_path).open("w") as f:
                        f.write('{"result": "success"}')
                return True

            with patch("app.llm.code.CodeExecutor._run_claude_code", failing_mock):
                # First task should fail
                output_path_1 = tmp_path / "output_1.json"
                with pytest.raises(Exception, match="Test error"):
                    await code_module.CodeExecutor(
                        prompt="test",
                        system_prompt="test",
                        project_dir=str(tmp_path),
                        output_path=str(output_path_1),
                        model_to_validate=DummyModel,
                    ).run_code()

                # Second task should succeed (semaphore was released)
                output_path_2 = tmp_path / "output_2.json"
                result = await code_module.CodeExecutor(
                    prompt="test",
                    system_prompt="test",
                    project_dir=str(tmp_path),
                    output_path=str(output_path_2),
                    model_to_validate=DummyModel,
                ).run_code()
                assert result is True

    @pytest.mark.asyncio
    async def test_default_semaphore_limit(self, tmp_path: Path) -> None:
        """Test that default semaphore limit is set from constants."""
        # Patch the constants with different values
        with (
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CODEX", 10),
            patch("app.constants.MAX_CONCURRENT_CODE_RUNS_CLAUDE", 10),
        ):
            importlib.reload(code_module)

            # Check that the value is set correctly (10 for Claude, since USE_CODEX is not set)
            assert code_module._max_concurrent == 10

            async def simple_mock(self: Any) -> bool:
                output_path = str(self.output_path)
                if output_path:
                    with Path(output_path).open("w") as f:
                        f.write('{"result": "success"}')
                return True

            with patch("app.llm.code.CodeExecutor._run_claude_code", simple_mock):
                # Run a single task to ensure it works with default
                output_path = tmp_path / "output.json"
                result = await code_module.CodeExecutor(
                    prompt="test",
                    system_prompt="test",
                    project_dir=str(tmp_path),
                    output_path=str(output_path),
                    model_to_validate=DummyModel,
                ).run_code()
                assert result is True
