from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.llm_analytics.backend.models.skills import LLMSkill, LLMSkillFile
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.limits import DEFAULT_LIMITS, RunLimits, resolve_limits
from products.signals.backend.scout_harness.prompt import build_run_prompt
from products.signals.backend.scout_harness.runner import (
    RunResult,
    _finalize_failed,
    _limits_for_run,
    _record_task_linkage,
    arun_signals_scout,
)
from products.signals.backend.scout_harness.skill_loader import (
    SkillNotFoundError,
    is_signals_scout_skill,
    load_skill_for_run,
)
from products.signals.backend.scout_harness.tools.runs import _build_task_url, _to_detail, _to_summary
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, run_signals_scout_activity


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


class TestLimitsResolution(BaseTest):
    def test_default_limits_when_no_overrides(self) -> None:
        assert resolve_limits(None) == DEFAULT_LIMITS
        assert resolve_limits({}) == DEFAULT_LIMITS

    def test_partial_overrides_apply_on_top_of_defaults(self) -> None:
        limits = resolve_limits({"max_runtime_s": 600})
        assert limits.max_runtime_s == 600
        assert limits.max_findings == DEFAULT_LIMITS.max_findings

    def test_unknown_keys_are_ignored(self) -> None:
        # A stale config row shouldn't crash the runner if a limit field gets renamed
        # or removed (e.g. the historical max_tool_calls / max_cost_usd we cut).
        limits = resolve_limits({"max_runtime_s": 120, "obsolete_field": "ignore_me"})
        assert limits == RunLimits(max_runtime_s=120)

    def test_limits_for_run_merges_config_and_overrides(self) -> None:
        # `_limits_for_run` is the three-level merge point: defaults < config row <
        # caller overrides. A caller-supplied key must not silently drop unrelated
        # config-row keys (the bug a previous short-circuit would introduce).
        config = SignalScoutConfig(team=self.team, limit_overrides={"max_findings": 3})
        limits = _limits_for_run(config, overrides={"max_runtime_s": 900})
        # Caller's max_runtime_s wins, but the team's max_findings is preserved.
        assert limits.max_runtime_s == 900
        assert limits.max_findings == 3

    def test_limits_for_run_overrides_win_on_conflict(self) -> None:
        # When config and overrides set the same key, the caller wins.
        config = SignalScoutConfig(team=self.team, limit_overrides={"max_runtime_s": 600})
        limits = _limits_for_run(config, overrides={"max_runtime_s": 120})
        assert limits.max_runtime_s == 120

    def test_limits_for_run_falls_back_to_config_when_no_overrides(self) -> None:
        config = SignalScoutConfig(team=self.team, limit_overrides={"max_findings": 2})
        limits = _limits_for_run(config, overrides=None)
        assert limits.max_findings == 2
        assert limits.max_runtime_s == DEFAULT_LIMITS.max_runtime_s


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
        assert "signals-scout-runs-findings-create" in prompt
        assert "signals-scout-scratchpad-list" in prompt
        # Recency lens references the started_at anchor.
        assert "Recency lens" in prompt
        assert "2026-05-01T12:34:56+00:00" in prompt


