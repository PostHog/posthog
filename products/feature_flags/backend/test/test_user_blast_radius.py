from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.feature_flags.backend.user_blast_radius import get_user_blast_radius, get_user_blast_radius_persons

FLAG_CONDITION = {
    "properties": [
        {
            "key": "my-other-flag",
            "type": "flag",
            "value": "true",
            "operator": "exact",
        }
    ],
    "rollout_percentage": 100,
}


class TestUserBlastRadiusFlagGuard(BaseTest):
    @parameterized.expand(
        [
            ("blast_radius", get_user_blast_radius),
            ("blast_radius_persons", get_user_blast_radius_persons),
        ]
    )
    def test_flag_condition_raises_validation_error(self, _name, func):
        with self.assertRaises(ValidationError) as ctx:
            func(self.team, FLAG_CONDITION)

        self.assertIn("Feature flag conditions are not supported", str(ctx.exception))

    @parameterized.expand(
        [
            ("blast_radius", get_user_blast_radius),
            ("blast_radius_persons", get_user_blast_radius_persons),
        ]
    )
    def test_flag_condition_mixed_with_person_property_raises(self, _name, func):
        condition = {
            "properties": [
                {"key": "email", "type": "person", "value": "a@b.com", "operator": "exact"},
                {"key": "my-other-flag", "type": "flag", "value": "true", "operator": "exact"},
            ],
            "rollout_percentage": 100,
        }

        with self.assertRaises(ValidationError):
            func(self.team, condition)
