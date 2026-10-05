from posthog.test.base import BaseTest

from parameterized import parameterized

from products.signals.backend.facade.api import enroll_scout_for_source, withdraw_scout_for_source
from products.signals.backend.models import SignalScoutConfig
from products.skills.backend.models.skills import LLMSkill

SKILL = "signals-scout-workflow-ideas"


class TestScoutForSource(BaseTest):
    def _enroll(self) -> bool:
        return enroll_scout_for_source(
            team=self.team,
            skill_name=SKILL,
            source_product="workflows",
            source_id="cohort:1",
            run_interval_minutes=4320,
            model="gpt-6-luna",
        )

    def test_enroll_seeds_only_the_one_scout_with_a_config_its_source_owns(self) -> None:
        assert self._enroll() is True
        assert self._enroll() is True

        skills = set(LLMSkill.objects.filter(team=self.team, deleted=False).values_list("name", flat=True))
        assert skills == {SKILL}
        config = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name=SKILL)
        assert (config.enabled, config.source_product, config.source_id, config.run_interval_minutes, config.model) == (
            True,
            "workflows",
            "cohort:1",
            4320,
            "gpt-6-luna",
        )
        assert config.structured_output_schema is not None

    @parameterized.expand([("ai processing not approved", "consent"), ("config a person made", "existing")])
    def test_enroll_refuses(self, _name: str, case: str) -> None:
        if case == "consent":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        else:
            SignalScoutConfig.objects.create(team=self.team, skill_name=SKILL, enabled=False)

        assert self._enroll() is False
        assert not SignalScoutConfig.objects.for_team(self.team.id).filter(source_product="workflows").exists()

    def test_withdraw_removes_only_the_config_its_source_owns(self) -> None:
        SignalScoutConfig.objects.create(team=self.team, skill_name=SKILL, enabled=True)

        assert withdraw_scout_for_source(team_id=self.team.id, skill_name=SKILL, source_product="workflows") is False
        assert SignalScoutConfig.objects.for_team(self.team.id).filter(skill_name=SKILL).exists()

        SignalScoutConfig.objects.for_team(self.team.id).filter(skill_name=SKILL).delete()
        self._enroll()
        assert withdraw_scout_for_source(team_id=self.team.id, skill_name=SKILL, source_product="workflows") is True
        assert not SignalScoutConfig.objects.for_team(self.team.id).filter(skill_name=SKILL).exists()
