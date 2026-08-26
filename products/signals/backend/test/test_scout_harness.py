from __future__ import annotations

import re
import json
import random
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.apps import apps
from django.db import OperationalError
from django.test import SimpleTestCase

import pytest_asyncio
from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.scoping import team_scope
from posthog.models.utils import uuid7
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.daily_limit import DailyReportLimitGate
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.report_charts import ReportChart
from products.signals.backend.scout_harness.derived_metadata import DERIVED_METADATA_KEY
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY, _compute_row_hash
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S, failure_streak_pause_threshold
from products.signals.backend.scout_harness.model_selection import ScoutModel
from products.signals.backend.scout_harness.prompt import (
    _EXTERNAL_MCP_LISTING_CAP,
    _GOVERNED_METRIC_LISTING_CAP,
    _METRICS_CATALOG_SUPERSEDES_CACHE as _SUPERSEDES_CACHED_ENTRIES,
    _REPORT_CHARTS,
    HARNESS_PROMPT_VERSION,
    build_run_prompt,
)
from products.signals.backend.scout_harness.runner import (
    SIGNALS_SCOUT_FULL_NETWORK_ENV_NAME,
    SIGNALS_SCOUT_SANDBOX_ENV_NAME,
    RunResult,
    _ai_stage,
    _create_run_row,
    _failure_streak_runs_in_window,
    arun_signals_scout,
)
from products.signals.backend.scout_harness.skill_loader import (
    LoadedSkill,
    SkillNotFoundError,
    is_signals_scout_skill,
    load_skill_for_run,
    resolve_scout_acting_user_id,
)
from products.signals.backend.scout_harness.tools.runs import _build_task_url, _to_detail, _to_summary
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, run_signals_scout_activity
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile, LLMSkillOwner
from products.tasks.backend.facade import api as tasks_facade

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

    def test_authors_lead_with_creator_not_last_editor(self) -> None:
        # Each version row's `created_by` is whoever published that version, so the pinned
        # (latest) row alone attributes the skill to its last editor. A regression back to
        # reading the loaded row's `created_by` flips this ordering.
        ben = User.objects.create_and_join(self.organization, "ben@posthog.com", None, "Ben")
        v1 = self._create_skill("signals-scout-errors")
        v1.created_by = ben
        v1.is_latest = False
        v1.save()
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="A test skill",
            body="edited body",
            version=2,
            is_latest=True,
            created_by=self.user,
        )
        loaded = load_skill_for_run(self.team, "signals-scout-errors", include_authors=True)
        assert [(a.role, a.email) for a in loaded.authors] == [
            ("creator", "ben@posthog.com"),
            ("editor", self.user.email),
        ]
        # Off by default: the report-authorization path in views loads the skill on every report
        # write just to check allowed_tools and must not pay the author scan.
        assert load_skill_for_run(self.team, "signals-scout-errors").authors == []

    def test_diverged_seeded_skill_creator_is_first_human_author(self) -> None:
        # A seeded row's v1 is system-authored (`created_by=None`); the creator of the diverged
        # skill is whoever first edited it, not "the author of version 1".
        seeded_metadata = {"seeded_by": HARNESS_SEEDED_BY, "canonical_hash": "0" * 64}
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-general",
            description="d",
            body="b",
            metadata=seeded_metadata,
            is_latest=False,
        )
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-general",
            description="d",
            body="edited",
            version=2,
            is_latest=True,
            created_by=self.user,
            metadata=seeded_metadata,
        )
        loaded = load_skill_for_run(self.team, "signals-scout-general", include_authors=True)
        assert [(a.role, a.email) for a in loaded.authors] == [("creator", self.user.email)]

    def test_authors_exclude_users_without_project_access(self) -> None:
        # An author's display name is self-editable and flows into a privileged prompt, so a
        # former member must stop resolving the moment their access is revoked — otherwise they
        # keep a post-revocation steering channel into scheduled runs (and waste an editor slot
        # on someone reviewer routing can't reach anyway).
        ben = User.objects.create_and_join(self.organization, "ben@posthog.com", None, "Ben")
        v1 = self._create_skill("signals-scout-errors")
        v1.created_by = ben
        v1.is_latest = False
        v1.save()
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="A test skill",
            body="edited body",
            version=2,
            is_latest=True,
            created_by=self.user,
        )
        OrganizationMembership.objects.filter(user=ben).delete()
        loaded = load_skill_for_run(self.team, "signals-scout-errors", include_authors=True)
        assert [(a.role, a.email) for a in loaded.authors] == [("creator", self.user.email)]

    def test_authors_empty_for_pristine_canonical_skill(self) -> None:
        skill = LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-general",
            description="d",
            body="b",
            created_by=self.user,
            metadata={"seeded_by": HARNESS_SEEDED_BY},
        )
        skill.metadata["canonical_hash"] = _compute_row_hash(skill, [])
        skill.save()
        assert load_skill_for_run(self.team, "signals-scout-general", include_authors=True).authors == []

    def test_authors_prefer_explicit_owners_over_version_history(self) -> None:
        # With an explicit owner set, ownership is authoritative and stable: a later editor never
        # displaces the owner. Here ben owns the skill but self.user is the latest editor — the
        # version-history reconstruction would surface self.user, the owner set must not.
        ben = User.objects.create_and_join(self.organization, "ben@posthog.com", None, "Ben")
        v1 = self._create_skill("signals-scout-errors")
        v1.is_latest = False
        v1.save()
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="A test skill",
            body="edited body",
            version=2,
            is_latest=True,
            created_by=self.user,
        )
        LLMSkillOwner.objects.for_team(self.team.id).create(team=self.team, skill_name="signals-scout-errors", user=ben)
        loaded = load_skill_for_run(self.team, "signals-scout-errors", include_authors=True)
        assert [(a.role, a.email) for a in loaded.authors] == [("owner", "ben@posthog.com")]

    def test_owned_skill_with_all_owners_revoked_returns_no_authors(self) -> None:
        # A skill with owner rows is authoritatively owned. If every owner loses access, the reviewer
        # path must return NO authors, not silently drift back to the version-history editor — the
        # exact misroute the owner primitive exists to prevent. self.user is a valid version author
        # here, so a regression that falls through would surface them.
        ben = User.objects.create_and_join(self.organization, "ben@posthog.com", None, "Ben")
        skill = self._create_skill("signals-scout-errors")
        skill.created_by = self.user
        skill.save()
        LLMSkillOwner.objects.for_team(self.team.id, canonical=True).create(
            team=self.team, skill_name="signals-scout-errors", user=ben
        )
        OrganizationMembership.objects.filter(user=ben).delete()

        loaded = load_skill_for_run(self.team, "signals-scout-errors", include_authors=True)
        assert loaded.authors == []

    def _create_config(self, **kwargs) -> SignalScoutConfig:
        return SignalScoutConfig.objects.unscoped().create(
            team_id=self.team.id, skill_name="signals-scout-errors", **kwargs
        )

    def test_acting_user_is_creator_even_when_config_names_an_enabler(self) -> None:
        # The creator authored the prompt the run executes, so they must win over whoever
        # merely switched the scout on.
        ben = User.objects.create_and_join(self.organization, "ben@example.com", None, "Ben")
        v1 = self._create_skill("signals-scout-errors")
        v1.created_by = ben
        v1.is_latest = False
        v1.save()
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="A test skill",
            body="edited body",
            version=2,
            is_latest=True,
            created_by=self.user,
        )
        config = self._create_config(enabled_by=self.user)
        assert resolve_scout_acting_user_id(self.team, "signals-scout-errors", config) == ben.id

    def test_acting_user_falls_back_to_config_enabler_for_authorless_skill(self) -> None:
        # A pristine canonical scout's versions are all system-authored, so without the config
        # fallback its runs pool on the team-level default user, which is the cost-allocation
        # bug this resolver exists to fix. `enabled_by` outranks `created_by`: switching a
        # scout on is the spend decision.
        ben = User.objects.create_and_join(self.organization, "ben@example.com", None, "Ben")
        self._create_skill("signals-scout-errors")
        config = self._create_config(enabled_by=ben, created_by=self.user)
        assert resolve_scout_acting_user_id(self.team, "signals-scout-errors", config) == ben.id

    def test_acting_user_skips_config_enabler_without_access(self) -> None:
        # The run mints a sandbox token as the resolved user, so a revoked member must never
        # resolve; the next self-consenting candidate (the config creator) takes over.
        ben = User.objects.create_and_join(self.organization, "ben@example.com", None, "Ben")
        self._create_skill("signals-scout-errors")
        config = self._create_config(enabled_by=ben, created_by=self.user)
        OrganizationMembership.objects.filter(user=ben).delete()
        assert resolve_scout_acting_user_id(self.team, "signals-scout-errors", config) == self.user.id

    def test_acting_user_none_when_creator_lost_access(self) -> None:
        # A revoked skill creator with no config candidates must resolve to nothing, so the
        # runner falls back to the team-level default instead of minting for a removed member.
        ben = User.objects.create_and_join(self.organization, "ben@example.com", None, "Ben")
        skill = self._create_skill("signals-scout-errors")
        skill.created_by = ben
        skill.save()
        OrganizationMembership.objects.filter(user=ben).delete()
        assert resolve_scout_acting_user_id(self.team, "signals-scout-errors", self._create_config()) is None

    def test_signals_scout_prefix_check(self) -> None:
        match = self._create_skill("signals-scout-errors")
        non_match = self._create_skill("custom-research-helper")
        assert is_signals_scout_skill(match) is True
        assert is_signals_scout_skill(non_match) is False


