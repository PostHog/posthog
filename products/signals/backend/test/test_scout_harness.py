from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.ai_observability.backend.models.skills import LLMSkill, LLMSkillFile
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.prompt import build_run_prompt
from products.signals.backend.scout_harness.runner import RunResult, arun_signals_scout
from products.signals.backend.scout_harness.skill_loader import (
    SkillNotFoundError,
    is_signals_scout_skill,
    load_skill_for_run,
)
from products.signals.backend.scout_harness.tools.runs import _build_task_url, _to_detail, _to_summary
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, run_signals_scout_activity
from products.tasks.backend.models import Task, TaskRun


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsScoutTestOrg-{random.randint(1, 99999)}",
        is_ai_data_processing_approved=True,
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsScoutTestTeam-{random.randint(1, 99999)}",
    )
    # Yield inside team_scope so dependent fixtures and test bodies have a team
    # context for the TeamScopedRootMixin-backed scout models.
    # `canonical=True` skips the sync DB resolution lookup (illegal from async).
    with team_scope(team.id, canonical=True):
        yield team
    await sync_to_async(team.delete)()


@pytest_asyncio.fixture
async def aerrors_skill(ateam):
    skill = await sync_to_async(LLMSkill.objects.create)(
        team=ateam,
        name="signals-scout-errors",
        description="Errors scout",
        body="scout",
    )
    yield skill


def _make_task_run(team: Team) -> TaskRun:
    """Minimal Task + TaskRun pair scoped to the given team."""
    task = Task.objects.create(
        team=team,
        title="scout run",
        description="scout run",
        origin_product=Task.OriginProduct.SIGNALS_SCOUT,
    )
    return TaskRun.objects.create(task=task, team=team)


class TestSkillLoader(BaseTest):
    def _create_skill(self, name: str, *, body: str = "skill body", file_paths: list[str] | None = None) -> LLMSkill:
        skill = LLMSkill.objects.create(
            team=self.team,
            name=name,
            description="A test skill",
            body=body,
            allowed_tools=["search_recent_runs", "remember"],
        )
        for path in file_paths or []:
            LLMSkillFile.objects.create(skill=skill, path=path, content=f"# {path}", content_type="text/plain")
        return skill

    def test_loads_latest_version_by_default(self) -> None:
        self._create_skill("signals-scout-errors", body="v1 body")
        loaded = load_skill_for_run(self.team, "signals-scout-errors")
        assert loaded.name == "signals-scout-errors"
        assert loaded.version == 1
        assert loaded.body == "v1 body"
        assert loaded.allowed_tools == ["search_recent_runs", "remember"]

    def test_loads_file_manifest_alongside_body(self) -> None:
        self._create_skill(
            "signals-scout-errors",
            file_paths=["references/playbook.md", "references/examples.md"],
        )
        loaded = load_skill_for_run(self.team, "signals-scout-errors")
        # Files come back sorted by path so the manifest is stable.
        assert [f.path for f in loaded.files] == [
            "references/examples.md",
            "references/playbook.md",
        ]

    def test_missing_skill_raises(self) -> None:
        with pytest.raises(SkillNotFoundError):
            load_skill_for_run(self.team, "signals-scout-does-not-exist")

    def test_signals_scout_prefix_check(self) -> None:
        match = self._create_skill("signals-scout-errors")
        non_match = self._create_skill("custom-research-helper")
        assert is_signals_scout_skill(match) is True
        assert is_signals_scout_skill(non_match) is False


class TestPromptBuilder(BaseTest):
    def test_renders_identity_bootstrap_and_universal_sections(self) -> None:
        skill = LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="Errors scout",
            body="watch for spikes",
        )
        LLMSkillFile.objects.create(skill=skill, path="refs/playbook.md", content="x", content_type="text/plain")
        loaded = load_skill_for_run(self.team, "signals-scout-errors")
        started_at = datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC)
        prompt = build_run_prompt(
            loaded,
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=self.team.id,
            started_at=started_at,
        )
        # Identity carries the skill name + version so bootstrap can reference it.
        assert "signals-scout-errors" in prompt
        assert "(v1)" in prompt
        # The agent needs to know its own run id to attribute emits and memories.
        assert "00000000-0000-0000-0000-000000000abc" in prompt
        # Bootstrap section directs the agent to read the skill via MCP, not
        # from the prompt. Skill body + file manifest are deliberately NOT
        # inlined — they're discovered at run time.
        assert "First: read your skill" in prompt
        # Skill version is pinned explicitly — the run row + tool resolution + budget
        # were snapshotted against v1, so the bootstrap fetch must lock to v1 too.
        assert 'llma-skill-get(skill_name="signals-scout-errors", version=1)' in prompt
        assert "llma-skill-file-get" in prompt
        assert "watch for spikes" not in prompt
        assert "refs/playbook.md" not in prompt
        # The base prompt teaches the agent to call the harness MCP tools by name.
        assert "signals-scout-emit-signal" in prompt
        assert "signals-scout-scratchpad-search" in prompt
        # Recency lens references the started_at anchor.
        assert "Recency lens" in prompt
        assert "2026-05-01T12:34:56+00:00" in prompt


