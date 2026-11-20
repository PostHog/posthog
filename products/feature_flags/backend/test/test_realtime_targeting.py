from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings

from parameterized import parameterized

from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.feature_flags.backend.realtime_targeting import is_realtime_cohort_flag_targeting_enabled


class TestRealtimeCohortFlagTargetingGate(BaseTest):
    @parameterized.expand(
        [
            ("serving_row", RealtimeCohortLevel.SERVING, False, False, True),
            ("processing_row", RealtimeCohortLevel.PROCESSING, False, True, False),
            # The env list holds load-test teams too, so the rollout flag still decides for a listed team.
            ("env_listed_flag_off", None, True, False, False),
            ("env_listed_flag_on", None, True, True, True),
            ("no_row", None, False, True, False),
        ]
    )
    def test_who_sees_realtime_cohorts(
        self, _name: str, level: RealtimeCohortLevel | None, env_listed: bool, flag_on: bool, expected: bool
    ) -> None:
        if level is not None:
            RealtimeCohortTeamAccess.objects.create(
                team=self.team, level=level, purpose=RealtimeCohortAccessPurpose.BETA
            )
        request = mock.Mock(user=self.user)

        with (
            override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=str(self.team.id) if env_listed else "none"),
            mock.patch(
                "products.feature_flags.backend.realtime_targeting.feature_enabled_or_false", return_value=flag_on
            ),
        ):
            assert is_realtime_cohort_flag_targeting_enabled(request, team=self.team) is expected