class TestReportChartsSection(SimpleTestCase):
    def test_worked_example_is_the_json_it_claims_to_be(self) -> None:
        # The section is an f-string, so every brace in the example is doubled. A single brace is
        # not a syntax error: `{"kind"}` is a valid set expression, so a mistyped example renders as
        # mangled Python repr and teaches every scout in the fleet a query shape that cannot parse.
        block = re.search(r"```json\n(.*?)\n```", _REPORT_CHARTS, re.S)
        assert block is not None
        charts = json.loads(block.group(1))

        assert [c["query"]["kind"] for c in charts] == ["InsightVizNode", "DataVisualizationNode"]
        for chart in charts:
            ReportChart.model_validate(chart)

    def test_sql_example_names_its_axes(self) -> None:
        # A graphical DataVisualizationNode renders an empty box without chartSettings, so the
        # example is the only place a scout learns to set it.
        block = re.search(r"```json\n(.*?)\n```", _REPORT_CHARTS, re.S)
        assert block is not None
        sql_chart = json.loads(block.group(1))[1]["query"]

        assert sql_chart["chartSettings"]["xAxis"]["column"]
        assert sql_chart["chartSettings"]["yAxis"][0]["column"]


class TestPromptCrossReferences(SimpleTestCase):
    @parameterized.expand(
        [
            ("signal_canonical", [], "canonical", False),
            ("signal_custom", [], "custom", False),
            ("report_both", ["emit_report", "edit_report"], "custom", False),
            ("report_both_github", ["emit_report", "edit_report"], "canonical", True),
            ("report_emit_only", ["emit_report"], "custom", False),
            ("report_emit_only_github", ["emit_report"], "custom", True),
            ("report_edit_only", ["edit_report"], "custom", False),
            # The `gh` section is the one that references an author-time section, so the edit-only
            # persona (which renders no author-time sections) only dangles with the token granted.
            ("report_edit_only_github", ["edit_report"], "custom", True),
        ]
    )
    def test_every_referenced_section_renders_in_the_same_prompt(
        self, _name: str, allowed_tools: list[str], origin: str, github_read_access: bool
    ) -> None:
        # Shared rules (the untrusted-input boundary, the front-load writing rule, the side-channel
        # etiquette) are stated once and pointed at by name from the sections that used to restate
        # them. Each tail is assembled by its own code path, so dropping a section from one list, or
        # renaming its heading, leaves the other sections telling the scout to consult guidance that
        # is not in its prompt — a silently missing rule no per-string assertion catches.
        prompt = build_run_prompt(
            LoadedSkill(
                name="signals-scout-errors",
                version=1,
                body="watch",
                description="d",
                allowed_tools=allowed_tools,
                files=[],
                skill_id="skill-1",
                origin=origin,  # type: ignore[arg-type]
                authors=[],
            ),
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=1,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
            github_read_access=github_read_access,
        )
        headings = {line.removeprefix("# ") for line in prompt.splitlines() if line.startswith("# ")}
        # `*Emphasized*` spans naming another section, e.g. "see *Ground rules*". Single asterisks
        # only, so `**bold**` labels don't register, and title-cased so the lowercase *what* / *why*
        # stress marks scattered through the prose aren't read as cross-references.
        referenced = set(re.findall(r"(?<![\w*])\*([A-Z][^*\n]{3,60})\*(?!\*)", prompt))
        assert referenced, "no cross-references found — the extraction pattern has drifted"
        assert referenced <= headings, f"dangling cross-references: {sorted(referenced - headings)}"


class TestStructuredOutputPromptSection(SimpleTestCase):
    _SCHEMA = {
        "type": "object",
        "properties": {"verdict": {"enum": ["good", "bad", "unsure"]}, "reason": {"type": "string"}},
        "required": ["verdict", "reason"],
    }

    @parameterized.expand(
        [
            ("signal_channel", []),
            ("report_channel", ["emit_report", "edit_report"]),
            ("edit_only", ["edit_report"]),
        ]
    )
    def test_section_renders_only_when_config_carries_a_schema(self, _name: str, allowed_tools: list[str]) -> None:
        # Two failure modes, both silent in production: dropping the section leaves a
        # schema-configured scout never told to record (the channel exists but nothing uses it),
        # and rendering it unconditionally steers schema-less scouts at a tool that fails closed.
        def _prompt(schema: dict | None) -> str:
            return build_run_prompt(
                LoadedSkill(
                    name="signals-scout-judge",
                    version=1,
                    body="judge",
                    description="d",
                    allowed_tools=allowed_tools,
                    files=[],
                    skill_id="skill-1",
                    origin="custom",
                    authors=[],
                ),
                run_id="00000000-0000-0000-0000-000000000abc",
                team_id=1,
                started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
                structured_output_schema=schema,
            )

        with_schema = _prompt(self._SCHEMA)
        assert "# Structured output" in with_schema
        assert "scout-record-output" in with_schema
        # The exact schema the endpoint enforces is rendered, so the prompt and the
        # validator can never describe two different contracts.
        assert '"verdict"' in with_schema

        without_schema = _prompt(None)
        assert "# Structured output" not in without_schema
        assert "scout-record-output" not in without_schema


