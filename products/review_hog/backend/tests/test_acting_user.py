from posthog.test.base import BaseTest

from parameterized import parameterized
from social_django.models import UserSocialAuth

from products.review_hog.backend.models import ReviewUserSettings
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
        assert result.acting_user_id == (self.user.id if expected == _SELF else expected)

    def test_settings_default_when_user_has_no_row(self) -> None:
        # No settings row → the resolve result carries the defaults (labeled reviews on, should_fix),
        # so the gate and publish behave as before this feature for users who never opened the UI.
        result = _resolve_acting_user(self.team.id, "octocat", None)
        assert result.review_labeled_prs is True
        assert result.urgency_threshold == "should_fix"

    def test_settings_row_flows_into_the_result(self) -> None:
        # The author's saved opt-out + threshold must reach the workflow — if resolve stops loading
        # them, the label gate and publish silently revert to defaults.
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            review_labeled_prs=False,
            urgency_threshold=ReviewUserSettings.UrgencyThreshold.MUST_FIX,
        )
        result = _resolve_acting_user(self.team.id, "octocat", None)
        assert result.review_labeled_prs is False
        assert result.urgency_threshold == "must_fix"
