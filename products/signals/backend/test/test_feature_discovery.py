import json
from collections.abc import Awaitable, Callable

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.artefact_schemas import FeatureLifecycle, FeatureStage, Priority, QuestionArtefact
from products.signals.backend.features.discovery import (
    MAX_DISCOVERY_CODE_REFERENCE_LINES,
    DiscoveredFeatureCodeReference,
    DiscoveredFeatureDocument,
    DiscoveredFeatureOpenQuestion,
    DiscoveredFeatureOwner,
    DiscoveredFeatureSummary,
    FeatureDiscoveryActiveWorkSource,
    FeatureDiscoveryCandidate,
    FeatureDiscoveryContinuation,
    FeatureDiscoveryExploration,
    FeatureDiscoveryOutputError,
    FeatureDiscoveryResult,
    persist_discovered_features,
    run_multi_turn_feature_discovery,
)
from products.signals.backend.features.service import owner_scout_skill_name
from products.signals.backend.features.types import FeatureDiscoveryWorkflowInput
from products.signals.backend.models import FeatureDiscoveryRun, SignalReport, SignalReportArtefact
from products.signals.backend.temporal.feature_discovery import (
    FeatureDiscoveryFailedInput,
    mark_feature_discovery_failed_activity,
    run_feature_discovery_activity,
)
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.tasks.backend.models import Task, TaskRun


def _exploration(candidate_titles: list[str] | None = None) -> FeatureDiscoveryExploration:
    titles = candidate_titles or ["Session replay"]
    return FeatureDiscoveryExploration(
        codebase_overview="The app has a replay product.",
        repositories_examined=["PostHog/posthog"],
        has_candidates=True,
        discovery_strategy="Treat the replay journey as one feature.",
        active_work_sources=[
            FeatureDiscoveryActiveWorkSource(
                source="GitHub pull requests",
                status="checked",
                details="No relevant open pull requests.",
            )
        ],
        feature_candidates=[
            FeatureDiscoveryCandidate(
                title=title,
                user_goal=f"Use {title.lower()}.",
                boundary="This journey has its own entry point and success measure.",
                entry_points=["/replay"],
            )
            for title in titles
        ],
    )


