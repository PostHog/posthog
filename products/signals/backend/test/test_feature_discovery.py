import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

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
from products.signals.backend.models import FeatureDiscoveryRun, SignalReport, SignalReportArtefact
from products.tasks.backend.models import Task


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
