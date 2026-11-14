from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.run_per_wake import starts_new_run_per_wake

PAYLOAD = "products.tasks.backend.run_per_wake.posthoganalytics.get_feature_flag_payload"


class TestStartsNewRunPerWake(TestCase):
    def setUp(self) -> None:
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")

    @parameterized.expand(
        [
            ("dict_payload", "user", {"user": "on"}, True),
            ("json_payload", "user", '{"user": "on"}', True),
            ("switched_off", "user", {"user": "off"}, False),
            ("other_profile_only", "user", {"slack": "on"}, False),
            ("unknown_value", "user", {"user": "yes"}, False),
            ("no_payload", "user", None, False),
            ("task_without_a_profile", None, {"user": "on"}, False),
        ]
    )
    def test_only_a_profile_switched_on_starts_a_new_run(
        self, _name: str, profile: str | None, payload: object, expected: bool
    ) -> None:
        with patch(PAYLOAD, return_value=payload):
            self.assertIs(starts_new_run_per_wake(profile, self.team.id), expected)

    def test_a_failed_flag_lookup_keeps_the_old_resume(self) -> None:
        with patch(PAYLOAD, side_effect=RuntimeError("flags unavailable")):
            self.assertIs(starts_new_run_per_wake("user", self.team.id), False)