# Orchestration tests run as plain pytest functions because the async runner uses
# `database_sync_to_async`, which requires the test team to be visible across threads.
# The fixture-based pattern (matching test_agentic_report_activity.py) gives us that.


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_successful_run_persists_completed_row(ateam, aerrors_skill):
    async def fake_spawn(**_kwargs):
        return "I would investigate /checkout 500s next."

    with patch("products.signals.backend.scout_harness.runner._spawn_and_run", side_effect=fake_spawn):
        result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert result.status == SignalScoutRun.Status.COMPLETED
    assert result.skill_name == "signals-scout-errors"
    assert result.skill_version == 1
    assert result.last_message and "checkout" in result.last_message

    run_row = await database_sync_to_async(SignalScoutRun.objects.get)(id=result.run_id)
    assert run_row.status == SignalScoutRun.Status.COMPLETED
    assert run_row.completed_at is not None
    assert run_row.summary == "I would investigate /checkout 500s next."
    assert "runtime_s" in run_row.run_metrics
    config = await database_sync_to_async(SignalScoutConfig.objects.get)(team=ateam)
    assert config.enabled is False
    assert config.shadow_mode is True
    assert run_row.scout_config_id == config.id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_failed_run_persists_failure_metadata(ateam, aerrors_skill):
    async def fake_spawn(**_kwargs):
        raise RuntimeError("sandbox refused to start")

    with patch("products.signals.backend.scout_harness.runner._spawn_and_run", side_effect=fake_spawn):
        result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert result.status == SignalScoutRun.Status.FAILED
    assert result.last_message is None
    run_row = await database_sync_to_async(SignalScoutRun.objects.get)(id=result.run_id)
    assert run_row.status == SignalScoutRun.Status.FAILED
    assert run_row.completed_at is not None
    assert "sandbox refused to start" in run_row.summary
    assert run_row.metadata.get("error_type") == "RuntimeError"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_missing_skill_does_not_create_run_row(ateam):
    with pytest.raises(SkillNotFoundError):
        await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-missing")
    has_runs = await database_sync_to_async(SignalScoutRun.objects.filter(team=ateam).exists)()
    assert not has_runs


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_limit_overrides_propagate_into_run_metadata(ateam, aerrors_skill):
    async def fake_spawn(**_kwargs):
        return "ok"

    with patch("products.signals.backend.scout_harness.runner._spawn_and_run", side_effect=fake_spawn):
        result = await arun_signals_scout(
            team_id=ateam.id,
            skill_name="signals-scout-errors",
            limit_overrides={"max_runtime_s": 120},
        )

    run_row = await database_sync_to_async(SignalScoutRun.objects.get)(id=result.run_id)
    assert run_row.metadata["limits"]["max_runtime_s"] == 120


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_skip_if_running_prevents_concurrent_runs(ateam, aerrors_skill):
    config = await database_sync_to_async(SignalScoutConfig.objects.create)(team=ateam)
    await database_sync_to_async(SignalScoutRun.objects.create)(
        team=ateam,
        scout_config=config,
        skill_name="signals-scout-errors",
        skill_version=1,
        status=SignalScoutRun.Status.RUNNING,
    )

    async def fake_spawn(**_kwargs):
        raise AssertionError("spawn should not run while a prior run is RUNNING")

    with patch("products.signals.backend.scout_harness.runner._spawn_and_run", side_effect=fake_spawn):
        result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert result.run_id is None
    assert result.status is None
    assert result.skip_reason and "RUNNING" in result.skip_reason
    count = await database_sync_to_async(SignalScoutRun.objects.filter(team=ateam).count)()
    assert count == 1


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_returns_completed_outcome(ateam):
    async def fake_arun(**_kwargs):
        return RunResult(
            run_id="abc",
            status=SignalScoutRun.Status.COMPLETED,
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
    assert output.status == "completed"
    assert output.skill_version == 2
    assert output.skip_reason is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_returns_skip_outcome_when_already_running(ateam):
    async def fake_arun(**_kwargs):
        return RunResult(
            run_id=None,
            status=None,
            last_message=None,
            runtime_s=0.0,
            skill_name="signals-scout-errors",
            skill_version=1,
            skip_reason="prior run still in RUNNING status",
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
    assert output.status is None
    assert output.skip_reason and "RUNNING" in output.skip_reason


# ── Tasks-UI cross-link: SignalScoutRun.metadata.task_id / task_run_id ────────
#
# The runner spawns a sandbox via `MultiTurnSession.start()` which itself creates
# a `(Task, TaskRun)` row in the Tasks product. The IDs of that pair are needed
# both for the `task_url` deep-link surfaced on the run serializers and for the
# future LLM-analytics token/cost join. These tests lock in the persistence path
# without standing up the real sandbox.


@pytest.mark.django_db
def test_record_task_linkage_persists_both_ids_into_metadata():
    team = Team.objects.create(
        organization=Organization.objects.create(
            name=f"link-test-org-{random.randint(1, 99999)}",
            is_ai_data_processing_approved=True,
        ),
        name=f"link-test-team-{random.randint(1, 99999)}",
    )
    config = SignalScoutConfig.objects.create(team=team)
    run = SignalScoutRun.objects.create(
        team=team,
        scout_config=config,
        skill_name="signals-scout-errors",
        skill_version=1,
        status=SignalScoutRun.Status.RUNNING,
        metadata={"limits": {"max_runtime_s": 1800}, "skill_id": "skill-uuid", "allowed_tools": {"declared": False}},
    )

    _record_task_linkage(
        run_id=str(run.id),
        task_id="11111111-1111-1111-1111-111111111111",
        task_run_id="22222222-2222-2222-2222-222222222222",
    )

    run.refresh_from_db()
    assert run.metadata["task_id"] == "11111111-1111-1111-1111-111111111111"
    assert run.metadata["task_run_id"] == "22222222-2222-2222-2222-222222222222"
    # Pre-existing keys must survive the merge — the run row is created with
    # limits / skill_id / allowed_tools and clobbering them would lose the
    # snapshot the rest of the harness reads back.
    assert run.metadata["limits"] == {"max_runtime_s": 1800}
    assert run.metadata["skill_id"] == "skill-uuid"
    assert run.metadata["allowed_tools"] == {"declared": False}


@pytest.mark.django_db
def test_finalize_failed_preserves_task_linkage():
    team = Team.objects.create(
        organization=Organization.objects.create(
            name=f"fail-link-org-{random.randint(1, 99999)}",
            is_ai_data_processing_approved=True,
        ),
        name=f"fail-link-team-{random.randint(1, 99999)}",
    )
    skill = LLMSkill.objects.create(team=team, name="signals-scout-errors", description="x", body="x")
    config = SignalScoutConfig.objects.create(team=team)
    run = SignalScoutRun.objects.create(
        team=team,
        scout_config=config,
        skill_name="signals-scout-errors",
        skill_version=1,
        status=SignalScoutRun.Status.RUNNING,
        metadata={"limits": {"max_runtime_s": 1800}, "skill_id": str(skill.id), "allowed_tools": {"declared": False}},
    )
    # Linkage was recorded mid-run (between session start and the failure).
    _record_task_linkage(
        run_id=str(run.id),
        task_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        task_run_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )

    loaded = load_skill_for_run(team_id=team.id, skill_name="signals-scout-errors", version=None)
    _finalize_failed(
        run_id=str(run.id),
        exc=RuntimeError("sandbox died"),
        runtime_s=12.5,
        limits=DEFAULT_LIMITS,
        skill=loaded,
    )

    run.refresh_from_db()
    assert run.status == SignalScoutRun.Status.FAILED
    # Failure annotation lands.
    assert run.metadata["error_type"] == "RuntimeError"
    # Task linkage survives — without the merge in `_finalize_failed`, the
    # deep-link to the sandbox that actually died would be lost on the row a
    # debugger needs to land on.
    assert run.metadata["task_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert run.metadata["task_run_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


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
def test_to_summary_and_detail_surface_task_url_when_linkage_present():
    team = Team.objects.create(
        organization=Organization.objects.create(
            name=f"surface-org-{random.randint(1, 99999)}",
            is_ai_data_processing_approved=True,
        ),
        name=f"surface-team-{random.randint(1, 99999)}",
    )
    config = SignalScoutConfig.objects.create(team=team)
    run = SignalScoutRun.objects.create(
        team=team,
        scout_config=config,
        skill_name="signals-scout-errors",
        skill_version=1,
        status=SignalScoutRun.Status.COMPLETED,
        summary="ok",
        metadata={
            "limits": {"max_runtime_s": 1800},
            "skill_id": "skill-uuid",
            "allowed_tools": {"declared": False},
            "task_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "task_run_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        },
    )

    summary = _to_summary(run, team_id=team.id)
    assert summary.task_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert summary.task_run_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert (
        summary.task_url
        == f"/project/{team.id}/tasks/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa?runId=bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )

    detail = _to_detail(run, team_id=team.id)
    assert detail.task_id == summary.task_id
    assert detail.task_run_id == summary.task_run_id
    assert detail.task_url == summary.task_url
    # Detail still carries the raw metadata blob (the IDs are duplicated as
    # top-level fields for callers that want them without dict access).
    assert detail.metadata["task_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.mark.django_db
def test_to_summary_and_detail_emit_null_task_url_when_linkage_missing():
    team = Team.objects.create(
        organization=Organization.objects.create(
            name=f"missing-org-{random.randint(1, 99999)}",
            is_ai_data_processing_approved=True,
        ),
        name=f"missing-team-{random.randint(1, 99999)}",
    )
    config = SignalScoutConfig.objects.create(team=team)
    run = SignalScoutRun.objects.create(
        team=team,
        scout_config=config,
        skill_name="signals-scout-errors",
        skill_version=1,
        status=SignalScoutRun.Status.COMPLETED,
        summary="ok",
        # No task_id / task_run_id — represents either a row predating the
        # linkage capture or a run that aborted before `MultiTurnSession.start()`
        # returned (e.g. sandbox provisioning failure).
        metadata={"limits": {"max_runtime_s": 1800}, "skill_id": "skill-uuid"},
    )

    assert _to_summary(run, team_id=team.id).task_url is None
    assert _to_detail(run, team_id=team.id).task_url is None