# Orchestration tests run as plain pytest functions because the async runner uses
# `database_sync_to_async`, which requires the test team to be visible across threads.
# The fixture-based pattern (matching test_agentic_report_activity.py) gives us that.


def _make_fake_session(team: Team, summary_text: str = "ok") -> tuple[MagicMock, object]:
    """Build a (session, summary_result) pair to return from `MultiTurnSession.start`.

    The session must carry a saved `task_run` so the bridge insert succeeds
    (FK requirement) and the runner's `session.task_run.id` access works.
    """
    task_run = _make_task_run(team)
    session = MagicMock()
    session.task_run = task_run
    session.end = AsyncMock()
    result = MagicMock()
    result.summary = summary_text
    return session, result


def _fake_start_invoking_hook(session: MagicMock, result: object):
    """Stand-in for `MultiTurnSession.start` that fires the `on_task_run_created` hook.

    The real `start` awaits the hook (creating the SignalScoutRun bridge row) after the
    TaskRun exists but before the first agent turn. A plain `return_value` mock would skip
    that, so the bridge row would never be created — mirror the real contract here.
    """

    async def _start(*args, on_task_run_created=None, **kwargs):
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        return session, result

    return _start


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_successful_run_creates_bridge_row_pointing_at_task_run(ateam, aerrors_skill):
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(
        ateam, "I would investigate /checkout 500s next."
    )

    with patch(
        "products.signals.backend.scout_harness.runner.MultiTurnSession.start",
        new=_fake_start_invoking_hook(session, result),
    ):
        # `_spawn_and_run` reaches for sandbox env + user-id resolution; stub the helpers.
        with (
            patch(
                "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
                return_value="env-id",
            ),
            patch(
                "products.signals.backend.scout_harness.runner.resolve_user_id_for_team",
                return_value=42,
            ),
        ):
            run_result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert run_result.status == TaskRun.Status.COMPLETED.value
    assert run_result.skill_name == "signals-scout-errors"
    assert run_result.skill_version == 1
    assert run_result.last_message and "checkout" in run_result.last_message
    assert run_result.task_run_id == str(session.task_run.id)

    bridge = await database_sync_to_async(SignalScoutRun.objects.select_related("task_run", "scout_config").get)(
        id=run_result.run_id
    )
    assert str(bridge.task_run_id) == str(session.task_run.id)
    assert bridge.skill_name == "signals-scout-errors"
    assert bridge.skill_version == 1
    # Agent close-out is persisted on the bridge row so future runs can dedupe
    # against non-emitting runs via the runs-list ILIKE filter.
    assert bridge.summary == "I would investigate /checkout 500s next."
    config = await database_sync_to_async(SignalScoutConfig.objects.get)(team=ateam)
    assert config.enabled is False
    assert bridge.scout_config_id == config.id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_failed_run_returns_failed_outcome_and_skips_bridge_insert(ateam, aerrors_skill):
    # Failure inside MultiTurnSession.start means we never get a session.task_run
    # to bridge to — the runner's except path returns FAILED without persisting.
    with (
        patch(
            "products.signals.backend.scout_harness.runner.MultiTurnSession.start",
            new_callable=AsyncMock,
            side_effect=RuntimeError("sandbox refused to start"),
        ),
        patch(
            "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
            return_value="env-id",
        ),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_user_id_for_team",
            return_value=42,
        ),
    ):
        run_result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert run_result.status == TaskRun.Status.FAILED.value
    assert run_result.last_message is None
    # No bridge row persisted on the failure path (TaskRun was never created).
    has_runs = await database_sync_to_async(SignalScoutRun.objects.filter(team=ateam).exists)()
    assert not has_runs


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_missing_skill_does_not_create_run_row(ateam):
    with pytest.raises(SkillNotFoundError):
        await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-missing")
    has_runs = await database_sync_to_async(SignalScoutRun.objects.filter(team=ateam).exists)()
    assert not has_runs


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_skip_if_running_prevents_concurrent_runs(ateam, aerrors_skill):
    # Seed an in-progress run for the same (team, skill) so the skip-if-running guard fires.
    config = await database_sync_to_async(SignalScoutConfig.objects.create)(team=ateam)
    task_run = await database_sync_to_async(_make_task_run)(ateam)
    # Force the TaskRun into IN_PROGRESS so the running-check returns True.
    await database_sync_to_async(TaskRun.objects.filter(id=task_run.id).update)(status=TaskRun.Status.IN_PROGRESS)
    await database_sync_to_async(SignalScoutRun.objects.create)(
        task_run=task_run,
        team=ateam,
        scout_config=config,
        skill_name="signals-scout-errors",
        skill_version=1,
    )

    with patch(
        "products.signals.backend.scout_harness.runner.MultiTurnSession.start",
        new_callable=AsyncMock,
        side_effect=AssertionError("session.start should not run while a prior run is IN_PROGRESS"),
    ):
        result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert result.run_id is None
    assert result.status is None
    assert result.skip_reason is not None
    count = await database_sync_to_async(SignalScoutRun.objects.filter(team=ateam).count)()
    assert count == 1


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_returns_completed_outcome(ateam):
    async def fake_arun(**_kwargs):
        return RunResult(
            run_id="abc",
            task_run_id="def",
            status=TaskRun.Status.COMPLETED.value,
            last_message="ok",
            runtime_s=1.5,
            skill_name="signals-scout-errors",
            skill_version=2,
        )

    with patch(
        "products.signals.backend.temporal.agentic.scout_scheduler.arun_signals_scout",
        side_effect=fake_arun,
    ):
        env = ActivityEnvironment()
        output = await env.run(
            run_signals_scout_activity,
            RunSignalsScoutInput(team_id=ateam.id, skill_name="signals-scout-errors"),
        )

    assert output.run_id == "abc"
    assert output.task_run_id == "def"
    assert output.status == "completed"
    assert output.skill_version == 2
    assert output.skip_reason is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_returns_skip_outcome_when_already_running(ateam):
    async def fake_arun(**_kwargs):
        return RunResult(
            run_id=None,
            task_run_id=None,
            status=None,
            last_message=None,
            runtime_s=0.0,
            skill_name="signals-scout-errors",
            skill_version=1,
            skip_reason="prior run still in progress",
        )

    with patch(
        "products.signals.backend.temporal.agentic.scout_scheduler.arun_signals_scout",
        side_effect=fake_arun,
    ):
        env = ActivityEnvironment()
        output = await env.run(
            run_signals_scout_activity,
            RunSignalsScoutInput(team_id=ateam.id, skill_name="signals-scout-errors"),
        )

    assert output.run_id is None
    assert output.task_run_id is None
    assert output.status is None
    assert output.skip_reason is not None