class TestExternalMcpServersPromptSection(SimpleTestCase):
    def _prompt(self, mcp_server_names: list[str] | None) -> str:
        return build_run_prompt(
            LoadedSkill(
                name="signals-scout-errors",
                version=1,
                body="watch",
                description="d",
                allowed_tools=[],
                files=[],
                skill_id="skill-1",
                origin="canonical",
                authors=[],
            ),
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=1,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
            mcp_server_names=mcp_server_names,
        )

    def test_carve_out_renders_only_when_the_run_mounts_external_servers(self) -> None:
        # Two silent failure modes: dropping the paragraph leaves the exec-interface rule reading
        # as universal, steering a scout away from the only way its mounted external tools can be
        # called; rendering it unconditionally steers server-less scouts at ToolSearch lookups
        # that can't match.
        mounted = self._prompt(["Linear", "Notion"])
        assert "`Linear`" in mounted
        assert "`Notion`" in mounted
        assert "mcp__<server>__<tool>" in mounted
        # The exec rule stays: external servers are a carve-out, not a replacement.
        assert "mcp__posthog__exec" in mounted

        for unmounted in (self._prompt(None), self._prompt([])):
            assert "mcp__<server>__<tool>" not in unmounted
            assert "Linear" not in unmounted

        overflowing = [f"server-{index:02d}" for index in range(_EXTERNAL_MCP_LISTING_CAP + 5)]
        capped = self._prompt(overflowing)
        assert f"`server-{_EXTERNAL_MCP_LISTING_CAP - 1:02d}`" in capped
        assert f"server-{_EXTERNAL_MCP_LISTING_CAP:02d}" not in capped
        # Past the cap the listing says it's partial, so an omitted server isn't read as unmounted.
        assert "5 more this listing omits" in capped


