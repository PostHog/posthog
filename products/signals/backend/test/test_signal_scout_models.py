from contextlib import AbstractContextManager
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError
from django.utils import timezone

from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun, SignalScratchpad


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
            shadow_mode=False,
            enabled_skill_names=["signals-scout-errors", "signals-scout-llm"],
            limit_overrides={"max_runtime_s": 900},
            created_by=self.user,
        )

        loaded = SignalScoutConfig.objects.get(pk=config.pk)
        assert loaded.team_id == self.team.id
        assert loaded.enabled is True
        assert loaded.shadow_mode is False
        assert loaded.enabled_skill_names == ["signals-scout-errors", "signals-scout-llm"]
        assert loaded.limit_overrides == {"max_runtime_s": 900}
        assert loaded.created_by_id == self.user.id

    def test_signal_scout_config_defaults(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team)
        loaded = SignalScoutConfig.objects.get(pk=config.pk)
        # Defaults: disabled, shadow on, no skill narrowing, empty overrides.
        assert loaded.enabled is False
        assert loaded.shadow_mode is True
        assert loaded.enabled_skill_names is None
        assert loaded.limit_overrides == {}

    def test_signal_scout_config_one_per_team(self) -> None:
        SignalScoutConfig.objects.create(team=self.team)
        with pytest.raises(IntegrityError):
            SignalScoutConfig.objects.create(team=self.team)

    def test_signal_scout_run_round_trip(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, enabled=True)
        run = SignalScoutRun.objects.create(
            team=self.team,
            scout_config=config,
            skill_name="signals-scout-errors",
            skill_version=3,
            status=SignalScoutRun.Status.RUNNING,
            summary="Looked at 4 issues, surfaced 1 finding.",
            findings=[{"finding_id": "f1", "severity": "P2"}],
            hypotheses_considered=[{"text": "spike on /checkout", "pursued": True}],
            run_metrics={"runtime_s": 380, "findings": 1},
        )

        loaded = SignalScoutRun.objects.get(pk=run.pk)
        assert loaded.team_id == self.team.id
        assert loaded.scout_config_id == config.id
        assert loaded.skill_name == "signals-scout-errors"
        assert loaded.skill_version == 3
        assert loaded.status == SignalScoutRun.Status.RUNNING
        assert loaded.findings == [{"finding_id": "f1", "severity": "P2"}]
        assert loaded.hypotheses_considered == [{"text": "spike on /checkout", "pursued": True}]
        assert loaded.run_metrics == {"runtime_s": 380, "findings": 1}
        assert loaded.started_at is not None  # auto_now_add
        assert loaded.completed_at is None

    def test_signal_scout_run_survives_config_deletion(self) -> None:
        # SET_NULL on scout_config: deleting the config row keeps run history intact for audit.
        config = SignalScoutConfig.objects.create(team=self.team)
        run = SignalScoutRun.objects.create(
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
            team=self.team,
            skill_name="signals-scout-errors",
            skill_version=1,
        )
        scratchpad = SignalScratchpad.objects.create(
            team=self.team,
            key="known-flaky/checkout-error",
            content="The /checkout 500s on Mondays during the partner cron — not actionable.",
            authority=SignalScratchpad.Authority.SCOUT_INFERENCE,
            scope=SignalScratchpad.Scope.TEAM,
            tags=["error_tracking", "known-flaky"],
            created_by_run=run,
            expires_at=timezone.now() + timedelta(days=7),
        )

        loaded = SignalScratchpad.objects.get(pk=scratchpad.pk)
        assert loaded.team_id == self.team.id
        assert loaded.key == "known-flaky/checkout-error"
        assert loaded.authority == SignalScratchpad.Authority.SCOUT_INFERENCE
        assert loaded.scope == SignalScratchpad.Scope.TEAM
        assert loaded.tags == ["error_tracking", "known-flaky"]
        assert loaded.created_by_run_id == run.id
        assert loaded.expires_at is not None

    def test_signal_scratchpad_defaults_to_run_scope(self) -> None:
        # `scope` defaults to RUN — ephemeral working notes, not durable steering.
        sp = SignalScratchpad.objects.create(team=self.team, key="cheap-note", content="something")
        loaded = SignalScratchpad.objects.get(pk=sp.pk)
        assert loaded.scope == SignalScratchpad.Scope.RUN

    def test_signal_scratchpad_unique_per_team_key(self) -> None:
        SignalScratchpad.objects.create(team=self.team, key="dup", content="first")
        with pytest.raises(IntegrityError):
            SignalScratchpad.objects.create(team=self.team, key="dup", content="second")