# ── Tasks-UI cross-link: SignalScoutRun ─→ TaskRun ────────────────────────────
#
# Status, timestamps, and the task-id pair all live on the linked `TaskRun` now.
# The summary/detail projections join through it; `_build_task_url` produces the
# deep-link from the team + task ids.


def test_build_task_url_renders_relative_path_when_both_ids_present():
    url = _build_task_url(
        team_id=42,
        task_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        task_run_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    assert url == "/project/42/tasks/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa?runId=bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.mark.parametrize(
    "task_id,task_run_id",
    [
        (None, None),
        ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", None),
        (None, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    ],
)
def test_build_task_url_returns_none_when_either_id_missing(task_id, task_run_id):
    # Cross-link only renders when both halves are captured — a half-link can't
    # reliably open the right tab in the Tasks UI, so we'd rather emit null and
    # let callers handle the absence than render a broken URL.
    assert _build_task_url(team_id=42, task_id=task_id, task_run_id=task_run_id) is None


@pytest.mark.django_db
def test_to_summary_and_detail_surface_task_url_from_bridge():
    team = Team.objects.create(
        organization=Organization.objects.create(
            name=f"surface-org-{random.randint(1, 99999)}",
            is_ai_data_processing_approved=True,
        ),
        name=f"surface-team-{random.randint(1, 99999)}",
    )
    with team_scope(team.id, canonical=True):
        config = SignalScoutConfig.objects.create(team=team)
        task_run = _make_task_run(team)
        run = SignalScoutRun.objects.create(
            task_run=task_run,
            team=team,
            scout_config=config,
            skill_name="signals-scout-errors",
            skill_version=1,
        )

        summary = _to_summary(run, team_id=team.id)
        assert summary.task_id == str(task_run.task_id)
        assert summary.task_run_id == str(task_run.id)
        assert summary.task_url == f"/project/{team.id}/tasks/{task_run.task_id}?runId={task_run.id}"
        # Status flows from the linked TaskRun.
        assert summary.status == task_run.status

        detail = _to_detail(run, team_id=team.id)
        assert detail.task_id == summary.task_id
        assert detail.task_run_id == summary.task_run_id
        assert detail.task_url == summary.task_url
