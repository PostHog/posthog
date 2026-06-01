from contextlib import AbstractContextManager

import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError

from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun, SignalScratchpad
from products.tasks.backend.models import Task, TaskRun


class _ScoutTeamScopedTestMixin:
    """Wraps setUp/tearDown with team_scope so test-body queries to the
    TeamScopedRootMixin-backed scout models find a team context."""

    _team_scope_cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        cm = team_scope(self.team.id)  # type: ignore[attr-defined]
        cm.__enter__()
        self._team_scope_cm = cm

    def tearDown(self) -> None:
        if self._team_scope_cm is not None:
            try:
                self._team_scope_cm.__exit__(None, None, None)
            finally:
                self._team_scope_cm = None
        super().tearDown()  # type: ignore[misc]


class TestSignalScoutModels(_ScoutTeamScopedTestMixin, BaseTest):
    def test_signal_scout_config_round_trip(self) -> None:
        config = SignalScoutConfig.objects.create(
            team=self.team,
            enabled=True,
            enabled_skill_names=["signals-scout-errors", "signals-scout-llm"],
            created_by=self.user,
        )

        loaded = SignalScoutConfig.objects.get(pk=config.pk)
        assert loaded.team_id == self.team.id
        assert loaded.enabled is True
        assert loaded.enabled_skill_names == ["signals-scout-errors", "signals-scout-llm"]
        assert loaded.created_by_id == self.user.id

    def test_signal_scout_config_defaults(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team)
        loaded = SignalScoutConfig.objects.get(pk=config.pk)
        # Defaults: disabled, no skill narrowing.
        assert loaded.enabled is False
        assert loaded.enabled_skill_names is None

    def test_signal_scout_config_one_per_team(self) -> None:
        SignalScoutConfig.objects.create(team=self.team)
        with pytest.raises(IntegrityError):
            SignalScoutConfig.objects.create(team=self.team)

    def _make_task_run(self) -> TaskRun:
        """Minimal Task + TaskRun pair scoped to this test's team."""
        task = Task.objects.create(
            team=self.team,
            title="scout run",
            description="scout run",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )
        return TaskRun.objects.create(task=task, team=self.team)

    def test_signal_scout_run_round_trip(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, enabled=True)
        task_run = self._make_task_run()
        run = SignalScoutRun.objects.create(
            task_run=task_run,
            team=self.team,
            scout_config=config,
            skill_name="signals-scout-errors",
            skill_version=3,
        )

        loaded = SignalScoutRun.objects.get(pk=run.pk)
        assert loaded.task_run_id == task_run.id
        assert loaded.team_id == self.team.id
        assert loaded.scout_config_id == config.id
        assert loaded.skill_name == "signals-scout-errors"
        assert loaded.skill_version == 3
        assert loaded.created_at is not None  # auto_now_add

    def test_signal_scout_run_one_per_task_run(self) -> None:
        # OneToOneField: a given TaskRun can only have a single scout-bridge row.
        task_run = self._make_task_run()
        SignalScoutRun.objects.create(
            task_run=task_run, team=self.team, skill_name="signals-scout-errors", skill_version=1
        )
        with pytest.raises(IntegrityError):
            SignalScoutRun.objects.create(
                task_run=task_run, team=self.team, skill_name="signals-scout-llm", skill_version=1
            )

    def test_signal_scout_run_survives_config_deletion(self) -> None:
        # SET_NULL on scout_config: deleting the config row keeps run history intact for audit.
        config = SignalScoutConfig.objects.create(team=self.team)
        task_run = self._make_task_run()
        run = SignalScoutRun.objects.create(
            task_run=task_run,
            team=self.team,
            scout_config=config,
            skill_name="signals-scout-errors",
            skill_version=1,
        )
        config.delete()
        loaded = SignalScoutRun.objects.get(pk=run.pk)
        assert loaded.scout_config_id is None
        assert loaded.team_id == self.team.id

    def test_signal_scratchpad_round_trip(self) -> None:
        run = SignalScoutRun.objects.create(
            task_run=self._make_task_run(),
            team=self.team,
            skill_name="signals-scout-errors",
            skill_version=1,
        )
        scratchpad = SignalScratchpad.objects.create(
            team=self.team,
            key="known-flaky/checkout-error",
            content="The /checkout 500s on Mondays during the partner cron — not actionable.",
            created_by_run=run,
        )

        loaded = SignalScratchpad.objects.get(pk=scratchpad.pk)
        assert loaded.team_id == self.team.id
        assert loaded.key == "known-flaky/checkout-error"
        assert loaded.created_by_run_id == run.id

    def test_signal_scratchpad_unique_per_team_key(self) -> None:
        SignalScratchpad.objects.create(team=self.team, key="dup", content="first")
        with pytest.raises(IntegrityError):
            SignalScratchpad.objects.create(team=self.team, key="dup", content="second")
