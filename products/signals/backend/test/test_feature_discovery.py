from collections.abc import Awaitable, Callable

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.artefact_schemas import FeatureLifecycle, FeatureStage, Priority
from products.signals.backend.features.discovery import (
    DiscoveredFeatureCodeReference,
    DiscoveredFeatureDocument,
    DiscoveredFeatureOwner,
    FeatureDiscoveryContinuation,
    FeatureDiscoveryExploration,
    FeatureDiscoveryResult,
    persist_discovered_features,
    run_multi_turn_feature_discovery,
)
from products.signals.backend.features.types import FeatureDiscoveryWorkflowInput
from products.signals.backend.models import FeatureDiscoveryRun, SignalReport, SignalReportArtefact
from products.signals.backend.temporal.feature_discovery import (
    FeatureDiscoveryFailedInput,
    mark_feature_discovery_failed_activity,
    run_feature_discovery_activity,
)
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.tasks.backend.models import Task, TaskRun


def _exploration() -> FeatureDiscoveryExploration:
    return FeatureDiscoveryExploration(
        codebase_overview="The app has a replay product.",
        repositories_examined=["PostHog/posthog"],
        has_candidates=True,
        discovery_strategy="Treat the replay journey as one feature.",
    )


def _feature(title: str = "Session replay") -> DiscoveredFeatureDocument:
    return DiscoveredFeatureDocument(
        title=title,
        summary="Users can record and replay browser sessions.\n\n## Outcome\n\nUnderstand behavior.",
        repository="PostHog/posthog",
        related_repositories=[],
        owners=[DiscoveredFeatureOwner(github_login="owner", reason="Owns the replay scene.")],
        priority=Priority.P1,
        priority_explanation="This is a core product workflow; impact was not measured during code exploration.",
        code_references=[
            DiscoveredFeatureCodeReference(
                repository="PostHog/posthog",
                file_path="frontend/src/scenes/session-recordings/index.ts",
                start_line=1,
                end_line=1,
                contents="export {}",
                relevance_note="Entry point for session replay.",
            )
        ],
        owner_scout_playbook="Monitor replay load success and playback errors.",
    )


def _create_discovery_run(team: Team) -> FeatureDiscoveryRun:
    return FeatureDiscoveryRun.objects.for_team(team.id).create(
        team_id=team.id,
        created_by_id=1,
        repository="PostHog/posthog",
    )


def _create_discovery_task_run(team: Team) -> TaskRun:
    task = Task.objects.create(
        team=team,
        title="Discover features",
        description="Explore the repository",
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
    )
    return TaskRun.objects.create(team=team, task=task)


def _load_discovery_run(team_id: int, run_id: str) -> FeatureDiscoveryRun:
    return FeatureDiscoveryRun.objects.for_team(team_id).get(id=run_id)


@pytest.mark.asyncio
async def test_feature_discovery_stops_when_agent_says_there_are_no_more_features() -> None:
    session = MagicMock()
    session.task.id = "task-id"
    session.task_run.id = "run-id"
    session.send_followup = AsyncMock(
        side_effect=[
            _feature(),
            FeatureDiscoveryContinuation(has_more=False, reason="The remaining code is implementation detail."),
        ]
    )
    session.end = AsyncMock()

    with patch(
        "products.signals.backend.features.discovery.MultiTurnSession.start",
        new=AsyncMock(return_value=(session, _exploration())),
    ):
        result = await run_multi_turn_feature_discovery(
            repository="PostHog/posthog",
            focus="Only replay features",
            context=MagicMock(),
        )

    assert [feature.title for feature in result.features] == ["Session replay"]
    assert session.send_followup.await_count == 2
    assert "Only replay features" in session.send_followup.await_args_list[0].args[0]
    session.end.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_feature_discovery_activity_links_the_agent_task_from_async_context(ateam: Team) -> None:
    run = await database_sync_to_async(_create_discovery_run)(ateam)
    task_run = await database_sync_to_async(_create_discovery_task_run)(ateam)

    async def discover_features(
        *,
        repository: str,
        focus: str,
        context: CustomPromptSandboxContext,
        on_task_run_created: Callable[[TaskRun], Awaitable[None]] | None = None,
    ) -> FeatureDiscoveryResult:
        assert on_task_run_created is not None
        await on_task_run_created(task_run)
        return FeatureDiscoveryResult(
            exploration=_exploration(),
            features=[],
            task_id=str(task_run.task_id),
            task_run_id=str(task_run.id),
        )

    with (
        patch(
            "products.signals.backend.temporal.feature_discovery.get_or_create_signals_sandbox_env",
            return_value="sandbox-environment-id",
        ),
        patch(
            "products.signals.backend.temporal.feature_discovery.resolve_agent_runtime",
            return_value=AgentRuntime(),
        ),
        patch(
            "products.signals.backend.temporal.feature_discovery.run_multi_turn_feature_discovery",
            new=discover_features,
        ),
        patch("products.signals.backend.temporal.feature_discovery.Heartbeater"),
    ):
        discovered_count = await run_feature_discovery_activity(
            FeatureDiscoveryWorkflowInput(
                run_id=str(run.id),
                team_id=ateam.id,
                user_id=1,
                repository=run.repository,
                focus="",
            )
        )

    saved_run = await database_sync_to_async(_load_discovery_run)(ateam.id, str(run.id))
    assert discovered_count == 0
    assert saved_run.status == FeatureDiscoveryRun.Status.COMPLETED
    assert saved_run.task_id == task_run.task_id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_feature_discovery_failure_activity_marks_the_run_failed_from_async_context(ateam: Team) -> None:
    run = await database_sync_to_async(_create_discovery_run)(ateam)

    await mark_feature_discovery_failed_activity(
        FeatureDiscoveryFailedInput(
            run_id=str(run.id),
            team_id=ateam.id,
            error="Activity task failed",
        )
    )

    saved_run = await database_sync_to_async(_load_discovery_run)(ateam.id, str(run.id))
    assert saved_run.status == FeatureDiscoveryRun.Status.FAILED
    assert saved_run.error == "Feature discovery failed. Check the repository connection and try again."


class TestPersistDiscoveredFeatures(APIBaseTest):
    def test_persistence_is_idempotent_and_stages_complete_results(self) -> None:
        task = Task.objects.create(
            team=self.team,
            title="Discover features",
            description="Explore the repository",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            created_by=self.user,
        )
        run = FeatureDiscoveryRun.objects.create(
            team_id=self.team.id,
            created_by_id=self.user.id,
            repository="PostHog/posthog",
        )
        result = FeatureDiscoveryResult(
            exploration=_exploration(),
            features=[_feature()],
            task_id=str(task.id),
            task_run_id="agent-run-id",
        )

        assert persist_discovered_features(run_id=str(run.id), team_id=self.team.id, result=result) == 1
        assert persist_discovered_features(run_id=str(run.id), team_id=self.team.id, result=result) == 1

        reports = SignalReport.objects.filter(team=self.team, title="Session replay")
        assert reports.count() == 1
        lifecycle_row = SignalReportArtefact.objects.get(
            report=reports.get(),
            type=SignalReportArtefact.ArtefactType.FEATURE_LIFECYCLE,
        )
        lifecycle = FeatureLifecycle.model_validate_json(lifecycle_row.content)
        assert lifecycle.feature_stage == FeatureStage.STAGED
        assert lifecycle.discovery_run_id == str(run.id)
        run.refresh_from_db()
        assert run.status == FeatureDiscoveryRun.Status.COMPLETED
        assert run.discovered_count == 1
