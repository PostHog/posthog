from posthog.test.base import BaseTest

from products.ai_observability.backend.models.skills import LLMSkill
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.config_registry import register_missing_configs


class TestRegisterMissingConfigs(BaseTest):
    def _create_skill(self, name: str, metadata: dict | None = None) -> LLMSkill:
        return LLMSkill.objects.create(
            team=self.team,
            name=name,
            description="test scout",
            body="# body",
            metadata=metadata or {},
            is_latest=True,
        )

    def test_creates_config_with_model_default_interval(self) -> None:
        self._create_skill("signals-scout-plain")
        register_missing_configs(self.team.id)
        config = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-plain")
        assert config.run_interval_minutes == 60

    def test_creates_config_with_skill_declared_interval(self) -> None:
        self._create_skill("signals-scout-daily", metadata={"default_run_interval_minutes": 1440})
        register_missing_configs(self.team.id)
        config = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-daily")
        assert config.run_interval_minutes == 1440

    def test_invalid_declared_interval_falls_back_to_model_default(self) -> None:
        # Out-of-range / non-int values (hand-edited rows) must not error the coordinator tick.
        self._create_skill("signals-scout-bad", metadata={"default_run_interval_minutes": "daily"})
        self._create_skill("signals-scout-too-big", metadata={"default_run_interval_minutes": 99999})
        register_missing_configs(self.team.id)
        configs = SignalScoutConfig.objects.for_team(self.team.id)
        assert configs.get(skill_name="signals-scout-bad").run_interval_minutes == 60
        assert configs.get(skill_name="signals-scout-too-big").run_interval_minutes == 60

    def test_existing_config_interval_is_never_overwritten(self) -> None:
        self._create_skill("signals-scout-daily", metadata={"default_run_interval_minutes": 1440})
        SignalScoutConfig.objects.for_team(self.team.id).get_or_create(
            team_id=self.team.id, skill_name="signals-scout-daily", defaults={"run_interval_minutes": 30}
        )
        register_missing_configs(self.team.id)
        config = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name="signals-scout-daily")
        assert config.run_interval_minutes == 30
