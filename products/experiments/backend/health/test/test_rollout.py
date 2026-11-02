from contextlib import AbstractContextManager

from posthog.test.base import BaseTest
from unittest.mock import patch

import posthoganalytics
from parameterized import parameterized
from posthoganalytics import Posthog

from products.experiments.backend.health.rollout import HEALTH_FINDINGS_FLAG, shows_health_findings

# The shape of a definition from /api/feature_flag/local_evaluation, with the rollout by email domain.
HEALTH_FINDINGS_DEFINITION = {
    "id": 1,
    "key": HEALTH_FINDINGS_FLAG,
    "active": True,
    "deleted": False,
    "ensure_experience_continuity": False,
    "filters": {
        "groups": [
            {
                "properties": [{"key": "email", "type": "person", "value": "@example.com", "operator": "icontains"}],
                "rollout_percentage": 100,
            }
        ],
        "multivariate": None,
    },
}


class TestShowsHealthFindings(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client_with_definition = Posthog("phc_test", personal_api_key="phx_test", sync_mode=True)
        self.client_with_definition.feature_flags = [HEALTH_FINDINGS_DEFINITION]
        self.client_with_definition.group_type_mapping = {"0": "organization", "1": "project"}

    @parameterized.expand(
        [
            ("email_in_the_rollout", "someone@example.com", False, True),
            ("email_outside_the_rollout", "someone@example.net", False, False),
            ("anonymized", "someone@example.com", True, False),
        ]
    )
    def test_evaluates_the_apps_flag_from_the_users_identity(
        self, _name: str, email: str, anonymize_data: bool, expected: bool
    ) -> None:
        self.user.email = email
        self.user.anonymize_data = anonymize_data

        with self._client_with_definition():
            self.assertEqual(shows_health_findings(self.user, self.team), expected)

    def test_shows_nothing_to_a_user_without_a_distinct_id(self) -> None:
        self.user.email = "someone@example.com"
        self.user.distinct_id = None

        with self._client_with_definition():
            self.assertFalse(shows_health_findings(self.user, self.team))

    def _client_with_definition(self) -> AbstractContextManager[None]:
        # The module functions apply the module settings to the default client on every call, and the test settings
        # disable it.
        return patch.multiple(posthoganalytics, default_client=self.client_with_definition, disabled=False)