class TestBusinessKnowledgePromptSection(SimpleTestCase):
    # Each channel assembles its own tail list, so the gate can be lost or inverted on one
    # channel alone.
    @parameterized.expand(
        [
            ("signal_channel", []),
            ("report_channel", ["emit_report", "edit_report"]),
        ]
    )
    def test_section_renders_only_when_the_team_has_a_knowledge_base(
        self, _name: str, allowed_tools: list[str]
    ) -> None:
        # Both failure modes are silent in production: dropping the section leaves a team that
        # curated a knowledge base with scouts that never search it, and rendering it for everyone
        # steers the whole fleet at BK tools that are only in the toolset when that product's flag
        # is on — an unknown-tool burn on every run, for a section most teams can't act on.
        def _prompt(*, maintained: bool) -> str:
            return build_run_prompt(
                LoadedSkill(
                    name="signals-scout-errors",
                    version=1,
                    body="watch",
                    description="d",
                    allowed_tools=allowed_tools,
                    files=[],
                    skill_id="skill-1",
                    origin="custom",
                    authors=[],
                ),
                run_id="00000000-0000-0000-0000-000000000abc",
                team_id=1,
                started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
                business_knowledge_maintained=maintained,
            )

        maintained = _prompt(maintained=True)
        assert "# Business knowledge" in maintained
        assert "business-knowledge-documents-search" in maintained

        unmaintained = _prompt(maintained=False)
        assert "# Business knowledge" not in unmaintained
        # The tool names, specifically — *Ground rules* still names business-knowledge documents as
        # one of the untrusted sources a run may read, and must keep doing so.
        assert "business-knowledge-documents-search" not in unmaintained
        assert "business-knowledge-document-window-retrieve" not in unmaintained


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
        # Calling convention is stated up front: bare tool names resolve only
        # through the exec interface, so the agent doesn't burn opening moves
        # trying to invoke them directly.
        assert "How to call tools" in prompt
        assert "mcp__posthog__exec" in prompt
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
        assert "scout-project-profile-get" in prompt
        # The base prompt teaches the agent to call the harness MCP tools by name.
        assert "scout-emit-signal" in prompt
        assert "scout-scratchpad-search" in prompt
        # Steering notes are prior context on every channel — the section and its tool
        # reference must survive in the signal tail.
        assert "Notes left for you" in prompt
        assert "scout-notes-list" in prompt
        # The fleet-seams section is shared across both channels, but each tail is assembled by
        # its own code path, so assert it on both to catch a drop from either list.
        assert "Working alongside the rest of the fleet" in prompt
        assert "scout_fleet" in prompt
        # The self-validation follow-up discipline is shared too: every scout keeps a
        # skill-namespaced `followup:` queue (a domain-only key would collide across scouts),
        # and the decision to spend a run validating it belongs to the scout, not the harness.
        assert "Follow up on your own past work" in prompt
        assert "followup:<your-skill-name>:<entity>" in prompt
        assert "You decide when a run becomes a validation run" in prompt
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
        # Dedupe rules point a signal scout at the inbox with `include_all_statuses=true` —
        # human-dismissed reports are hidden by default, and their dismissal notes carry the
        # human rationale the scout needs before re-surfacing a topic. The note is free text
        # any task:write caller can author, so the guidance must keep the untrusted-content
        # boundary — a scout holds write scopes an injected note could otherwise steer.
        assert "include_all_statuses=true" in prompt
        assert "dismissal_note" in prompt
        assert "record the rationale in your own words" in prompt
        # Recency ordering too — the default report ordering sorts dismissed reports last,
        # so without it a recent dismissal can paginate out of view.
        assert "ordering=-updated_at" in prompt
        # A signal scout never sees the report-channel guidance — it fires weak
        # signals, it does not author reports.
        assert "scout-emit-report" not in prompt
        assert "Suggested reviewers route the report" not in prompt
        assert "scratchpad entry is a pointer" not in prompt

    def test_github_evidence_section_gated_on_token_grant(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-gh-reports",
            description="Report scout",
            body="watch",
            allowed_tools=["emit_report", "edit_report"],
        )
        loaded = load_skill_for_run(self.team, "signals-scout-gh-reports")
        kwargs: dict = {
            "run_id": "00000000-0000-0000-0000-000000000abc",
            "team_id": self.team.id,
            "started_at": datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        }
        granted = build_run_prompt(loaded, **kwargs, github_read_access=True)
        # The section only renders when the sandbox actually holds the token, and must carry the
        # read-only framing so the scout doesn't attempt writes.
        assert "Code-derived reviewer evidence" in granted
        assert "read-only" in granted

        # Default (no grant): naming `gh` in a tokenless sandbox burns the budget on 401s.
        ungranted = build_run_prompt(loaded, **kwargs)
        assert "Code-derived reviewer evidence" not in ungranted

        # A signal-channel scout has no reviewers field — the section must not leak into its
        # prompt even if the runner flag were mis-set for it.
        LLMSkill.objects.create(team=self.team, name="signals-scout-plain", description="s", body="watch")
        signal_prompt = build_run_prompt(
            load_skill_for_run(self.team, "signals-scout-plain"), **kwargs, github_read_access=True
        )
        assert "Code-derived reviewer evidence" not in signal_prompt

    # The rule lives in the shared run-works head, and each channel assembles its own tail from
    # that head, so a channel can lose it independently.
    @parameterized.expand(
        [
            ("signal_channel", []),
            ("report_channel", ["emit_report", "edit_report"]),
        ]
    )
    def test_catalog_rule_gated_on_data_catalog_flag(self, name: str, allowed_tools: list[str]) -> None:
        skill_name = f"signals-scout-catalog-{name}"
        LLMSkill.objects.create(
            team=self.team,
            name=skill_name,
            description="Catalog scout",
            body="watch",
            allowed_tools=allowed_tools,
        )
        loaded = load_skill_for_run(self.team, skill_name)
        kwargs: dict = {
            "run_id": "00000000-0000-0000-0000-000000000abc",
            "team_id": self.team.id,
            "started_at": datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        }

        enabled = build_run_prompt(loaded, **kwargs, data_catalog_enabled=True)
        assert "system.information_schema.metrics" in enabled
        assert "data-catalog-metric-run" in enabled

        # Default (flag off): the metrics table isn't registered for the team, so steering
        # at it would burn the run's budget on failing queries.
        disabled = build_run_prompt(loaded, **kwargs)
        assert "information_schema.metrics" not in disabled
        assert "data-catalog-metric-run" not in disabled

    def test_prefetched_catalog_listing_replaces_the_probe_instruction(self) -> None:
        LLMSkill.objects.create(team=self.team, name="signals-scout-catalog-listing", description="s", body="watch")
        loaded = load_skill_for_run(self.team, "signals-scout-catalog-listing")
        kwargs: dict = {
            "run_id": "00000000-0000-0000-0000-000000000abc",
            "team_id": self.team.id,
            "started_at": datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        }
        names = ["scout_cost_per_run", "scout_run_fail_pct"]

        listed = build_run_prompt(loaded, **kwargs, data_catalog_enabled=True, governed_metric_names=names)
        assert "`scout_run_fail_pct`" in listed
        assert "`scout_cost_per_run`" in listed
        assert "data-catalog-metric-run" in listed
        assert "Cache the lookup outcome" not in listed
        assert _SUPERSEDES_CACHED_ENTRIES in listed
        assert "governed catalog consulted: no listed metric matched" in listed

        empty = build_run_prompt(loaded, **kwargs, data_catalog_enabled=True, governed_metric_names=[])
        assert "no approved metrics" in empty
        assert "Cache the lookup outcome" not in empty
        assert _SUPERSEDES_CACHED_ENTRIES in empty
        assert "governed catalog consulted: empty, no metric matches" in empty

        fallback = build_run_prompt(loaded, **kwargs, data_catalog_enabled=True, governed_metric_names=None)
        assert "Cache the lookup outcome" in fallback
        assert _SUPERSEDES_CACHED_ENTRIES not in fallback
        assert "governed catalog consulted: no listed metric matched" in fallback

        # The cap is what keeps this injection to a handful of tokens in every catalog-enabled run,
        # and past it the listing stops being the whole catalog, so it has to say a lookup is still
        # warranted for an unlisted measure.
        overflowing = [f"metric_{index:03d}" for index in range(_GOVERNED_METRIC_LISTING_CAP + 3)]
        capped = build_run_prompt(loaded, **kwargs, data_catalog_enabled=True, governed_metric_names=overflowing)
        assert "`metric_000`" in capped
        assert f"`metric_{_GOVERNED_METRIC_LISTING_CAP:03d}`" not in capped
        assert "and 3 more this listing omits" in capped

        flag_off = build_run_prompt(loaded, **kwargs, governed_metric_names=names)
        assert "scout_run_fail_pct" not in flag_off
        assert "data-catalog-metric-run" not in flag_off

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
        assert "scout-emit-report" in prompt
        assert "scout-edit-report" in prompt
        # Steering notes are prior context on the report channel too.
        assert "Notes left for you" in prompt
        assert "scout-notes-list" in prompt
        # Fleet seams too — the report tail is built by `_report_tail_sections`, a separate list
        # from the signal tail, so it can lose the shared section independently.
        assert "Working alongside the rest of the fleet" in prompt
        # Same for the shared self-validation follow-up discipline.
        assert "Follow up on your own past work" in prompt
        assert "followup:<your-skill-name>:<entity>" in prompt
        # The two highest-leverage nudges the report channel adds: search the inbox
        # and edit before authoring a duplicate, and set suggested reviewers (what
        # actually routes a report).
        assert "Authoring vs. editing: search the inbox first" in prompt
        assert "inbox-reports-list" in prompt
        assert "Suggested reviewers route the report" in prompt
        assert "suggested_reviewers" in prompt
        # Reviewer routing accepts a `user_uuid` (server-resolved to a GitHub login), and when the
        # owner isn't already in the evidence the prompt points the scout at the in-run
        # `scout-members-list` tool — so it must name both rather than letting it guess a
        # handle or reach for the org-scoped resolver that's stripped from a scout run.
        assert "user_uuid" in prompt
        assert "scout-members-list" in prompt
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
        # The inbox search must widen to human-dismissed reports (`include_all_statuses=true`) and
        # read their dismissal notes — a human's dismissal rationale is context the scout needs
        # before re-surfacing a topic. Dropping either re-opens the "re-report what a human
        # already dismissed" failure mode. The note is free text any task:write caller can
        # author, so the guidance must keep the untrusted-content boundary — a scout holds
        # write scopes an injected note could otherwise steer.
        assert "include_all_statuses=true" in prompt
        assert "dismissal_note" in prompt
        assert "record the rationale in your own words" in prompt
        # Signal-only sections (weak-finding schema, tagging taxonomy) are dropped
        # for a report scout — it doesn't fire `emit_signal`.
        assert "scout-emit-signal" not in prompt
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
            ("custom_report_scout_emit_only", "signals-scout-errors", {}, ["emit_report"], True),
            # No stored canonical_hash (pre-hash-tracking legacy row): unprovable, stays canonical.
            ("canonical_scout_no_hash", "signals-scout-general", {"seeded_by": HARNESS_SEEDED_BY}, [], False),
            (
                "canonical_report_scout",
                "signals-scout-general",
                {"seeded_by": HARNESS_SEEDED_BY},
                ["emit_report", "edit_report"],
                False,
            ),
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
        # The report-escalation guidance (file strong suggestions as inbox reports about the scout)
        # must ride only with report tools the scout actually holds — a signal-channel custom scout
        # has neither, so pointing it at `emit_report` would steer it into a PermissionDenied.
        expect_escalation = expect_section and "emit_report" in allowed_tools
        assert ("Scout self-improvement:" in prompt) is expect_escalation
        # Reviewer routing for self-improvement reports points at the run-identity authors line,
        # not at "whoever owns this scout" guesswork — dropping the reference re-opens the
        # last-editor-becomes-the-assignee failure mode.
        assert ("the skill authors listed under *Your run identity*" in prompt) is expect_escalation
        if _name == "custom_report_scout_emit_only":
            # The emit-only variant must never name the edit tool it lacks (fails closed).
            assert "scout-edit-report" not in prompt
        # The canonical-improvement channel is the exact inverse of the self-improvement gate: a
        # canonical scout routes skill-content gaps upstream via agent-feedback, while a custom or
        # diverged scout must never be told to send its team-owned skill body to the PostHog team.
        assert ("Suggest improvements to your canonical skill" in prompt) is not expect_section
        assert ('`feedback_type` = `"scout"`' in prompt) is not expect_section
        # The structured fields and the reported: dedupe key are what make fleet-wide feedback
        # aggregable per skill/version and non-repetitive across runs — they must ride with the section.
        assert ("scout_skill_name" in prompt) is not expect_section
        assert ("reported:<your-skill-name>:<topic>" in prompt) is not expect_section
        # The generalization rule is the privacy boundary: the feedback leaves the customer's
        # project, so dropping this line silently re-opens the customer-data-travels failure mode.
        assert ("this project's data must not travel" in prompt) is not expect_section
        # The upstream friction channel is origin-independent: harness/tool defects still route there.
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
        # The pristine canonical scout routes skill-content gaps upstream instead.
        assert "Suggest improvements to your canonical skill" in prompt
        # A canonical skill body is PostHog-owned — the run identity must not name the seeding
        # row's incidental `created_by` as a skill author.
        assert "skill authors" not in prompt

    def test_run_identity_names_skill_authors_creator_first(self) -> None:
        # The rendered line is what the escalation guidance points `suggested_reviewers` at;
        # if it drops the creator, or renders for a skill with no known authors, routing
        # falls back to the last editor (the exact misattribution this line exists to fix).
        ben = User.objects.create_and_join(self.organization, "ben@posthog.com", None, "Ben")
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="d",
            body="b",
            created_by=ben,
            is_latest=False,
        )
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="d",
            body="edited",
            version=2,
            is_latest=True,
            created_by=self.user,
            allowed_tools=["emit_report"],
        )
        loaded = load_skill_for_run(self.team, "signals-scout-errors", include_authors=True)
        prompt = build_run_prompt(
            loaded,
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=self.team.id,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        )
        assert "**skill authors**: created by Ben (ben@posthog.com); since edited by" in prompt
        assert self.user.email in prompt
        # The authors line is a default, not an override — dropping the precedence hedge would
        # set the harness up to fight a skill body that defines its own reviewer routing.
        assert "unless your skill body defines its own reviewer routing" in prompt
        # A signal-channel scout has no `suggested_reviewers` field, so member names/emails must
        # not reach its prompt — there is no feature path that could use them.
        signal_prompt = build_run_prompt(
            replace(loaded, allowed_tools=[]),
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=self.team.id,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        )
        assert "skill authors" not in signal_prompt
        assert "ben@posthog.com" not in signal_prompt

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
        # `scout-edit-report` — the endpoint fails closed on the exact tool, so naming it
        # would route the run into a PermissionDenied. This is the regression the per-tool gating guards.
        prompt = self._report_prompt_for(["emit_report"])
        assert "scout-emit-report" in prompt
        assert "scout-edit-report" not in prompt
        assert "Authoring reports: search the inbox first" in prompt
        assert "Suggested reviewers route the report" in prompt
        # The dedup nuances reach the emit-only variant too — not just the both-tools prompt.
        assert "ordering=-updated_at" in prompt
        # Same for the dismissed-report guidance: the emit-only section is a separate constant,
        # so it can lose the widened search or the untrusted-note boundary independently.
        assert "include_all_statuses=true" in prompt
        assert "dismissal_note" in prompt
        assert "record the rationale in your own words" in prompt
        # An emit-only scout can't edit, so a relapse of a CLOSED report must become a fresh report
        # rather than a skip — otherwise relapses on resolved/suppressed/failed reports are dropped.
        assert "relapse of a closed report" in prompt

    def test_edit_only_report_scout_never_references_emit_tool(self) -> None:
        # The mirror case: an edit_report-only scout must never be told to author via
        # `scout-emit-report`, and the standalone author-time sections (the suggested-reviewers
        # deep-dive, writing a report) are dropped since it can't author. It still learns it can SET
        # reviewers via edit (the routing rescue), folded into the editing guidance — not the H1 section.
        prompt = self._report_prompt_for(["edit_report"])
        assert "scout-edit-report" in prompt
        assert "scout-emit-report" not in prompt
        assert "Editing existing reports" in prompt
        assert "Suggested reviewers route the report" not in prompt
        assert "Writing the report" not in prompt
        assert "suggested_reviewers" in prompt
        # An edit-only scout can still rescue an unrouted report's reviewers, so the editing guidance
        # carries the in-run member lookup too — even though the standalone author-time deep-dive drops.
        assert "scout-members-list" in prompt
        # An edit-only scout searches the inbox to find the report to update, so it needs the same
        # dedup nuance — else the default ordering hides the most recently updated match.
        assert "ordering=-updated_at" in prompt
        # Same for the dismissed-report guidance: the edit-only section is a separate constant,
        # so it can lose the widened search or the untrusted-note boundary independently.
        assert "include_all_statuses=true" in prompt
        assert "dismissal_note" in prompt
        assert "record the rationale in your own words" in prompt

    @parameterized.expand(
        [
            # (label, allowed_tools, resurface_tool). The section's re-surface clause must follow
            # the same fail-closed rule as the channel sections — steering a scout at a tool it
            # never opted into routes the failed-validation re-surface into a PermissionDenied.
            # The wrong-tool half of that rule is already policed by the channel tests above
            # (they assert the unheld tool appears nowhere in the whole prompt); these rows pin
            # that the clause names a re-surface path the scout actually holds, on every variant.
            ("signal_channel", [], "scout-emit-signal"),
            ("report_both", ["emit_report", "edit_report"], "scout-emit-report"),
            ("report_emit_only", ["emit_report"], "scout-emit-report"),
            ("report_edit_only", ["edit_report"], "scout-edit-report"),
        ]
    )
    def test_followup_section_resurface_clause_channel_matched(
        self, _name: str, allowed_tools: list[str], resurface_tool: str
    ) -> None:
        name = "signals-scout-fu-" + (_name.replace("_", "-"))
        LLMSkill.objects.create(team=self.team, name=name, description="d", body="b", allowed_tools=allowed_tools)
        prompt = build_run_prompt(
            load_skill_for_run(self.team, name),
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=self.team.id,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        )
        assert "Follow up on your own past work" in prompt
        # The validation cadence is the scout's own judgment — the section must say so rather
        # than reference a harness trigger that no longer exists.
        assert "You decide when a run becomes a validation run" in prompt
        # A validation pass must defer resolved-report re-measurement to the canonical
        # inbox-validation scout when it runs — otherwise it duplicates that scout's whole surface.
        assert "signals-scout-inbox-validation" in prompt
        section = prompt[prompt.index("Follow up on your own past work") :]
        assert resurface_tool in section.split("# ")[0]


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
    # Scouts pass a `scout:<skill>` ai_stage to the sandbox session so every $ai_generation
    # carries it, letting scout spend be split out of the ai_product='signals' bucket (scouts
    # have no report id) and attributed to one scout.
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

    # `signals-scout-errors` is not a canonical scout, so its team-authored name is withheld.
    assert captured["ai_stage"] == "scout:custom"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_acts_as_the_skill_creator_when_one_resolves(ateam, aorganization, aerrors_skill):
    # Spend attribution follows the task row's user, so a run whose skill has a creator must
    # mint under them; falling through to the team-level default (42 here) re-pools every
    # scout's spend on one user, the bug the skill-based resolution exists to fix.
    def _set_creator() -> User:
        creator = User.objects.create_and_join(aorganization, f"creator-{random.randint(1, 99999)}@example.com", None)
        aerrors_skill.created_by = creator
        aerrors_skill.save()
        return creator

    creator = await database_sync_to_async(_set_creator, thread_sensitive=False)()
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

    assert captured["context"].user_id == creator.id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_passes_the_per_scout_server_selection_and_no_credential_owner(ateam, aerrors_skill):
    # A scout is a team resource: its runs mount only team-scoped grants, gated by the
    # config's per-scout server selection, and never delegate anyone's personal grants.
    # Passing a credential owner here would silently re-open the personal lane.
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)
    captured: dict = {}

    def _seed_config() -> None:
        creator = User.objects.create(email=f"scout-owner-{random.randint(1, 99999)}@example.com")
        SignalScoutConfig.objects.unscoped().create(
            team_id=ateam.id,
            skill_name="signals-scout-errors",
            created_by=creator,
            mcp_gateway_server_ids=["11111111-1111-1111-1111-111111111111"],
        )

    await database_sync_to_async(_seed_config, thread_sensitive=False)()

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

    assert captured["mcp_builtin_agent_key"] == "scout"
    assert captured.get("mcp_credential_owner_id") is None
    assert captured["mcp_gateway_server_ids"] == ["11111111-1111-1111-1111-111111111111"]


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "flag,expect_rule",
    [
        pytest.param(True, True, id="enabled"),
        pytest.param(False, False, id="disabled"),
        # A flag-read error resolves off and the run still completes: failing here would book a
        # failed run and advance the streak toward pausing the lane, over a prompt section the
        # run does not need.
        pytest.param(RuntimeError("flag backend down"), False, id="flag_read_error"),
    ],
)
async def test_catalog_steering_reaches_the_prompt_from_the_team_flag(ateam, aerrors_skill, flag, expect_rule):
    # The prompt-builder tests take `data_catalog_enabled` directly, so they stay green if the
    # runner stops resolving or forwarding the flag — this covers that wiring end to end.
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)
    captured: dict = {}

    async def _capture_start(*args, on_task_run_created=None, **kwargs):
        captured.update(kwargs)
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        return session, result

    flag_mock = MagicMock(side_effect=flag) if isinstance(flag, Exception) else MagicMock(return_value=flag)
    with (
        patch("products.signals.backend.scout_harness.runner.MultiTurnSession.start", new=_capture_start),
        patch("products.signals.backend.scout_harness.runner.is_data_catalog_enabled", flag_mock),
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

    assert run_result.status == apps.get_model("tasks", "TaskRun").Status.COMPLETED.value
    assert ("information_schema.metrics" in captured["prompt"]) is expect_rule


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "names,expected_marker",
    [
        pytest.param(["scout_run_fail_pct"], "scout_run_fail_pct", id="listing_injected"),
        pytest.param(RuntimeError("catalog read down"), "Cache the lookup outcome", id="lookup_error_falls_back"),
    ],
)
async def test_governed_listing_reaches_the_prompt_from_the_catalog(ateam, aerrors_skill, names, expected_marker):
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)
    acting_user = await sync_to_async(User.objects.create_and_join)(
        organization=ateam.organization,
        email=f"scout-catalog-{random.randint(1, 99999)}@posthog.com",
        password=None,
    )
    captured: dict = {}

    async def _capture_start(*args, on_task_run_created=None, **kwargs):
        captured.update(kwargs)
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        return session, result

    names_mock = MagicMock(side_effect=names) if isinstance(names, Exception) else MagicMock(return_value=names)
    with (
        patch("products.signals.backend.scout_harness.runner.MultiTurnSession.start", new=_capture_start),
        patch("products.signals.backend.scout_harness.runner.is_data_catalog_enabled", return_value=True),
        patch("products.signals.backend.scout_harness.runner.approved_metric_names_for_team", names_mock),
        patch(
            "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
            return_value="env-id",
        ),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=acting_user.id,
        ),
    ):
        run_result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    assert run_result.status == apps.get_model("tasks", "TaskRun").Status.COMPLETED.value
    assert expected_marker in captured["prompt"]
    # The listing must be resolved as the run's acting user, or it could be wider than what the run
    # could have queried for itself; the access check lives behind the facade call, so passing the
    # user is the only part of that the runner owns.
    assert names_mock.call_args.args == (ateam, acting_user)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "resolution,expect_carve_out",
    [
        pytest.param(["Linear"], True, id="mounted_server_named"),
        pytest.param([], False, id="no_servers_no_carve_out"),
        # A resolution error degrades to no carve-out and the run still completes: failing here
        # would book a failed run and advance the streak toward pausing the lane, over a paragraph
        # of steering for servers the launch mounts (or not) regardless.
        pytest.param(RuntimeError("store read down"), False, id="resolution_error_falls_back"),
    ],
)
async def test_mounted_mcp_server_names_reach_the_prompt(ateam, aerrors_skill, resolution, expect_carve_out):
    # The prompt-builder tests take `mcp_server_names` directly, so they stay green if the runner
    # stops resolving or forwarding the mounted set — this covers that wiring end to end.
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)
    captured: dict = {}

    async def _capture_start(*args, on_task_run_created=None, **kwargs):
        captured.update(kwargs)
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        return session, result

    names_mock = (
        MagicMock(side_effect=resolution) if isinstance(resolution, Exception) else MagicMock(return_value=resolution)
    )
    with (
        patch("products.signals.backend.scout_harness.runner.MultiTurnSession.start", new=_capture_start),
        patch("products.signals.backend.scout_harness.runner.get_sandbox_mcp_server_names", names_mock),
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

    assert run_result.status == apps.get_model("tasks", "TaskRun").Status.COMPLETED.value
    assert ("mcp__<server>__<tool>" in captured["prompt"]) is expect_carve_out
    if expect_carve_out:
        assert "`Linear`" in captured["prompt"]


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "network_access,expected_env_name,expected_level",
    [
        pytest.param(
            None,
            SIGNALS_SCOUT_SANDBOX_ENV_NAME,
            tasks_facade.SandboxNetworkAccessLevel.TRUSTED,
            id="default_trusted",
        ),
        pytest.param(
            "full",
            SIGNALS_SCOUT_FULL_NETWORK_ENV_NAME,
            tasks_facade.SandboxNetworkAccessLevel.FULL,
            id="full",
        ),
    ],
)
async def test_sandbox_env_matches_config_network_access(
    ateam, aerrors_skill, network_access, expected_env_name, expected_level
):
    # The (env name, level) pair is the egress enforcement point: `upsert_internal_sandbox_env`
    # reasserts policy per call on the per-team env row named here, so a `full` config routed to
    # the shared trusted env would silently lift the restriction for every other scout on the
    # team — and a config value that never reaches provisioning would leave a "full" scout
    # blocked. The default path (no pre-existing config row) must stay on the trusted env.
    if network_access is not None:
        await database_sync_to_async(SignalScoutConfig.objects.create, thread_sensitive=False)(
            team=ateam, skill_name="signals-scout-errors", network_access=network_access
        )
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)
    env_mock = MagicMock(return_value="env-id")

    with (
        patch(
            "products.signals.backend.scout_harness.runner.MultiTurnSession.start",
            new=_fake_start_invoking_hook(session, result),
        ),
        patch("products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env", env_mock),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=42,
        ),
    ):
        run_result = await arun_signals_scout(team_id=ateam.id, skill_name="signals-scout-errors")

    env_mock.assert_called_once_with(ateam.id, expected_env_name, expected_level)
    # Provenance stamp: `metadata.network_access` is present exactly when the run departed from
    # the trusted default — a later config edit must not rewrite what past runs could reach.
    bridge = await database_sync_to_async(SignalScoutRun.objects.unscoped().get)(id=run_result.run_id)
    assert (bridge.metadata or {}).get("network_access") == ("full" if network_access == "full" else None)


