from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.error_tracking.backend.logic import default_per_issue_rate_limit, effective_per_issue_rate_limit


@override_settings(ERROR_TRACKING_DEFAULT_PER_ISSUE_RATE_LIMIT=10000)
class TestEffectivePerIssueRateLimit(SimpleTestCase):
    @parameterized.expand(
        [
            ("unset falls back to the default", None, 10000),
            ("zero opts out", 0, None),
            ("own value wins", 25, 25),
        ]
    )
    def test_resolves_stored_value(self, _name: str, stored: int | None, expected: int | None) -> None:
        self.assertEqual(effective_per_issue_rate_limit(stored), expected)

    @override_settings(ERROR_TRACKING_DEFAULT_PER_ISSUE_RATE_LIMIT=0)
    def test_fallback_can_be_switched_off_for_the_deployment(self) -> None:
        self.assertIsNone(default_per_issue_rate_limit())
        self.assertIsNone(effective_per_issue_rate_limit(None))
        self.assertEqual(effective_per_issue_rate_limit(25), 25)