def _feature(title: str = "Session replay") -> DiscoveredFeatureDocument:
    return DiscoveredFeatureDocument(
        title=title,
        summary=DiscoveredFeatureSummary(
            overview="Users can record and replay browser sessions.",
            current_status="Available.",
            user_experience="Open a recording and play it back.",
            implementation="The replay scene loads captured snapshots.",
            in_flight_work="GitHub pull requests were checked; none affect this feature.",
            measurement_and_health="Monitor playback errors.",
            next_steps="Validate playback reliability.",
        ),
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
        open_questions=[
            DiscoveredFeatureOpenQuestion(
                question="Should recordings be retained when a user revokes consent?",
                options=["Delete recordings immediately", "Retain recordings until their normal expiry"],
            )
        ],
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


def _set_discovery_failure_details(team_id: int, run_id: str, failure_details: str) -> None:
    FeatureDiscoveryRun.objects.for_team(team_id).filter(id=run_id).update(
        status=FeatureDiscoveryRun.Status.FAILED,
        error="Feature discovery failed. Check the repository connection and try again.",
        failure_details=failure_details,
    )


def test_feature_summary_renders_the_bounded_living_overview() -> None:
    rendered = _feature().summary.render_markdown()

    assert len(rendered) <= 2500
    assert rendered.startswith("## Overview\n\nUsers can record and replay browser sessions.")
    assert "## In-flight work\n\nGitHub pull requests were checked" in rendered
    assert rendered.endswith("## Next steps\n\nValidate playback reliability.")


def test_feature_summary_rejects_embedded_section_headings() -> None:
    document = _feature().model_dump()
    document["summary"]["overview"] = "## Outcome\n\nUsers understand behavior."

    with pytest.raises(ValidationError, match="must not include section headings"):
        DiscoveredFeatureDocument.model_validate(document)


def test_feature_document_rejects_oversized_code_reference_instead_of_truncating_it() -> None:
    document = _feature().model_dump()
    source_lines = [f"line {index}" for index in range(MAX_DISCOVERY_CODE_REFERENCE_LINES + 5)]
    document["code_references"][0].update(
        start_line=40,
        end_line=40 + len(source_lines) - 1,
        contents="\n".join(source_lines),
    )

    with pytest.raises(ValidationError, match="must not exceed 10 lines"):
        DiscoveredFeatureDocument.model_validate(document)


@pytest.mark.asyncio
async def test_feature_discovery_follows_candidate_ledger_until_agent_stops() -> None:
    session = MagicMock()
    session.task.id = "task-id"
    session.task_run.id = "run-id"
    session.send_followup_raw = AsyncMock(
        side_effect=[
            _feature().model_dump_json(),
            FeatureDiscoveryContinuation(
                has_more=True,
                next_candidate_title="Replay playlists",
                reason="The replay playlist journey still needs a report.",
            ).model_dump_json(),
            _feature("Replay playlists").model_dump_json(),
            FeatureDiscoveryContinuation(
                has_more=False,
                reason="The remaining code is implementation detail.",
            ).model_dump_json(),
        ]
    )
    session.end = AsyncMock()
    exploration = _exploration(["Session replay", "Replay playlists"])
    start_session = AsyncMock(return_value=(session, exploration.model_dump_json()))

    with patch(
        "products.signals.backend.features.discovery.MultiTurnSession.start_raw",
        new=start_session,
    ):
        result = await run_multi_turn_feature_discovery(
            repository="PostHog/posthog",
            focus="Only replay features",
            context=MagicMock(),
        )

    assert [feature.title for feature in result.features] == ["Session replay", "Replay playlists"]
    assert session.send_followup_raw.await_count == 4
    assert start_session.await_args is not None
    exploration_prompt = start_session.await_args.kwargs["prompt"]
    assert "open pull requests or merge requests" in exploration_prompt
    assert "active remote branches" in exploration_prompt
    assert "relevant open issues" in exploration_prompt
    assert "Do not infer that no work is in flight from the default branch alone" in exploration_prompt
    assert "Build `feature_candidates` as an ordered ledger" in exploration_prompt
    assert "Administrative management and public consumption are separate candidates" in exploration_prompt
    assert "Do not repeat this ledger in `codebase_overview`" in exploration_prompt
    assert "`discovery_strategy` at most 600 characters" in exploration_prompt
    assert "candidate `title` at most 80, `user_goal` at most 180, and `boundary` at most 220" in exploration_prompt
    feature_prompt = session.send_followup_raw.await_args_list[0].args[0]
    assert "Only replay features" in feature_prompt
    assert "candidate `Session replay`" in feature_prompt
    assert "structured set of bounded sections" in feature_prompt
    assert "open_questions" in feature_prompt
    assert "Do not guess about intended behavior" in feature_prompt
    assert "two to five concise, mutually exclusive `options`" in feature_prompt
    assert "Do not add an Other option" in feature_prompt
    assert "include only active work connected to this candidate" in feature_prompt
    assert "Do not merge distinct workflows merely because they share files" in feature_prompt
    assert "target 4 to 8 contiguous lines and never exceed 10" in feature_prompt
    assert "end_line = start_line + line_count - 1" in feature_prompt
    assert "Return `owner_scout_playbook` as one Markdown string, never an array" in feature_prompt
    assert (
        "three or four one-sentence bullets, at most 150 characters per bullet and 800 characters total"
        in feature_prompt
    )
    assert "Use only keys declared in the schema; do not add placeholders or helper fields" in feature_prompt
    prompt_schema = json.loads(feature_prompt.split("<jsonschema>\n", 1)[1].split("\n</jsonschema>", 1)[0])
    summary_schema = prompt_schema["$defs"]["DiscoveredFeatureSummary"]["properties"]
    for field, field_schema in summary_schema.items():
        assert f"`summary.{field}`: at most {field_schema['maxLength']} characters" in feature_prompt
    assert "title" in prompt_schema["properties"]
    assert "title" not in prompt_schema
    continuation_prompt = session.send_followup_raw.await_args_list[1].args[0]
    assert "Exploration candidate ledger" in continuation_prompt
    assert "next_candidate_title" in continuation_prompt
    assert "user journey, entry point, and relevant active-work item" in continuation_prompt
    assert "even if another feature mentions it or shares implementation files" in continuation_prompt
    second_feature_prompt = session.send_followup_raw.await_args_list[2].args[0]
    assert "candidate `Replay playlists`" in second_feature_prompt
    session.end.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_feature_discovery_corrects_an_invalid_feature_document() -> None:
    invalid_document = _feature().model_dump()
    invalid_document["open_questions"] = [
        {
            "question": "Should recordings be retained when a user revokes consent?",
            "options": ["Delete recordings immediately"],
        }
    ]
    with pytest.raises(ValidationError):
        DiscoveredFeatureDocument.model_validate(invalid_document)

    session = MagicMock()
    session.task.id = "task-id"
    session.task_run.id = "run-id"
    session.send_followup_raw = AsyncMock(
        side_effect=[
            json.dumps(invalid_document),
            json.dumps(invalid_document),
            _feature().model_dump_json(),
            FeatureDiscoveryContinuation(has_more=False, reason="No other feature remains.").model_dump_json(),
        ]
    )
    session.end = AsyncMock()

    with patch(
        "products.signals.backend.features.discovery.MultiTurnSession.start_raw",
        new=AsyncMock(return_value=(session, _exploration().model_dump_json())),
    ):
        result = await run_multi_turn_feature_discovery(
            repository="PostHog/posthog",
            focus="Only replay features",
            context=MagicMock(),
        )

    assert [feature.title for feature in result.features] == ["Session replay"]
    assert session.send_followup_raw.await_count == 4
    first_correction_prompt = session.send_followup_raw.await_args_list[1].args[0]
    assert "at least 2 items" in first_correction_prompt
    assert "return one Markdown string, never an array" in first_correction_prompt
    assert "remove the undeclared key instead of renaming it" in first_correction_prompt
    assert "at least 2 items" in session.send_followup_raw.await_args_list[2].args[0]
    session.end.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_feature_discovery_corrects_an_invalid_exploration_turn() -> None:
    invalid_exploration = _exploration().model_dump()
    invalid_exploration["feature_candidates"] = []

    session = MagicMock()
    session.task.id = "task-id"
    session.task_run.id = "run-id"
    session.send_followup_raw = AsyncMock(
        side_effect=[
            _exploration().model_dump_json(),
            _feature().model_dump_json(),
            FeatureDiscoveryContinuation(has_more=False, reason="No other feature remains.").model_dump_json(),
        ]
    )
    session.end = AsyncMock()

    with patch(
        "products.signals.backend.features.discovery.MultiTurnSession.start_raw",
        new=AsyncMock(return_value=(session, json.dumps(invalid_exploration))),
    ):
        result = await run_multi_turn_feature_discovery(
            repository="PostHog/posthog",
            focus="Only replay features",
            context=MagicMock(),
        )

    assert [feature.title for feature in result.features] == ["Session replay"]
    assert session.send_followup_raw.await_count == 3
    assert (
        "has_candidates must match whether feature_candidates is empty"
        in session.send_followup_raw.await_args_list[0].args[0]
    )
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
    assert saved_run.failure_details == "Activity task failed"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_feature_discovery_cleanup_preserves_the_specific_activity_failure(ateam: Team) -> None:
    run = await database_sync_to_async(_create_discovery_run)(ateam)
    await database_sync_to_async(_set_discovery_failure_details, thread_sensitive=False)(
        ateam.id,
        str(run.id),
        "Code references must not exceed 20 lines",
    )

    await mark_feature_discovery_failed_activity(
        FeatureDiscoveryFailedInput(
            run_id=str(run.id),
            team_id=ateam.id,
            error="Activity task failed",
        )
    )

    saved_run = await database_sync_to_async(_load_discovery_run)(ateam.id, str(run.id))
    assert saved_run.failure_details == "Code references must not exceed 20 lines"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_feature_discovery_activity_does_not_retry_invalid_agent_output(ateam: Team) -> None:
    run = await database_sync_to_async(_create_discovery_run)(ateam)
    output_error = FeatureDiscoveryOutputError("Agent returned invalid feature document")

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
            new=AsyncMock(side_effect=output_error),
        ),
        patch("products.signals.backend.temporal.feature_discovery.Heartbeater"),
        pytest.raises(ApplicationError, match="Agent returned invalid feature document") as error,
    ):
        await run_feature_discovery_activity(
            FeatureDiscoveryWorkflowInput(
                run_id=str(run.id),
                team_id=ateam.id,
                user_id=1,
                repository=run.repository,
                focus="",
            )
        )

    saved_run = await database_sync_to_async(_load_discovery_run)(ateam.id, str(run.id))
    assert error.value.non_retryable is True
    assert saved_run.status == FeatureDiscoveryRun.Status.FAILED
    assert saved_run.error == "Feature discovery failed. Check the repository connection and try again."
    assert saved_run.failure_details == "Agent returned invalid feature document"


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
        report = reports.get()
        assert report.summary == _feature().summary.render_markdown()
        assert len(report.summary or "") <= 2500
        lifecycle_row = SignalReportArtefact.objects.get(
            report=report,
            type=SignalReportArtefact.ArtefactType.FEATURE_LIFECYCLE,
        )
        lifecycle = FeatureLifecycle.model_validate_json(lifecycle_row.content)
        assert lifecycle.feature_stage == FeatureStage.STAGED
        assert lifecycle.discovery_run_id == str(run.id)
        groundskeeping = SignalReportArtefact.objects.get(
            report=report,
            type=SignalReportArtefact.ArtefactType.NOTE,
            content__contains="About this feature report",
        )
        assert owner_scout_skill_name(str(report.id)) in groundskeeping.content
        question_row = SignalReportArtefact.objects.get(
            report=report,
            type=SignalReportArtefact.ArtefactType.QUESTION,
        )
        question = QuestionArtefact.model_validate_json(question_row.content)
        assert question.question == "Should recordings be retained when a user revokes consent?"
        assert question.options == ["Delete recordings immediately", "Retain recordings until their normal expiry"]
        assert question.answered is False
        assert question_row.task_id == task.id
        run.refresh_from_db()
        assert run.status == FeatureDiscoveryRun.Status.COMPLETED
        assert run.discovered_count == 1