def _resolved_failure_threshold(cron_schedule: str | None, interval_minutes: int) -> int:
    config = SignalScoutConfig(run_cron_schedule=cron_schedule, run_interval_minutes=interval_minutes)
    return failure_streak_pause_threshold(_failure_streak_runs_in_window(config))


@parameterized.expand(
    [
        # The schedule floor. Bounded, so the densest lane cannot turn the span into an
        # unbounded lease budget.
        ("floor_interval", None, 30, 25),
        # The outage case the breaker used to get wrong: hourly lanes accrued five failures
        # inside an outage shorter than the 24h probe cooldown the pause then cost them. The
        # threshold sits one past the 12 runs the window fits, so an outage lasting exactly
        # the tolerated span still cannot trip the lane.
        ("hourly_interval", None, 60, 13),
        ("two_hourly_interval", None, 120, 7),
        # An off-grid interval dispatches at the next whole coordinator tick (32 minutes runs
        # hourly), so sizing off the raw column would hand a wedged lane nearly double the
        # leases its real cadence earns.
        ("off_grid_interval_sized_at_its_dispatch_cadence", None, 32, 13),
        # Past the span the count floor takes over — a broken lane must not get more leases
        # just because it runs rarely.
        ("six_hourly_interval", None, 360, 5),
        ("daily_default", None, 1440, 5),
        ("monthly_interval", None, 43200, 5),
        # A cron wins at dispatch, but `run_interval_minutes` keeps whatever it held before —
        # so reading the column alone would size an hourly lane as a daily one. Two runs wider
        # than the hourly interval lane: cron lanes are wall-clock schedules, so the sizing
        # window carries DST slack for the largest spring-forward jump a project timezone can
        # select (two hours).
        ("hourly_cron_beats_stale_column", "0 * * * *", 1440, 15),
        ("half_hourly_cron_hits_the_ceiling", "*/30 * * * *", 1440, 25),
        # Bursty: a 30-minute gap that repeats twice a day is not a lane that runs all day, and
        # must not be handed the tolerance of one — that is twelve days of leases on a wedge.
        ("bursty_cron_is_not_a_dense_lane", "0,30 0 * * *", 1440, 5),
        ("uneven_daily_cron", "0 9,17 * * *", 1440, 5),
        # First-of-the-month or Sunday: the fullest window (six runs, 21:00 through 02:00) only
        # exists where a matching Sunday touches a first — May 31st into June 1st in the sampled
        # year. A sample truncated by occurrence count ends months earlier and sizes the lane
        # off its ordinary three-run days.
        ("sparse_cron_fullest_window_at_a_month_boundary", "0 0,1,2,21,22,23 1 * 0", 1440, 7),
        # Valid but with no occurrence in the sampled year at all; sized as a single-run lane
        # rather than crashing or zeroing out.
        ("cron_with_no_occurrence_in_the_sample_year", "0 0 29 2 *", 1440, 5),
        # Both only reachable by an out-of-band write (the API validates cron and interval on
        # save); a run's breaker bookkeeping must not die on either.
        ("malformed_cron_falls_back_to_the_interval", "not a cron", 60, 13),
        ("nonsensical_interval_falls_back_to_the_floor", None, 0, 5),
    ]
)
def test_failure_breaker_threshold_tracks_the_runs_an_outage_can_consume(
    _name, cron_schedule, interval_minutes, expected
):
    # A fleet-wide count means hours on a tight lane and months on a slow one: it either trips
    # healthy hourly scouts during a platform outage or lets a wedged daily scout burn leases
    # for weeks. Both directions have to hold at once, on cron lanes as well as interval ones.
    assert _resolved_failure_threshold(cron_schedule, interval_minutes) == expected


