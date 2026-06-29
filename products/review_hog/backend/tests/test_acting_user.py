from posthog.test.base import BaseTest

from parameterized import parameterized
from social_django.models import UserSocialAuth

from products.review_hog.backend.temporal.activities import _resolve_acting_user

_SELF = "SELF"


class TestResolveActingUser(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-1", extra_data={"login": "OctoCat"})

    @parameterized.expand(
        [
            # An explicit override (CLI/eval) wins regardless of the author — resolution is skipped.
            ("override_wins", "nobody", 4321, 4321),
            # The PR author maps to the org user, case-insensitively.
            ("maps_author", "octocat", None, _SELF),
            ("maps_author_mixed_case", "OCTOCAT", None, _SELF),
            # No PostHog org user for the author (or no author) → None, so the parent skips the review.
            ("unmapped_author", "ghost", None, None),
            ("empty_author", "", None, None),
        ]
    )
    def test_resolve_acting_user(self, _name: str, author: str, override: int | None, expected: object) -> None:
        result = _resolve_acting_user(self.team.id, author, override)
        assert result == (self.user.id if expected == _SELF else expected)
