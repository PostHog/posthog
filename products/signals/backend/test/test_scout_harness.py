from __future__ import annotations

import random
import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.apps import apps
from django.db import OperationalError

import pytest_asyncio
from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY, _compute_row_hash
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S
from products.signals.backend.scout_harness.model_selection import ScoutModel
from products.signals.backend.scout_harness.prompt import build_run_prompt
from products.signals.backend.scout_harness.runner import RunResult, arun_signals_scout
from products.signals.backend.scout_harness.skill_loader import (
    SkillNotFoundError,
    is_signals_scout_skill,
    load_skill_for_run,
)
from products.signals.backend.scout_harness.tools.runs import _build_task_url, _to_detail, _to_summary
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, run_signals_scout_activity
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


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
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
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
        assert 'skill-get(skill_name="signals-scout-errors", version=1)' in prompt
        assert "skill-file-get" in prompt
        assert "watch for spikes" not in prompt
        assert "refs/playbook.md" not in prompt
        # Second bootstrap step orients the agent on the project via the
        # project-profile harness tool, eliminating the discovery-burn the
        # scout would otherwise pay on a fresh team.
        assert "Then: orient on this project" in prompt
        assert "signals-scout-project-profile-get" in prompt
        # The base prompt teaches the agent to call the harness MCP tools by name.
        assert "signals-scout-emit-signal" in prompt
        assert "signals-scout-scratchpad-search" in prompt
        # Recency lens references the started_at anchor.
        assert "Recency lens" in prompt
        assert "2026-05-01T12:34:56+00:00" in prompt
        # The base prompt nudges the scout to report operational friction via the
        # agent-feedback tool so the scout system improves over time.
        assert "Report operational friction" in prompt
        assert "agent-feedback" in prompt
        # Tag guidance teaches the scratchpad-taxonomy convention — the scout owns and
        # evolves its vocabulary in the scout loop; the harness only carries the nudge.
        assert "Tagging your findings" in prompt
        assert "tags:<domain>:taxonomy" in prompt
        # The base prompt teaches scouts to format the description for the inbox
        # surface (markdown, front-loaded into the ~300-char collapsed preview),
        # while leaving a skill body free to impose its own structure.
        assert "Writing the description (how it renders in the inbox)" in prompt
        # The writing-style section is wired into the tail, carrying the
        # session-replay-vs-recording terminology rule scouts must follow.
        assert "session recordings" in prompt
        # A signal scout never sees the report-channel guidance — it fires weak
        # signals, it does not author reports.
        assert "signals-scout-emit-report" not in prompt
        assert "Suggested reviewers route the report" not in prompt
        assert "scratchpad entry is a pointer" not in prompt

    def test_report_channel_renders_report_persona_and_guidance(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors-reports",
            description="Errors scout that authors reports",
            body="watch for spikes",
            allowed_tools=["emit_report", "edit_report"],
        )
        loaded = load_skill_for_run(self.team, "signals-scout-errors-reports")
        prompt = build_run_prompt(
            loaded,
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=self.team.id,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        )
        # A report scout authors via the report channel, so the persona and the
        # run-identity emit reference point at emit-report, not emit-signal.
        assert "signals-scout-emit-report" in prompt
        assert "signals-scout-edit-report" in prompt
        # The two highest-leverage nudges the report channel adds: search the inbox
        # and edit before authoring a duplicate, and set suggested reviewers (what
        # actually routes a report).
        assert "Authoring vs. editing: search the inbox first" in prompt
        assert "inbox-reports-list" in prompt
        assert "Suggested reviewers route the report" in prompt
        assert "suggested_reviewers" in prompt
        # Reviewer routing accepts a `user_uuid` (server-resolved to a GitHub login), and when the
        # owner isn't already in the evidence the prompt points the scout at the in-run
        # `signals-scout-members-list` tool — so it must name both rather than letting it guess a
        # handle or reach for the org-scoped resolver that's stripped from a scout run.
        assert "user_uuid" in prompt
        assert "signals-scout-members-list" in prompt
        # The report channel teaches that the `report:` scratchpad entry is a pointer
        # into the inbox, not a copy of the report — the inbox stays the source of
        # truth, so the scout retrieves the live report before editing. Dropping this
        # discipline re-opens the duplicate / stale-edit failure mode.
        assert "scratchpad entry is a pointer" in prompt
        assert "source of truth" in prompt
        # The report-channel prompt must carry both dedup nuances: search `ordering=-updated_at`
        # (else the most recent duplicate sorts below older rows) and don't filter by product name
        # (a scout's own report-channel signals persist under `source_product=signals_scout`).
        # Dropping either silently re-opens the duplicate-report failure mode for every report scout.
        assert "ordering=-updated_at" in prompt
        assert "source_product=signals_scout" in prompt
        # Signal-only sections (weak-finding schema, tagging taxonomy) are dropped
        # for a report scout — it doesn't fire `emit_signal`.
        assert "signals-scout-emit-signal" not in prompt
        assert "Tagging your findings" not in prompt
        # Shared scaffolding is still present on both personas.
        assert "First: read your skill" in prompt
        assert "Report operational friction" in prompt
        assert "Output format" in prompt

    @parameterized.expand(
        [
            # (label, skill_name, metadata, allowed_tools, expect_section). A pristine canonical
            # scout (harness-seeded row on an on-disk fleet name) must never see the
            # self-improvement section — applying an `improve:` suggestion would mark its row
            # diverged and cut it off from upstream sync. Custom scouts get it on both channels,
            # and so does a *diverged* seeded row (content hash no longer matching the stamped
            # `canonical_hash`): the team already owns that body, sync leaves it alone.
            ("custom_signal_scout", "signals-scout-errors", {}, [], True),
            ("custom_report_scout", "signals-scout-errors", {}, ["emit_report", "edit_report"], True),
            # No stored canonical_hash (pre-hash-tracking legacy row): unprovable, stays canonical.
            ("canonical_scout_no_hash", "signals-scout-general", {"seeded_by": HARNESS_SEEDED_BY}, [], False),
            (
                "diverged_canonical_scout",
                "signals-scout-general",
                {"seeded_by": HARNESS_SEEDED_BY, "canonical_hash": "0" * 64},
                [],
                True,
            ),
        ]
    )
    def test_self_improvement_section_gated_on_custom_origin(
        self,
        _name: str,
        skill_name: str,
        metadata: dict,
        allowed_tools: list[str],
        expect_section: bool,
    ) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name=skill_name,
            description="d",
            body="b",
            allowed_tools=allowed_tools,
            metadata=metadata,
        )
        prompt = build_run_prompt(
            load_skill_for_run(self.team, skill_name),
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=self.team.id,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        )
        assert ("Suggest improvements to your own skill" in prompt) is expect_section
        # The `improve:` key contract is what the meta-skills document — it must ride with the
        # section, and it must be skill-namespaced (scratchpad keys are unique per (team, key),
        # so a domain-only key would let two scouts clobber each other's suggestions).
        assert ("improve:<your-skill-name>:<topic>" in prompt) is expect_section
        # The upstream friction channel is origin-independent: canonical defects still route there.
        assert "agent-feedback" in prompt

    def test_pristine_seeded_row_stays_canonical(self) -> None:
        # A seeded row whose content still matches its stamped canonical_hash is the one case
        # that must NOT get the section — a regression that ignores the hash comparison (always
        # custom when a hash is present) would nudge every unedited canonical scout to diverge.
        skill = LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-general",
            description="d",
            body="b",
            metadata={"seeded_by": HARNESS_SEEDED_BY},
        )
        skill.metadata["canonical_hash"] = _compute_row_hash(skill, [])
        skill.save()
        prompt = build_run_prompt(
            load_skill_for_run(self.team, "signals-scout-general"),
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=self.team.id,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        )
        assert "Suggest improvements to your own skill" not in prompt

    def _report_prompt_for(self, allowed_tools: list[str]) -> str:
        name = "signals-scout-" + "-".join(allowed_tools)
        LLMSkill.objects.create(team=self.team, name=name, description="d", body="b", allowed_tools=allowed_tools)
        return build_run_prompt(
            load_skill_for_run(self.team, name),
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=self.team.id,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        )

    def test_emit_only_report_scout_never_references_edit_tool(self) -> None:
        # A scout that opted into emit_report but NOT edit_report must never be steered toward
        # `signals-scout-edit-report` — the endpoint fails closed on the exact tool, so naming it
        # would route the run into a PermissionDenied. This is the regression the per-tool gating guards.
        prompt = self._report_prompt_for(["emit_report"])
        assert "signals-scout-emit-report" in prompt
        assert "signals-scout-edit-report" not in prompt
        assert "Authoring reports: search the inbox first" in prompt
        assert "Suggested reviewers route the report" in prompt
        # The dedup nuances reach the emit-only variant too — not just the both-tools prompt.
        assert "ordering=-updated_at" in prompt
        # An emit-only scout can't edit, so a relapse of a CLOSED report must become a fresh report
        # rather than a skip — otherwise relapses on resolved/suppressed/failed reports are dropped.
        assert "relapse of a closed report" in prompt

    def test_edit_only_report_scout_never_references_emit_tool(self) -> None:
        # The mirror case: an edit_report-only scout must never be told to author via
        # `signals-scout-emit-report`, and the standalone author-time sections (the suggested-reviewers
        # deep-dive, writing a report) are dropped since it can't author. It still learns it can SET
        # reviewers via edit (the routing rescue), folded into the editing guidance — not the H1 section.
        prompt = self._report_prompt_for(["edit_report"])
        assert "signals-scout-edit-report" in prompt
        assert "signals-scout-emit-report" not in prompt
        assert "Editing existing reports" in prompt
        assert "Suggested reviewers route the report" not in prompt
        assert "Writing the report" not in prompt
        assert "suggested_reviewers" in prompt
        # An edit-only scout can still rescue an unrouted report's reviewers, so the editing guidance
        # carries the in-run member lookup too — even though the standalone author-time deep-dive drops.
        assert "signals-scout-members-list" in prompt
        # An edit-only scout searches the inbox to find the report to update, so it needs the same
        # dedup nuance — else the default ordering hides the most recently updated match.
        assert "ordering=-updated_at" in prompt


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
    TaskRun = apps.get_model("tasks", "TaskRun")
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
                "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
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
    config = await database_sync_to_async(SignalScoutConfig.objects.get)(team=ateam, skill_name="signals-scout-errors")
    # Auto-created configs default to enabled (the dogfood flag is the team-level gate).
    assert config.enabled is True
    assert bridge.scout_config_id == config.id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_tags_session_with_scout_ai_stage(ateam, aerrors_skill):
    # Scouts pass ai_stage='scout' to the sandbox session so every $ai_generation carries it,
    # letting scout spend be split out of the ai_product='signals' bucket (scouts have no report id).
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)
    captured: dict = {}

    async def _capture_start(*args, on_task_run_created=None, **kwargs):
        captured.update(kwargs)
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        return session, result

    with (
        patch("products.signals.backend.scout_harness.runner.MultiTurnSession.start", new=_capture_start),
        patch(
            "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
            return_value="env-id",
        ),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=42,
        ),
    ):
        await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert captured["ai_stage"] == "scout"


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "resolved, expected_model, expected_runtime_adapter",
    [
        (ScoutModel(model="@cf/zai-org/glm-5.2", runtime_adapter="codex"), "@cf/zai-org/glm-5.2", "codex"),
        (ScoutModel(model=None, runtime_adapter=None), None, None),
    ],
)
async def test_run_pins_sandbox_to_resolved_scout_model(
    ateam, aerrors_skill, resolved, expected_model, expected_runtime_adapter
):
    # The `scouts-model-selection` gate resolves an agent-model override (glm-5.2 on the codex
    # runtime) or the agent-server default (None/None); the runner must hand both straight to the
    # sandbox via the context — the runtime travels with the model so the agent server can route it.
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)
    captured: dict = {}

    async def _capture_start(*args, on_task_run_created=None, **kwargs):
        captured.update(kwargs)
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        return session, result

    with (
        patch("products.signals.backend.scout_harness.runner.MultiTurnSession.start", new=_capture_start),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_scout_model",
            return_value=resolved,
        ),
        # No `signals-pipeline-models` runtime pin: the scouts-glm model gate drives the run.
        patch(
            "products.signals.backend.scout_harness.runner.resolve_agent_runtime",
            return_value=AgentRuntime(),
        ),
        patch(
            "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
            return_value="env-id",
        ),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=42,
        ),
    ):
        await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert captured["context"].model == expected_model
    assert captured["context"].runtime_adapter == expected_runtime_adapter


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_codex_runtime_pin_overrides_scout_model(ateam, aerrors_skill):
    # A runtime pin replaces the scouts-glm gated model wholesale (runtime/model move as a set).
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)
    captured: dict = {}

    async def _capture_start(*args, on_task_run_created=None, **kwargs):
        captured.update(kwargs)
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        return session, result

    with (
        patch("products.signals.backend.scout_harness.runner.MultiTurnSession.start", new=_capture_start),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_scout_model",
            return_value="@cf/zai-org/glm-5.2",
        ),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_agent_runtime",
            return_value=AgentRuntime(runtime_adapter="codex", model="gpt-5.5", reasoning_effort="high"),
        ),
        patch(
            "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
            return_value="env-id",
        ),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=42,
        ),
    ):
        await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    ctx = captured["context"]
    assert ctx.runtime_adapter == "codex"
    assert ctx.model == "gpt-5.5"
    assert ctx.reasoning_effort == "high"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_failed_run_returns_failed_outcome_and_skips_bridge_insert(ateam, aerrors_skill):
    TaskRun = apps.get_model("tasks", "TaskRun")
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
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
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
async def test_successful_run_captures_run_finished_event(ateam, aerrors_skill):
    TaskRun = apps.get_model("tasks", "TaskRun")
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)

    with (
        patch(
            "products.signals.backend.scout_harness.runner.MultiTurnSession.start",
            new=_fake_start_invoking_hook(session, result),
        ),
        patch(
            "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
            return_value="env-id",
        ),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=42,
        ),
        patch("products.signals.backend.scout_harness.runner.posthoganalytics.capture") as capture,
    ):
        run_result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    # A successful run emits the started marker (in the bridge-row hook) then the finished event.
    events = [c.kwargs["event"] for c in capture.call_args_list]
    assert events == ["signals_scout_run_started", "signals_scout_run_finished"]
    finished = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_run_finished")
    assert finished.kwargs["distinct_id"] == str(ateam.uuid)
    props = finished.kwargs["properties"]
    assert props["skill_name"] == "signals-scout-errors"
    assert props["skill_version"] == 1
    assert props["status"] == TaskRun.Status.COMPLETED.value
    assert props["emitted_count"] == 0
    assert props["run_id"] == run_result.run_id
    # task_run_id is the join key into LLM analytics for the richer per-run metrics.
    assert props["task_run_id"] == str(session.task_run.id)
    assert isinstance(props["runtime_seconds"], float)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_successful_run_captures_run_started_event(ateam, aerrors_skill):
    # The started marker fires once the TaskRun + bridge row exist (the on_task_run_created
    # hook), so it counts only runs that actually start. Pairs with the finished event for
    # event-derived throughput / stall detection with no warehouse lag.
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)

    with (
        patch(
            "products.signals.backend.scout_harness.runner.MultiTurnSession.start",
            new=_fake_start_invoking_hook(session, result),
        ),
        patch(
            "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
            return_value="env-id",
        ),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=42,
        ),
        patch("products.signals.backend.scout_harness.runner.posthoganalytics.capture") as capture,
    ):
        run_result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    started = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_run_started")
    assert started.kwargs["distinct_id"] == str(ateam.uuid)
    props = started.kwargs["properties"]
    assert props["skill_name"] == "signals-scout-errors"
    assert props["skill_version"] == 1
    assert props["run_id"] == run_result.run_id
    assert props["task_run_id"] == str(session.task_run.id)
    config = await database_sync_to_async(SignalScoutConfig.objects.get)(team=ateam, skill_name="signals-scout-errors")
    assert props["scout_config_id"] == str(config.id)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_failed_run_captures_run_finished_event(ateam, aerrors_skill):
    TaskRun = apps.get_model("tasks", "TaskRun")
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
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=42,
        ),
        patch("products.signals.backend.scout_harness.runner.posthoganalytics.capture") as capture,
    ):
        await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    capture.assert_called_once()
    props = capture.call_args.kwargs["properties"]
    assert capture.call_args.kwargs["event"] == "signals_scout_run_finished"
    assert props["status"] == TaskRun.Status.FAILED.value
    # No bridge row persisted (TaskRun never created), so no emit tally or join key.
    assert props["emitted_count"] == 0
    assert props["task_run_id"] is None
    # Failure reason rides on the event so the failure rate is breakable down by cause
    # without digging into worker logs — the bulk of scout failures fail here, before the
    # process-task workflow's own task_run_failed event fires.
    assert props["error_type"] == "RuntimeError"
    assert props["error_message"] == "sandbox refused to start"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_skipped_when_no_acting_user(ateam, aerrors_skill):
    # When no user can be resolved to act as (no active org member — `resolve_acting_user_id_for_team`
    # returns None), the run must skip rather than crash deep in _spawn_and_run and book a bogus
    # `failed`. That instant-crash-as-failure is what let a handful of teams dominate the fleet
    # failure rate. A skip leaves no row, no lifecycle event, just a skip_reason. (A team merely
    # lacking GitHub is NOT this case — it resolves an org member and runs; see the resolver tests.)
    with (
        patch(
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=None,
        ),
        patch("products.signals.backend.scout_harness.runner.posthoganalytics.capture") as capture,
    ):
        run_result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert run_result.status is None
    assert run_result.run_id is None
    assert run_result.skip_reason == "no active user to act as for team"
    # Skipped runs are not runs: no started / finished / failed event is emitted.
    assert capture.call_count == 0
    has_runs = await database_sync_to_async(SignalScoutRun.objects.filter(team=ateam).exists)()
    assert not has_runs


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_cancelled_run_captures_run_finished_event(ateam, aerrors_skill):
    TaskRun = apps.get_model("tasks", "TaskRun")

    async def fake_spawn(**_kwargs):
        raise asyncio.CancelledError("worker is shutting down")

    with (
        patch("products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.runner._spawn_and_run", side_effect=fake_spawn),
        patch("products.signals.backend.scout_harness.runner.posthoganalytics.capture") as capture,
    ):
        with pytest.raises(asyncio.CancelledError):
            await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    # The cancelled path still emits before re-raising, so the metric isn't lost on shutdown.
    capture.assert_called_once()
    props = capture.call_args.kwargs["properties"]
    assert props["status"] == TaskRun.Status.CANCELLED.value
    # Cancellation skips the DB read, so emit volume is left unknown rather than guessed.
    assert props["emitted_count"] is None


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
    TaskRun = apps.get_model("tasks", "TaskRun")
    # Seed an in-progress run for the same (team, skill) so the skip-if-running guard fires.
    config = await database_sync_to_async(SignalScoutConfig.objects.create)(
        team=ateam, skill_name="signals-scout-errors"
    )
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
async def test_withheld_scout_is_not_run(ateam, aerrors_skill):
    # A direct `run_signals_scout` of a held-back scout is refused up front — no sandbox session,
    # no run row — so the manual path can't run a scout the `signals-scout` flag withholds.
    payload_path = "products.signals.backend.scout_harness.team_limits.posthoganalytics.get_feature_flag_payload"
    with (
        patch(payload_path, return_value={"default_team_config": {"withheld_skills": ["signals-scout-errors"]}}),
        patch(
            "products.signals.backend.scout_harness.runner.MultiTurnSession.start",
            new_callable=AsyncMock,
            side_effect=AssertionError("session.start should not run for a withheld scout"),
        ),
    ):
        result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert result.run_id is None
    assert result.skip_reason == "scout is withheld from this team"
    has_runs = await database_sync_to_async(SignalScoutRun.objects.filter(team=ateam).exists)()
    assert not has_runs


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_skip_if_running_lock_keys_on_team_and_skill_not_just_team(ateam, aerrors_skill):
    """Different skills for the same team must be allowed to run concurrently — the
    coordinator can dispatch several due scouts for one team in a single tick. The
    skip-if-running guard locks on `(team, skill_name)` rather than `(team, config_id)`
    so this works."""
    TaskRun = apps.get_model("tasks", "TaskRun")
    config = await database_sync_to_async(SignalScoutConfig.objects.create)(team=ateam)
    # A different skill for the same team is in flight — should NOT block. Run status lives
    # on the linked TaskRun now, so stand up a real IN_PROGRESS TaskRun + bridge row.
    other_task_run = await database_sync_to_async(_make_task_run)(ateam)
    await database_sync_to_async(TaskRun.objects.filter(id=other_task_run.id).update)(status=TaskRun.Status.IN_PROGRESS)
    await database_sync_to_async(SignalScoutRun.objects.create)(
        task_run=other_task_run,
        team=ateam,
        scout_config=config,
        skill_name="signals-scout-other",
        skill_version=1,
    )

    spawn_calls: list[dict] = []

    async def fake_spawn(**kwargs):
        spawn_calls.append(kwargs)
        return "ok"

    with (
        patch("products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.runner._spawn_and_run", side_effect=fake_spawn),
    ):
        result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    # Spawn went through — the OTHER skill's RUNNING row didn't gate ours.
    assert len(spawn_calls) == 1
    assert result.run_id is not None
    assert result.skip_reason is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_stale_in_progress_run_is_reaped_and_unblocks_dispatch(ateam, aerrors_skill):
    TaskRun = apps.get_model("tasks", "TaskRun")
    # An IN_PROGRESS run orphaned by a crashed worker must not block the lane forever. The
    # stale-run self-heal fails any run older than STALE_RUN_CUTOFF_S before the skip-if-running
    # guard, so a fresh dispatch proceeds and the orphan is marked FAILED.
    config = await database_sync_to_async(SignalScoutConfig.objects.create)(
        team=ateam, skill_name="signals-scout-errors"
    )
    task_run = await database_sync_to_async(_make_task_run)(ateam)
    # An IN_PROGRESS run whose start is older than the cutoff = an orphan from a crashed worker.
    await database_sync_to_async(TaskRun.objects.filter(id=task_run.id).update)(
        status=TaskRun.Status.IN_PROGRESS,
        created_at=datetime.now(UTC) - timedelta(seconds=STALE_RUN_CUTOFF_S + 60),
    )
    await database_sync_to_async(SignalScoutRun.objects.create)(
        task_run=task_run,
        team=ateam,
        scout_config=config,
        skill_name="signals-scout-errors",
        skill_version=1,
    )

    spawn_calls: list[dict] = []

    async def fake_spawn(**kwargs):
        spawn_calls.append(kwargs)
        return "ok", str(task_run.id)

    with (
        patch("products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.runner._spawn_and_run", side_effect=fake_spawn),
    ):
        result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    # The orphan was reaped, so the guard didn't block — dispatch went through.
    assert len(spawn_calls) == 1
    assert result.run_id is not None
    assert result.skip_reason is None
    # The stale run is now terminal.
    reaped = await database_sync_to_async(TaskRun.objects.get)(id=task_run.id)
    assert reaped.status == TaskRun.Status.FAILED


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_recent_in_progress_run_is_not_reaped_and_still_blocks(ateam, aerrors_skill):
    TaskRun = apps.get_model("tasks", "TaskRun")
    # A genuinely in-flight run (younger than the cutoff) must still single-flight — the
    # self-heal must not reap a live run out from under itself.
    config = await database_sync_to_async(SignalScoutConfig.objects.create)(
        team=ateam, skill_name="signals-scout-errors"
    )
    task_run = await database_sync_to_async(_make_task_run)(ateam)
    await database_sync_to_async(TaskRun.objects.filter(id=task_run.id).update)(
        status=TaskRun.Status.IN_PROGRESS,
        created_at=datetime.now(UTC) - timedelta(seconds=30),
    )
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
        side_effect=AssertionError("session.start should not run while a live run is IN_PROGRESS"),
    ):
        result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert result.skip_reason is not None
    still_running = await database_sync_to_async(TaskRun.objects.get)(id=task_run.id)
    assert still_running.status == TaskRun.Status.IN_PROGRESS


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_stale_run_reap_captures_run_reaped_event(ateam, aerrors_skill):
    TaskRun = apps.get_model("tasks", "TaskRun")
    # Reaping an orphan emits `signals_scout_run_reaped` — the strand's only event (a reaped
    # run never reaches the finalize path, so it emits no `signals_scout_run_finished`). This
    # is what makes the worker-death / mass-stall shape alertable with no warehouse lag.
    config = await database_sync_to_async(SignalScoutConfig.objects.create)(
        team=ateam, skill_name="signals-scout-errors"
    )
    task_run = await database_sync_to_async(_make_task_run)(ateam)
    await database_sync_to_async(TaskRun.objects.filter(id=task_run.id).update)(
        status=TaskRun.Status.IN_PROGRESS,
        created_at=datetime.now(UTC) - timedelta(seconds=STALE_RUN_CUTOFF_S + 60),
    )
    await database_sync_to_async(SignalScoutRun.objects.create)(
        task_run=task_run,
        team=ateam,
        scout_config=config,
        skill_name="signals-scout-errors",
        skill_version=1,
    )

    async def fake_spawn(**_kwargs):
        return "ok", str(task_run.id)

    with (
        patch("products.signals.backend.scout_harness.runner._spawn_and_run", side_effect=fake_spawn),
        patch("products.signals.backend.scout_harness.runner.posthoganalytics.capture") as capture,
    ):
        await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    reaped = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_run_reaped")
    assert reaped.kwargs["distinct_id"] == str(ateam.uuid)
    props = reaped.kwargs["properties"]
    assert props["skill_name"] == "signals-scout-errors"
    assert props["task_run_id"] == str(task_run.id)
    assert props["status_before"] == TaskRun.Status.IN_PROGRESS
    assert props["stale_cutoff_seconds"] == STALE_RUN_CUTOFF_S
    # Age is measured from the orphan's TaskRun.created_at, so it clears the cutoff.
    assert props["age_seconds"] >= STALE_RUN_CUTOFF_S


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_cancelled_run_re_raises(ateam, aerrors_skill):
    """asyncio.CancelledError is BaseException, not Exception — the runner must let it
    propagate so Temporal marks the activity failed, rather than swallowing it. Run status
    now lives on the linked TaskRun (managed by MultiTurnSession); the bridge row is created
    inside `_spawn_and_run`, so a cancellation that escapes before the session starts leaves
    no orphaned bridge row.
    """

    async def fake_spawn(**_kwargs):
        raise asyncio.CancelledError("worker is shutting down")

    with (
        patch("products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.runner._spawn_and_run", side_effect=fake_spawn),
    ):
        with pytest.raises(asyncio.CancelledError):
            await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    # No bridge row orphaned — it's created inside the patched-out `_spawn_and_run`.
    count = await database_sync_to_async(SignalScoutRun.objects.filter(team=ateam).count)()
    assert count == 0


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_returns_completed_outcome(ateam):
    TaskRun = apps.get_model("tasks", "TaskRun")

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
        "products.signals.backend.scout_harness.runner.arun_signals_scout",
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
        "products.signals.backend.scout_harness.runner.arun_signals_scout",
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


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_skips_run_when_team_over_signals_quota(ateam):
    fake_arun = AsyncMock()
    with (
        patch(
            "products.signals.backend.temporal.agentic.scout_scheduler.is_team_signals_quota_limited",
            return_value=True,
        ),
        patch("products.signals.backend.scout_harness.runner.arun_signals_scout", fake_arun),
    ):
        env = ActivityEnvironment()
        output = await env.run(
            run_signals_scout_activity,
            RunSignalsScoutInput(team_id=ateam.id, skill_name="signals-scout-errors"),
        )

    fake_arun.assert_not_called()
    assert output.run_id is None
    assert output.status is None
    assert output.skip_reason == "quota_limited"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_runs_when_team_under_signals_quota(ateam):
    TaskRun = apps.get_model("tasks", "TaskRun")

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

    with (
        patch(
            "products.signals.backend.temporal.agentic.scout_scheduler.is_team_signals_quota_limited",
            return_value=False,
        ),
        patch("products.signals.backend.scout_harness.runner.arun_signals_scout", side_effect=fake_arun),
    ):
        env = ActivityEnvironment()
        output = await env.run(
            run_signals_scout_activity,
            RunSignalsScoutInput(team_id=ateam.id, skill_name="signals-scout-errors"),
        )

    assert output.status == "completed"
    assert output.skip_reason is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_swallows_transient_db_connection_drop(ateam):
    # A pgbouncer pool recycle / failover can surface as OperationalError from the runner's
    # synchronous DB access, outside the run-row try/except. The activity's "never raises"
    # contract must hold: report a failed run instead of letting it escape.
    async def fake_arun(**_kwargs):
        raise OperationalError("server closed the connection unexpectedly")

    with patch(
        "products.signals.backend.scout_harness.runner.arun_signals_scout",
        side_effect=fake_arun,
    ):
        env = ActivityEnvironment()
        output = await env.run(
            run_signals_scout_activity,
            RunSignalsScoutInput(team_id=ateam.id, skill_name="signals-scout-errors"),
        )

    assert output.run_id is None
    assert output.task_run_id is None
    assert output.status == "failed"
    assert output.skill_name == "signals-scout-errors"
    assert output.skip_reason is None


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
        config = SignalScoutConfig.objects.create(team=team, skill_name="signals-scout-errors")
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