@parameterized.expand(
    [
        ("canonical", "signals-scout-general", "scout:general"),
        ("team_authored", "signals-scout-our-own-thing", "scout:custom"),
    ]
)
def test_ai_stage_tag_only_carries_canonical_scout_names(_name, skill_name, expected):
    # Team-authored names must collapse to `custom`: ai_stage is a low-cardinality tag and the
    # fleet can enroll teams by wildcard, so admitting them grows it without bound.
    skill = LoadedSkill(
        name=skill_name,
        version=1,
        body="scout",
        description="",
        allowed_tools=[],
        files=[],
        skill_id="skill-1",
        # A canonical scout a team edited reads as `custom` here, and must still be named.
        origin="custom",
        authors=[],
    )
    assert _ai_stage(skill) == expected


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "resolved, pin, expected_model, expected_runtime_adapter, expected_reasoning_effort",
    [
        # Gate resolved, no pin: the gate's triple reaches the sandbox as-is — the runtime (and
        # optional effort) travel with the model so the agent server can route it.
        (
            ScoutModel(model="@cf/zai-org/glm-5.2", runtime_adapter="codex", reasoning_effort="high"),
            AgentRuntime(),
            "@cf/zai-org/glm-5.2",
            "codex",
            "high",
        ),
        # Gate resolved AND a fleet-wide pin present: the gate wins — a pin silently swallowing a
        # configured model trial is the production bug this ordering exists to prevent.
        (
            ScoutModel(model="@cf/zai-org/glm-5.2", runtime_adapter="codex"),
            AgentRuntime(runtime_adapter="codex", model="gpt-5.5", reasoning_effort="high"),
            "@cf/zai-org/glm-5.2",
            "codex",
            None,
        ),
        # Gate unallocated remainder: falls through to the pin's whole triple (the fleet default).
        (
            ScoutModel(model=None, runtime_adapter=None),
            AgentRuntime(runtime_adapter="codex", model="gpt-5.5", reasoning_effort="high"),
            "gpt-5.5",
            "codex",
            "high",
        ),
        # Neither configured: agent-server default.
        (ScoutModel(model=None, runtime_adapter=None), AgentRuntime(), None, None, None),
    ],
)
async def test_run_pins_sandbox_to_resolved_scout_model(
    ateam, aerrors_skill, resolved, pin, expected_model, expected_runtime_adapter, expected_reasoning_effort
):
    # The `scouts-model-selection` gate is the per-run experiment layer and wins when it resolves a
    # model; the `signals-pipeline-models` pin is the default layer beneath it. Either way one
    # source supplies the whole runtime/model/effort triple.
    # The routed model must also ride on both lifecycle events (omitted on the default path), so
    # run outcomes are sliceable by model without joining through $ai_generation.
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
        patch(
            "products.signals.backend.scout_harness.runner.resolve_agent_runtime",
            return_value=pin,
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

    assert captured["context"].model == expected_model
    assert captured["context"].runtime_adapter == expected_runtime_adapter
    assert captured["context"].reasoning_effort == expected_reasoning_effort
    # The routed triple is also stamped on the bridge row's `metadata` (keys omitted when unset,
    # nothing at the top level on the default path) — the native API-side record of which model
    # served the run.
    bridge = await database_sync_to_async(SignalScoutRun.objects.get)(team=ateam)
    expected_metadata = {
        key: value
        for key, value in (
            ("model", expected_model),
            ("runtime_adapter", expected_runtime_adapter),
            ("reasoning_effort", expected_reasoning_effort),
        )
        if value is not None
    }
    stamped = bridge.metadata or {}
    routed = {key: value for key, value in stamped.items() if key in _ROUTED_MODEL_KEYS}
    assert routed == expected_metadata
    # Wiring guards for the two regions written outside `_create_run_row`'s routing triple:
    # the prompt build the run was given, and the finalize-time derived map. Neither can be
    # proven by a direct unit test of the function that computes it.
    assert stamped["harness_prompt_version"] == HARNESS_PROMPT_VERSION
    assert DERIVED_METADATA_KEY in stamped
    events = {c.kwargs["event"] for c in capture.call_args_list}
    assert events == {"signals_scout_run_started", "signals_scout_run_finished"}
    for call in capture.call_args_list:
        props = call.kwargs["properties"]
        if expected_model is None:
            assert "model" not in props
            assert "runtime_adapter" not in props
        else:
            assert props["model"] == expected_model
            assert props["runtime_adapter"] == expected_runtime_adapter


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
    # The prompt-shape fork reaches the lifecycle event too (this team has no knowledge base),
    # so an event-based A/B readout can segment on it without joining back to the run row.
    assert props["business_knowledge_maintained"] is False


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
        # A routed model must survive onto the failed event too — timeouts and crashes are
        # exactly the outcomes a model trial slices by.
        patch(
            "products.signals.backend.scout_harness.runner.resolve_scout_model",
            return_value=ScoutModel(model="@cf/zai-org/glm-5.2", runtime_adapter="claude"),
        ),
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
    assert props["model"] == "@cf/zai-org/glm-5.2"
    assert props["runtime_adapter"] == "claude"
    # Failure reason rides on the event so the failure rate is breakable down by cause
    # without digging into worker logs — the bulk of scout failures fail here, before the
    # process-task workflow's own task_run_failed event fires.
    assert props["error_type"] == "RuntimeError"
    assert props["error_message"] == "sandbox refused to start"


@contextmanager
def _stubbed_spawn_dependencies():
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
        yield


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_failure_streak_pauses_scout_once_and_a_success_resumes_it(ateam, aerrors_skill):
    TaskRun = apps.get_model("tasks", "TaskRun")
    # The wedge this exists for: a (team, skill) lane that can never succeed stays due every
    # tick, so it re-dispatches forever and takes a full-length sandbox lease each time to
    # produce nothing. Nothing else in the harness notices, so the breaker has to.
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam, "close-out")

    async def _run_once(*, failing: bool, capture, triggered_by: str = "schedule"):
        start = (
            AsyncMock(side_effect=RuntimeError("poll_for_turn: timed out after 900s"))
            if failing
            else _fake_start_invoking_hook(session, result)
        )
        with (
            patch("products.signals.backend.scout_harness.runner.MultiTurnSession.start", new=start),
            patch("products.signals.backend.scout_harness.runner.posthoganalytics.capture", new=capture),
            # Canonical-skill sync is disk + DB work unrelated to the breaker, and this test
            # calls the entrypoint once per run in the streak.
            patch("products.signals.backend.scout_harness.runner.sync_canonical_skills"),
            _stubbed_spawn_dependencies(),
        ):
            return await arun_signals_scout(
                team_id=ateam.id, skill_name="signals-scout-errors", triggered_by=triggered_by
            )

    def _paused_events(capture) -> list:
        return [c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_config_auto_paused"]

    async def _reload() -> SignalScoutConfig:
        return await database_sync_to_async(SignalScoutConfig.objects.get)(
            team=ateam, skill_name="signals-scout-errors"
        )

    capture = MagicMock()
    await _run_once(failing=True, capture=capture)
    config = await _reload()
    # The breaker scales with the lane's schedule, so the streak this run has to reach is
    # derived from the config rather than fixed.
    threshold = failure_streak_pause_threshold(_failure_streak_runs_in_window(config))

    # A failed manual "run now" is off-schedule evidence and must not advance the streak:
    # the threshold is sized on the schedule's cadence, so counting rapid manual retries
    # would let a burst of them pause a daily lane within minutes of a platform blip.
    await _run_once(failing=True, capture=capture, triggered_by="manual")
    config = await _reload()
    assert config.consecutive_failure_count == 1

    for _ in range(threshold - 2):
        await _run_once(failing=True, capture=capture)
    config = await _reload()
    assert config.consecutive_failure_count == threshold - 1
    assert config.status == SignalScoutConfig.Status.ACTIVE
    assert _paused_events(capture) == []

    await _run_once(failing=True, capture=capture)
    config = await _reload()
    assert config.consecutive_failure_count == threshold
    assert config.status == SignalScoutConfig.Status.PAUSED_BY_SYSTEM
    assert config.pause_reason == SignalScoutConfig.PauseReason.REPEATED_FAILURES
    assert config.enabled is False
    trip = _paused_events(capture)
    assert len(trip) == 1
    assert trip[0].kwargs["properties"]["consecutive_failure_count"] == threshold
    assert trip[0].kwargs["properties"]["failure_streak_threshold"] == threshold
    assert "timed out after 900s" in trip[0].kwargs["properties"]["auto_pause_reason"]

    # A failed probe leaves the lane paused but must not re-alert — otherwise the event stops
    # being a count of wedges and becomes a count of doomed runs again.
    await _run_once(failing=True, capture=capture)
    config = await _reload()
    assert config.status == SignalScoutConfig.Status.PAUSED_BY_SYSTEM
    assert len(_paused_events(capture)) == 1

    # A probe that gets through resumes the lane with a clean streak, so a lane whose cause
    # was fixed recovers without anyone having to un-pause it by hand.
    assert (await _run_once(failing=False, capture=capture)).status == TaskRun.Status.COMPLETED.value
    config = await _reload()
    assert config.consecutive_failure_count == 0
    assert config.status == SignalScoutConfig.Status.ACTIVE
    assert config.pause_reason is None
    assert config.enabled is True


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
@pytest.mark.parametrize(
    ("billing_limited", "daily_limited", "expected_skip_reason"),
    [
        (True, False, "quota_limited"),
        (False, True, "daily_report_limit"),
        (True, True, "quota_limited"),
    ],
)
async def test_activity_skips_run_attributed_to_the_limit_that_fired(
    ateam, billing_limited, daily_limited, expected_skip_reason
):
    fake_arun = AsyncMock()
    with (
        patch(
            "products.signals.backend.temporal.agentic.scout_scheduler.is_team_signals_quota_limited",
            return_value=billing_limited,
        ),
        patch(
            "products.signals.backend.temporal.agentic.scout_scheduler.daily_report_limit_gate",
            return_value=DailyReportLimitGate(limited=daily_limited, limit=2, reports_today=2),
        ),
        patch(
            "products.signals.backend.temporal.agentic.scout_scheduler.capture_signal_report_daily_limit_paused"
        ) as capture,
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
    assert output.skip_reason == expected_skip_reason
    # The capture event tracks its own gate: it fires whenever the daily limit binds, even when
    # the quota skip wins the single-status run counter.
    if daily_limited:
        assert capture.call_args.kwargs["stage"] == "scout_run"
    else:
        capture.assert_not_called()


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


_ROUTED_MODEL_KEYS = ("model", "runtime_adapter", "reasoning_effort")


class TestRunRowProvenanceStamps(BaseTest):
    # The three dimensions an eval or A/B has to hold constant. Each is unrecoverable after the
    # fact, so a regression that hardcodes one (rather than reading it off the loaded skill)
    # silently mislabels every run from then on instead of failing loudly.
    def _skill(self, *, allowed_tools: list[str], origin: str) -> LoadedSkill:
        return LoadedSkill(
            name="signals-scout-general",
            version=3,
            body="scout",
            description="",
            allowed_tools=allowed_tools,
            files=[],
            skill_id="skill-1",
            origin=origin,  # type: ignore[arg-type]
            authors=[],
        )

    @parameterized.expand(
        [
            # emit-only and edit-only are separate prompt builds, not one "report channel" —
            # `build_run_prompt` renders different follow-up, escalation, and action guidance for
            # each, so collapsing them to a boolean would pool runs given different instructions.
            ("emit_only_custom", ["emit_report"], "custom", "emit", "custom"),
            ("edit_only_custom", ["edit_report"], "custom", "edit", "custom"),
            ("both_tools_canonical", ["emit_report", "edit_report"], "canonical", "both", "canonical"),
            ("legacy_channel_canonical", ["emit_finding"], "canonical", "none", "canonical"),
        ]
    )
    def test_stamps_prompt_build_channel_and_origin(
        self,
        _name: str,
        allowed_tools: list[str],
        origin: str,
        expected_channel: str,
        expected_origin: str,
    ) -> None:
        config, _ = SignalScoutConfig.objects.get_or_create(team=self.team, skill_name="signals-scout-general")
        run = _create_run_row(
            run_id=uuid7(),
            task_run=_make_task_run(self.team),
            team=self.team,
            config=config,
            skill=self._skill(allowed_tools=allowed_tools, origin=origin),
        )
        stamped = run.metadata or {}
        assert stamped["harness_prompt_version"] == HARNESS_PROMPT_VERSION
        assert stamped["report_channel"] == expected_channel
        assert stamped["skill_origin"] == expected_origin
        # Always-present provenance key: absence would mean a run predating the field, so a False
        # default must still be stamped, not omitted.
        assert stamped["business_knowledge_maintained"] is False
        # The routing triple stays absent on the default-model path, so its keys can't be
        # confused with the always-present provenance keys.
        assert not any(key in stamped for key in _ROUTED_MODEL_KEYS)

    def test_stamps_business_knowledge_fork_when_maintained(self) -> None:
        # The section rides on every run and the flag/source state behind it can change, so the
        # resolved boolean is stamped write-once — an eval or A/B compares only runs given the
        # same prompt, and re-deriving it later would read the wrong (current) state.
        config, _ = SignalScoutConfig.objects.get_or_create(team=self.team, skill_name="signals-scout-general")
        run = _create_run_row(
            run_id=uuid7(),
            task_run=_make_task_run(self.team),
            team=self.team,
            config=config,
            skill=self._skill(allowed_tools=["emit_report"], origin="custom"),
            business_knowledge_maintained=True,
        )
        assert (run.metadata or {})["business_knowledge_maintained"] is True
