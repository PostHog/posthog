from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.facade.api import scout_creation_available

TEAM_LIMITS = "products.signals.backend.scout_harness.team_limits"
CREATE_ACCESS = "products.signals.backend.scout_harness.create_access"


class TestScoutCreationAvailable(BaseTest):
    @parameterized.expand(
        [
            ("enrolled_team", lambda team_id: {"guaranteed_team_ids": [team_id]}, True),
            ("wildcard", lambda _team_id: {"guaranteed_team_ids": ["*"]}, True),
            ("skipped_team", lambda team_id: {"guaranteed_team_ids": ["*"], "skip_team_ids": [team_id]}, False),
            ("other_team_only", lambda team_id: {"guaranteed_team_ids": [team_id + 1000]}, False),
        ]
    )
    def test_follows_the_scout_enrollment_payload(self, _name, payload_for, expected: bool):
        with patch(f"{TEAM_LIMITS}._read_flag_payload", return_value=payload_for(self.team.id)):
            assert scout_creation_available(team=self.team, user=self.user) is expected

    def test_requires_skill_editor_access_like_the_create_endpoint(self):
        with (
            patch(f"{TEAM_LIMITS}._read_flag_payload", return_value={"guaranteed_team_ids": ["*"]}),
            patch(f"{CREATE_ACCESS}.UserAccessControl") as user_access_control,
        ):
            user_access_control.return_value.check_access_level_for_resource.return_value = False
            assert scout_creation_available(team=self.team, user=self.user) is False
