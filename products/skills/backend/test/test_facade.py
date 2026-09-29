from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team

from products.skills.backend.facade.api import get_skill_prompt
from products.skills.backend.models import LLMSkill, LLMSkillFile


class TestGetSkillPrompt(BaseTest):
    def _create_skill(
        self,
        *,
        name: str = "onboarding-account-audit",
        body: str = "# Account audit\n",
        version: int = 1,
        is_latest: bool = True,
        deleted: bool = False,
        team: Team | None = None,
    ) -> LLMSkill:
        return LLMSkill.objects.create(
            team=team or self.team,
            name=name,
            description="Test skill.",
            body=body,
            version=version,
            is_latest=is_latest,
            deleted=deleted,
            created_by=self.user,
        )

    def test_returns_only_the_requested_teams_skill(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        self._create_skill(body="# Other team\n", team=other_team)

        assert get_skill_prompt(team_id=self.team.id, skill_name="onboarding-account-audit") is None

    def test_returns_the_latest_active_version(self) -> None:
        self._create_skill(body="# Version one\n", version=1, is_latest=False)
        self._create_skill(body="# Version two\n", version=2)

        prompt = get_skill_prompt(team_id=self.team.id, skill_name="onboarding-account-audit")

        assert prompt is not None
        assert prompt.body == "# Version two\n"
        assert prompt.version == 2

    @parameterized.expand(
        [
            ("missing",),
            ("archived",),
            ("empty",),
        ]
    )
    def test_returns_none_for_unavailable_skill(self, state: str) -> None:
        if state == "archived":
            self._create_skill(deleted=True)
        elif state == "empty":
            self._create_skill(body="")

        assert get_skill_prompt(team_id=self.team.id, skill_name="onboarding-account-audit") is None

    def test_returns_none_when_skill_has_bundled_files(self) -> None:
        skill = self._create_skill()
        LLMSkillFile.objects.create(skill=skill, path="references/guide.md", content="# Guide\n")

        assert get_skill_prompt(team_id=self.team.id, skill_name="onboarding-account-audit") is None

    def test_returns_none_when_skill_body_exceeds_64_kb(self) -> None:
        self._create_skill(body="x" * (64 * 1024 + 1))

        assert get_skill_prompt(team_id=self.team.id, skill_name="onboarding-account-audit") is None
