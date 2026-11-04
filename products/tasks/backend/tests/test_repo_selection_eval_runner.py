import asyncio
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from posthog.egress.limiter.policies import Priority

from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.tasks.backend.facade.repo_selection import RepoSelectionUsageLimitError
from products.tasks.evals.repo_selection import runner
from products.tasks.evals.repo_selection.fixtures import SELECTOR_CASES
from products.tasks.evals.repo_selection.runner import RepoSelectionArtifacts, run_selector

_SCENARIO = SELECTOR_CASES[0].scenario
_CONTEXT = CustomPromptSandboxContext(team_id=1, user_id=2, repository="posthog/hedgebox")
_TASK_RUN = SimpleNamespace(id="run-1", task_id="task-1", workflow_id="workflow-1")


async def _run(provider: MagicMock, *, artifacts: RepoSelectionArtifacts | None = None):
    return await run_selector(
        _SCENARIO,
        _CONTEXT,
        origin_product="signal_report",  # type: ignore[arg-type]
        priority=Priority.BATCH,
        provider=provider,
        on_cleanup=None,
        timeout_seconds=600,
        artifacts=artifacts,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,outcome",
    [
        (RepoSelectionUsageLimitError("API Error: 402"), "usage_limited"),
        (RuntimeError("agent failed during startup"), "error"),
    ],
)
async def test_selector_failure_is_not_scored_as_a_clean_exit(error: Exception, outcome: str) -> None:
    cascade_artifacts = RepoSelectionArtifacts(exit_code=0, stage="selector")
    with (
        patch.object(runner, "select_repository", side_effect=error),
        patch.object(runner, "_distinct_id", return_value=None),
        patch.object(runner, "_latest_task_run", return_value=None),
    ):
        result = await _run(MagicMock(), artifacts=cascade_artifacts)

    assert (result.artifacts.exit_code, result.artifacts.outcome) == (1, outcome)


@pytest.mark.asyncio
async def test_cancelled_selection_still_reclaims_its_sandbox() -> None:
    started = asyncio.Event()

    async def hang(**_kwargs: object) -> None:
        started.set()
        await asyncio.Event().wait()

    provider = MagicMock()
    with (
        patch.object(runner, "select_repository", side_effect=hang),
        patch.object(runner, "_distinct_id", return_value=None),
        patch.object(runner, "_latest_task_run", return_value=_TASK_RUN),
        patch.object(runner.tasks_api, "read_task_run_conversation_logs", return_value=""),
        patch.object(runner, "async_connect", side_effect=RuntimeError("no temporal")),
    ):
        case = asyncio.create_task(_run(provider))
        await started.wait()
        case.cancel()
        with pytest.raises(asyncio.CancelledError):
            await case

    provider.register_task.assert_called_with("task-1")
    provider.cleanup_case.assert_called_once_with("task-1")
