from dataclasses import replace
from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team.team import Team

from products.signals.backend.agent_skills import SkillNotFoundError
from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.research_skills import ResearchSkillBinding, ResearchSkills, ResearchSource
from products.signals.backend.temporal.types import SignalData
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile


class TestResearchSkills(BaseTest):
    def signal(self, product: str, source_type: str) -> SignalData:
        return SignalData(
            signal_id=f"{product}-{source_type}",
            content="An operation failed.",
            source_product=product,
            source_type=source_type,
            source_id="example-1",
            weight=1,
            timestamp=datetime.now(UTC),
        )

    def test_grouped_sources_keep_separate_skills_and_default_research(self) -> None:
        first = LLMSkill.objects.create(team=self.team, name="review-defects", body="Check the reproduction.")
        LLMSkillFile.objects.create(skill=first, path="references/checks.md", content="Check the failing operation.")
        LLMSkill.objects.create(team=self.team, name="review-feedback", body="Check the reported impact.")
        for product, name in [("github", "review-defects"), ("linear", "review-feedback")]:
            SignalSourceConfig.objects.create(
                team=self.team, source_product=product, source_type="issue", config={"research_skill": name}
            )
        signals = [
            self.signal("github", "issue"),
            self.signal("linear", "issue"),
            self.signal("conversations", "ticket"),
        ]
        skills = ResearchSkills.load(self.team.id, signals)
        assert "Check the reproduction." in skills.for_signal(signals[0])
        assert "references/checks.md" in skills.for_signal(signals[0])
        assert "review-feedback" not in skills.for_signal(signals[0])
        assert "Check the reported impact." in skills.for_signal(signals[1])
        assert "No custom skill applies" in skills.for_signal(signals[2])
        assert ResearchSkills.load(self.team.id, [signals[2]]).for_signal(signals[2]) == ""

    def test_retry_keeps_the_selected_version_after_source_and_skill_changes(self) -> None:
        first = LLMSkill.objects.create(team=self.team, name="review-defects", body="Original instructions.")
        config = SignalSourceConfig.objects.create(
            team=self.team, source_product="github", source_type="issue", config={"research_skill": first.name}
        )
        signal = self.signal("github", "issue")
        bindings = ResearchSkills.load(self.team.id, [signal]).bindings(self.team.id)
        first.is_latest = False
        first.save(update_fields=["is_latest"])
        LLMSkill.objects.create(team=self.team, name=first.name, version=2, body="New instructions.")
        config.config = {}
        config.save(update_fields=["config"])
        retry = ResearchSkills.from_bindings(self.team.id, bindings)
        assert "Original instructions." in retry.for_signal(signal)
        assert "New instructions." not in retry.for_signal(signal)
        assert not ResearchSkills.load(self.team.id, [signal]).by_source

    def test_binding_cannot_read_another_project(self) -> None:
        other = Team.objects.create(organization=self.organization)
        LLMSkill.objects.create(team=other, name="private-skill", body="Private instructions.")
        binding = ResearchSkillBinding(
            source=ResearchSource(product="github", type="issue"), team_id=other.id, name="private-skill", version=1
        )
        with pytest.raises(ValueError, match="another project"):
            ResearchSkills.from_bindings(self.team.id, [binding])
        with pytest.raises(SkillNotFoundError):
            ResearchSkills.from_bindings(self.team.id, [replace(binding, team_id=self.team.id)])

    @parameterized.expand([("session_problem",), ("session_analysis_cluster",)])
    def test_session_replay_uses_its_source_config_alias(self, source_type: str) -> None:
        LLMSkill.objects.create(team=self.team, name="review-replay", body="Inspect the recording.")
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            config={"research_skill": "review-replay"},
        )
        signal = self.signal("session_replay", source_type)
        assert "Inspect the recording." in ResearchSkills.load(self.team.id, [signal]).for_signal(signal)

    def test_scout_skill_uses_canonical_project_and_other_sources_use_environment(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team)
        LLMSkill.objects.create(team=self.team, name="parent-skill", body="Parent instructions.")
        LLMSkill.objects.create(team=child, name="child-skill", body="Child instructions.")
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="signals_scout",
            source_type="cross_source_issue",
            config={"research_skill": "parent-skill"},
        )
        SignalSourceConfig.objects.create(
            team=child, source_product="github", source_type="issue", config={"research_skill": "child-skill"}
        )
        signals = [self.signal("signals_scout", "cross_source_issue"), self.signal("github", "issue")]
        skills = ResearchSkills.load(child.id, signals)
        bindings = skills.bindings(child.id)
        restored = ResearchSkills.from_bindings(child.id, bindings)
        assert "Parent instructions." in restored.for_signal(signals[0])
        assert "Child instructions." in restored.for_signal(signals[1])
