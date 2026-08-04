import pytest

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.report_generation.select_repo import (
    RepoSelectionRejectedError,
    RepoSelectionUnavailableError,
    select_repository_for_team,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raised,expected_no_repo_reason",
    [
        (RepoSelectionRejectedError("owner/hallucinated", "picked it anyway"), "agent_rejected"),
        (RepoSelectionUnavailableError("all candidates archived"), "no_eligible_repos"),
    ],
)
async def test_select_repository_for_team_tags_no_repo_reason(monkeypatch, raised, expected_no_repo_reason):
    # Regression: these two exceptions used to collapse into `RepoSelectionResult(repository=None, ...)`
    # with no way to tell them apart downstream, which is exactly what made the `no_repo` analytics
    # event untriageable. Each must map to its own `no_repo_reason` category.
    monkeypatch.setattr(
        "products.signals.backend.report_generation.select_repo.resolve_agent_runtime",
        lambda team_id, step: AgentRuntime(model=None, runtime_adapter=None, reasoning_effort=None),
    )

    async def fake_select_repository(*args, **kwargs):
        raise raised

    monkeypatch.setattr(
        "products.signals.backend.report_generation.select_repo.select_repository",
        fake_select_repository,
    )

    result = await select_repository_for_team(team_id=1, user_id=1, request_section="some signals")

    assert result.repository is None
    assert result.no_repo_reason == expected_no_repo_reason
