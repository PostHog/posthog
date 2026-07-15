from posthog.test.base import BaseTest

from parameterized import parameterized
from social_django.models import UserSocialAuth

from products.review_hog.backend.models import ReviewReport, ReviewUserSettings
from products.review_hog.backend.temporal.activities import _resolve_acting_user
from products.review_hog.backend.temporal.types import TRIGGER_LABEL, TRIGGER_MANUAL

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
        # No settings row → the resolve result carries the defaults (labeled reviews on, inbox
        # reviews off, should_fix), so the gates and publish behave as before this feature for
        # users who never opened the UI.
        result = _resolve_acting_user(self.team.id, "octocat", None)
        assert result.review_labeled_prs is True
        assert result.review_inbox_prs is False
        assert result.urgency_threshold == "should_fix"

    def test_settings_row_flows_into_the_result(self) -> None:
        # The user's saved settings must reach the workflow — if resolve stops loading any of them,
        # the gates and publish silently revert to defaults. review_inbox_prs is set to the OPPOSITE
        # of its dataclass default: dropping its one passthrough line would silently disable the
        # entire inbox trigger for every opted-in user with the whole suite still green.
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            review_labeled_prs=False,
            review_inbox_prs=True,
            urgency_threshold=ReviewUserSettings.UrgencyThreshold.MUST_FIX,
        )
        result = _resolve_acting_user(self.team.id, "octocat", None)
        assert result.review_labeled_prs is False
        assert result.review_inbox_prs is True
        assert result.urgency_threshold == "must_fix"

    def test_label_trigger_falls_back_to_the_run_user(self) -> None:
        # Unmapped author on a labeled PR → the run user the trigger already resolved, passed
        # through as default_user_id so acting and sandbox identity can never drift.
        result = _resolve_acting_user(
            self.team.id, "ghost", None, trigger_source=TRIGGER_LABEL, default_user_id=self.user.id
        )
        assert (result.acting_user_id, result.resolved_from) == (self.user.id, "default")

    def test_non_label_triggers_keep_the_author_only_contract(self) -> None:
        result = _resolve_acting_user(
            self.team.id, "ghost", None, trigger_source=TRIGGER_MANUAL, default_user_id=self.user.id
        )
        assert result.acting_user_id is None

    def test_labeled_opt_out_protects_authors_but_never_travels_with_a_borrowed_user(self) -> None:
        # self.user is both the mapped author (octocat) and the run-user fallback.
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, review_labeled_prs=False
        )
        # Acting as the author: their own opt-out applies and the workflow will skip.
        as_author = _resolve_acting_user(self.team.id, "octocat", None, trigger_source=TRIGGER_LABEL)
        assert (as_author.resolved_from, as_author.review_labeled_prs) == ("author", False)
        # Acting as the borrowed run user on someone else's PR: the same row must NOT kill the review.
        as_default = _resolve_acting_user(
            self.team.id, "ghost", None, trigger_source=TRIGGER_LABEL, default_user_id=self.user.id
        )
        assert (as_default.acting_user_id, as_default.resolved_from) == (self.user.id, "default")
        assert as_default.review_labeled_prs is True

    def test_resolve_stamps_the_acting_user_onto_the_report(self) -> None:
        # "Your recent reviews" filters on this stamp — if resolve stops writing it, the list goes empty.
        report = ReviewReport.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            repository="PostHog/posthog",
            pr_number=7,
            pr_url="https://github.com/PostHog/posthog/pull/7",
            head_branch="feat",
            base_branch="main",
        )
        _resolve_acting_user(self.team.id, "octocat", None, report_id=str(report.id))
        report.refresh_from_db()
        assert report.acting_user_id == self.user.id
