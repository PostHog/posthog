from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

import pytest
from posthog.test.base import BaseTest

from django.apps import apps
from django.db import IntegrityError
from django.utils import timezone

from posthog.models import Organization, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun, SignalScratchpad

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


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
            skill_name="signals-scout-errors",
            enabled=True,
            emit=True,
            run_interval_minutes=60,
            created_by=self.user,
            enabled_by=self.user,
        )

        loaded = SignalScoutConfig.objects.get(pk=config.pk)
        assert loaded.team_id == self.team.id
        assert loaded.skill_name == "signals-scout-errors"
        assert loaded.enabled is True
        assert loaded.emit is True
        assert loaded.run_interval_minutes == 60
        assert loaded.created_by_id == self.user.id
        assert loaded.enabled_by_id == self.user.id

    def test_signal_scout_config_defaults(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        loaded = SignalScoutConfig.objects.get(pk=config.pk)
        # Auto-created scouts run every 24 hours and emit on by default (live from the first tick).
        assert loaded.enabled is True
        assert loaded.emit is True
        assert loaded.run_interval_minutes == 1440
        assert loaded.last_run_at is None

    def test_signal_scout_config_one_per_team_skill(self) -> None:
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        with pytest.raises(IntegrityError):
            SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")

    def test_signal_scout_config_multiple_skills_per_team(self) -> None:
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-bar")
        assert SignalScoutConfig.objects.filter(team=self.team).count() == 2

    def test_enabling_scout_logs_activity(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo", enabled=False)
        config.enabled = True
        config.save()
        assert ActivityLog.objects.filter(
            scope="SignalScoutConfig", item_id=str(config.id), activity="updated"
        ).exists()

    def test_last_run_at_update_skips_activity_log(self) -> None:
        # The coordinator stamps last_run_at via .update() every tick; that hot write must
        # not flood the audit log.
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        ActivityLog.objects.filter(scope="SignalScoutConfig").delete()
        SignalScoutConfig.all_teams.filter(pk=config.pk).update(last_run_at=timezone.now())
        assert not ActivityLog.objects.filter(scope="SignalScoutConfig", item_id=str(config.id)).exists()

    def _make_task_run(self) -> "TaskRun":
        """Minimal Task + TaskRun pair scoped to this test's team."""
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team,
            title="scout run",
            description="scout run",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )
        return TaskRun.objects.create(task=task, team=self.team)

    def test_signal_scout_run_round_trip(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-errors", enabled=True)
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
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-errors")
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


@pytest.mark.django_db
def test_scout_config_update_without_team_scope_logs_activity() -> None:
    # Django admin / coordinator / shell edits run with no team context. The activity-logging
    # prior-state lookup must use the unscoped manager, not the fail-closed `objects`, or the
    # save raises TeamScopeError before the change is persisted. Function-style (not BaseTest)
    # so the conftest's auto team_scope does not apply.
    org = Organization.objects.create(name="ScoutScopeTestOrg")
    team = Team.objects.create(organization=org, name="ScoutScopeTestTeam")
    config = SignalScoutConfig.all_teams.create(team=team, skill_name="signals-scout-x", emit=False)

    config.emit = True
    config.save()

    config.refresh_from_db()
    assert config.emit is True
    assert ActivityLog.objects.filter(scope="SignalScoutConfig", item_id=str(config.id), activity="updated").exists()
