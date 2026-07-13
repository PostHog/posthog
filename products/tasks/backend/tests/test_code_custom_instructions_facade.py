from typing import ClassVar

from django.test import TestCase

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.facade import api as facade
from products.tasks.backend.models import CODE_CUSTOM_INSTRUCTIONS_MAX_LENGTH, CodeCustomInstructions


class TestCodeCustomInstructionsFacade(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org")
        cls.team = Team.objects.create(organization=cls.org, name="Team")
        cls.user = User.objects.create(email="user@test.com", distinct_id="user")

    def test_get_seeds_empty_row(self):
        dto = facade.get_code_custom_instructions(self.team.id, self.user.id)
        assert dto.version == 1
        assert dto.content == ""
        assert CodeCustomInstructions.objects.for_team(self.team.id).filter(user=self.user).count() == 1

    def test_save_persists_and_bumps_version(self):
        seed = facade.get_code_custom_instructions(self.team.id, self.user.id)

        result = facade.save_code_custom_instructions(
            self.team.id, self.user.id, content="Prefer tabs.", expected_version=seed.version
        )

        assert result.outcome == facade.CODE_CUSTOM_INSTRUCTIONS_SAVED
        assert result.config.version == seed.version + 1
        assert result.config.content == "Prefer tabs."

    def test_stale_version_conflicts_without_writing(self):
        seed = facade.get_code_custom_instructions(self.team.id, self.user.id)
        facade.save_code_custom_instructions(self.team.id, self.user.id, content="first", expected_version=seed.version)

        result = facade.save_code_custom_instructions(
            self.team.id, self.user.id, content="second", expected_version=seed.version
        )

        assert result.outcome == facade.CODE_CUSTOM_INSTRUCTIONS_CONFLICT
        assert result.config.content == "first"

    def test_content_over_cap_is_invalid(self):
        seed = facade.get_code_custom_instructions(self.team.id, self.user.id)

        result = facade.save_code_custom_instructions(
            self.team.id,
            self.user.id,
            content="x" * (CODE_CUSTOM_INSTRUCTIONS_MAX_LENGTH + 1),
            expected_version=seed.version,
        )

        assert result.outcome == facade.CODE_CUSTOM_INSTRUCTIONS_INVALID
        assert result.config.content == ""

    def test_reset_clears_and_bumps_version(self):
        seed = facade.get_code_custom_instructions(self.team.id, self.user.id)
        facade.save_code_custom_instructions(
            self.team.id, self.user.id, content="something", expected_version=seed.version
        )

        dto = facade.reset_code_custom_instructions(self.team.id, self.user.id)

        assert dto.content == ""
        assert dto.version == seed.version + 2
