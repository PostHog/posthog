from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.facade.api import scout_creation_available

TEAM_LIMITS = "products.signals.backend.scout_harness.team_limits"
CREATE_ACCESS = "products.signals.backend.scout_harness.create_access"
FACADE = "products.signals.backend.facade.api"


class TestScoutCreationAvailable(BaseTest):
    @parameterized.expand(
        [
            ("enrolled_team", lambda team_id: {"guaranteed_team_ids": [team_id]}, False, True),
            ("wildcard", lambda _team_id: {"guaranteed_team_ids": ["*"]}, False, True),
            ("skipped_team", lambda team_id: {"guaranteed_team_ids": ["*"], "skip_team_ids": [team_id]}, False, False),
            ("other_team_only", lambda team_id: {"guaranteed_team_ids": [team_id + 1000]}, False, False),
            ("child_environment_of_enrolled_project", lambda team_id: {"guaranteed_team_ids": [team_id]}, True, True),
        ]
    )
    def test_follows_the_scout_enrollment_payload(self, _name, payload_for, on_child_environment: bool, expected: bool):
        team_id = self.team.id
        if on_child_environment:
            team_id = Team.objects.create(organization=self.organization, parent_team=self.team, name="Environment").id
        with patch(f"{TEAM_LIMITS}._read_flag_payload", return_value=payload_for(self.team.id)):
            assert scout_creation_available(team_id=team_id, user_id=self.user.id) is expected

    def test_requires_skill_editor_access_like_the_create_endpoint(self):
        with (
            patch(f"{TEAM_LIMITS}._read_flag_payload", return_value={"guaranteed_team_ids": ["*"]}),
            patch(f"{CREATE_ACCESS}.UserAccessControl") as user_access_control,
        ):
            user_access_control.return_value.check_access_level_for_resource.return_value = False
            assert scout_creation_available(team_id=self.team.id, user_id=self.user.id) is False

    def test_requires_access_to_the_requested_project(self):
        with (
            patch(f"{TEAM_LIMITS}._read_flag_payload", return_value={"guaranteed_team_ids": ["*"]}),
            patch(f"{FACADE}.UserAccessControl") as user_access_control,
        ):
            user_access_control.return_value.has_project_access = False
            assert scout_creation_available(team_id=self.team.id, user_id=self.user.id) is False
        assert user_access_control.call_args.kwargs["team"].id == self.team.id
