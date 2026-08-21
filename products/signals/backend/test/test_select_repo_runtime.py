import pytest
from unittest.mock import AsyncMock, patch

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.report_generation.select_repo import RepoSelectionResult, select_repository_for_team


@pytest.mark.asyncio
async def test_select_repository_for_team_uses_explicit_runtime_override() -> None:
    runtime = AgentRuntime(runtime_adapter="codex", model="gpt-5.5", reasoning_effort="high")
    selected = RepoSelectionResult(repository=None, reason="no match")

    with patch(
        "products.signals.backend.report_generation.select_repo.select_repository", new=AsyncMock(return_value=selected)
    ) as select:
        result = await select_repository_for_team(7, 8, "synthetic request", agent_runtime=runtime)

    assert result == selected
    select.assert_awaited_once()
    assert select.await_args.kwargs["runtime_adapter"] == "codex"
    assert select.await_args.kwargs["model"] == "gpt-5.5"
    assert select.await_args.kwargs["reasoning_effort"] == "high"
