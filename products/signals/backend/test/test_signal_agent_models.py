from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError
from django.utils import timezone

from products.signals.backend.models import SignalAgentConfig, SignalAgentRun, SignalMemory


class TestSignalAgentModels(BaseTest):
    def test_signal_agent_config_round_trip(self) -> None:
        config = SignalAgentConfig.objects.create(
            team=self.team,
            enabled=True,
            shadow_mode=False,
            enabled_skill_names=["signals-agent-errors", "signals-agent-llm"],
            limit_overrides={"max_runtime_s": 900},
            created_by=self.user,
        )

        loaded = SignalAgentConfig.objects.get(pk=config.pk)
        assert loaded.team_id == self.team.id
        assert loaded.enabled is True
        assert loaded.shadow_mode is False
        assert loaded.enabled_skill_names == ["signals-agent-errors", "signals-agent-llm"]
        assert loaded.limit_overrides == {"max_runtime_s": 900}
        assert loaded.created_by_id == self.user.id

    def test_signal_agent_config_defaults(self) -> None:
        config = SignalAgentConfig.objects.create(team=self.team)
        loaded = SignalAgentConfig.objects.get(pk=config.pk)
        # Defaults: disabled, shadow on, no skill narrowing, empty overrides.
        assert loaded.enabled is False
        assert loaded.shadow_mode is True
        assert loaded.enabled_skill_names is None
        assert loaded.limit_overrides == {}

    def test_signal_agent_config_one_per_team(self) -> None:
        SignalAgentConfig.objects.create(team=self.team)
        with pytest.raises(IntegrityError):
            SignalAgentConfig.objects.create(team=self.team)

    def test_signal_agent_run_round_trip(self) -> None:
        config = SignalAgentConfig.objects.create(team=self.team, enabled=True)
        run = SignalAgentRun.objects.create(
            team=self.team,
            agent_config=config,
            skill_name="signals-agent-errors",
            skill_version=3,
            status=SignalAgentRun.Status.RUNNING,
            summary="Looked at 4 issues, surfaced 1 finding.",
            findings=[{"finding_id": "f1", "severity": "P2"}],
            hypotheses_considered=[{"text": "spike on /checkout", "pursued": True}],
            run_metrics={"runtime_s": 380, "findings": 1},
        )

        loaded = SignalAgentRun.objects.get(pk=run.pk)
        assert loaded.team_id == self.team.id
        assert loaded.agent_config_id == config.id
        assert loaded.skill_name == "signals-agent-errors"
        assert loaded.skill_version == 3
        assert loaded.status == SignalAgentRun.Status.RUNNING
        assert loaded.findings == [{"finding_id": "f1", "severity": "P2"}]
        assert loaded.hypotheses_considered == [{"text": "spike on /checkout", "pursued": True}]
        assert loaded.run_metrics == {"runtime_s": 380, "findings": 1}
        assert loaded.started_at is not None  # auto_now_add
        assert loaded.completed_at is None

    def test_signal_agent_run_survives_config_deletion(self) -> None:
        # SET_NULL on agent_config: deleting the config row keeps run history intact for audit.
        config = SignalAgentConfig.objects.create(team=self.team)
        run = SignalAgentRun.objects.create(
            team=self.team,
            agent_config=config,
            skill_name="signals-agent-errors",
            skill_version=1,
        )
        config.delete()
        loaded = SignalAgentRun.objects.get(pk=run.pk)
        assert loaded.agent_config_id is None
        assert loaded.team_id == self.team.id

    def test_signal_memory_round_trip(self) -> None:
        run = SignalAgentRun.objects.create(
            team=self.team,
            skill_name="signals-agent-errors",
            skill_version=1,
        )
        memory = SignalMemory.objects.create(
            team=self.team,
            key="known-flaky/checkout-error",
            content="The /checkout 500s on Mondays during the partner cron — not actionable.",
            authority=SignalMemory.Authority.AGENT_INFERENCE,
            tags=["error_tracking", "known-flaky"],
            created_by_run=run,
            expires_at=timezone.now() + timedelta(days=7),
        )

        loaded = SignalMemory.objects.get(pk=memory.pk)
        assert loaded.team_id == self.team.id
        assert loaded.key == "known-flaky/checkout-error"
        assert loaded.authority == SignalMemory.Authority.AGENT_INFERENCE
        assert loaded.tags == ["error_tracking", "known-flaky"]
        assert loaded.created_by_run_id == run.id
        assert loaded.expires_at is not None

    def test_signal_memory_unique_per_team_key(self) -> None:
        SignalMemory.objects.create(team=self.team, key="dup", content="first")
        with pytest.raises(IntegrityError):
            SignalMemory.objects.create(team=self.team, key="dup", content="second")
