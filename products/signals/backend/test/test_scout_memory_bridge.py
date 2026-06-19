from contextlib import AbstractContextManager

from posthog.test.base import BaseTest

from posthog.models.scoping import team_scope

from products.agent_memory.backend.facade import api as memory_api
from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness import memory_bridge
from products.tasks.backend.models import Task, TaskRun


class _TeamScopedMixin:
    _cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        cm = team_scope(self.team.id)  # type: ignore[attr-defined]
        cm.__enter__()
        self._cm = cm

    def tearDown(self) -> None:
        if self._cm is not None:
            try:
                self._cm.__exit__(None, None, None)
            finally:
                self._cm = None
        super().tearDown()  # type: ignore[misc]


class TestScoutMemoryBridge(_TeamScopedMixin, BaseTest):
    async def test_render_run_memory_empty_returns_none(self) -> None:
        rendered = await memory_bridge.render_run_memory(team_id=self.team.id, skill_name="signals-scout-errors")
        assert rendered is None

    async def test_render_run_memory_includes_project_and_scratchpad(self) -> None:
        await memory_api.awrite_memory(
            team_id=self.team.id, path="project.md", content="Top-level project memory.", expected_version=None
        )
        await memory_api.awrite_memory(
            team_id=self.team.id,
            path=memory_bridge.scratchpad_path("signals-scout-errors"),
            content="My scout notes.",
            expected_version=None,
        )
        rendered = await memory_bridge.render_run_memory(team_id=self.team.id, skill_name="signals-scout-errors")
        assert rendered is not None
        assert "Top-level project memory." in rendered
        assert "My scout notes." in rendered
        assert "project.md" in rendered

    async def test_render_run_memory_scopes_scratchpad_to_skill(self) -> None:
        await memory_api.awrite_memory(
            team_id=self.team.id,
            path=memory_bridge.scratchpad_path("signals-scout-other"),
            content="Other scout's notes.",
            expected_version=None,
        )
        rendered = await memory_bridge.render_run_memory(team_id=self.team.id, skill_name="signals-scout-errors")
        # The errors scout must not see the other scout's scratchpad.
        assert rendered is None

    def test_mirror_scratchpad_to_shared_path_without_run(self) -> None:
        memory_bridge.mirror_scratchpad_to_memory(
            team_id=self.team.id, run_id=None, key="known-noise", content="Ignore the staging health check."
        )
        from asgiref.sync import async_to_sync

        memory_file = async_to_sync(memory_api.aread_memory)(team_id=self.team.id, path="scouts/scratchpad.md")
        assert "## known-noise" in memory_file.content
        assert "Ignore the staging health check." in memory_file.content

    def test_mirror_scratchpad_to_skill_path_with_run(self) -> None:
        task = Task.objects.create(
            team=self.team, title="t", description="", origin_product=Task.OriginProduct.SIGNALS_SCOUT
        )
        task_run = TaskRun.objects.create(task=task, team=self.team)
        run = SignalScoutRun.objects.create(
            team=self.team, skill_name="signals-scout-errors", skill_version=1, task_run=task_run
        )

        memory_bridge.mirror_scratchpad_to_memory(
            team_id=self.team.id, run_id=str(run.id), key="learning", content="The errors are mostly bots."
        )
        from asgiref.sync import async_to_sync

        memory_file = async_to_sync(memory_api.aread_memory)(
            team_id=self.team.id, path="scouts/signals-scout-errors/scratchpad.md"
        )
        assert "## learning" in memory_file.content
        assert "The errors are mostly bots." in memory_file.content
