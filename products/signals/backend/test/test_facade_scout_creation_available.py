from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.facade.api import scout_creation_available

TEAM_LIMITS = "products.signals.backend.scout_harness.team_limits"


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
