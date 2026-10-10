from posthog.test.base import BaseTest

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models.integration import Integration

from products.review_hog.backend.models import (
    ReviewInstallationClaim,
    ReviewProjectSettings,
    ReviewReport,
    ReviewRepository,
    ReviewUserSettings,
)
from products.review_hog.backend.temporal.activities import ResolveActingUserInput, _resolve_acting_user
from products.review_hog.backend.temporal.types import TRIGGER_AUTOMATIC, TRIGGER_LABEL, TRIGGER_MANUAL

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
        result = _resolve_acting_user(
            ResolveActingUserInput(team_id=self.team.id, author_login=author, override_user_id=override)
        )
        assert result.acting_user_id == (self.user.id if expected == _SELF else expected)

    def test_settings_default_when_user_has_no_row(self) -> None:
        # No settings row → the code defaults (inbox reviews off, consider, resolution off), so every
        # validated finding publishes and nothing writes to the PR for users who never opened the UI.
        result = _resolve_acting_user(
            ResolveActingUserInput(team_id=self.team.id, author_login="octocat", override_user_id=None)
        )
        assert result.review_labeled_prs is True
        assert result.review_inbox_prs is False
        assert result.urgency_threshold == "consider"
        assert result.resolve_comments is False
        assert result.review_authored_prs is False
        assert result.flash_reasoning_effort == "medium"

    def test_project_defaults_reach_authors_and_borrowed_runs(self) -> None:
        ReviewProjectSettings.objects.for_team(self.team.id).create(
            team=self.team, preferences={"urgency_threshold": "must_fix", "celebrate_clean_reviews": False}
        )
        as_author = _resolve_acting_user(
            ResolveActingUserInput(team_id=self.team.id, author_login="octocat", override_user_id=None)
        )
        as_default = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id,
                author_login="ghost",
                override_user_id=None,
                trigger_source=TRIGGER_LABEL,
                default_user_id=self.user.id,
            )
        )
        for result in (as_author, as_default):
            assert (result.urgency_threshold, result.celebrate_clean_reviews) == ("must_fix", False)

    @parameterized.expand(
        [
            ("enabled", True, True, True, True, False, "PostHog", None),
            ("opted_out", False, True, True, True, False, "PostHog", None),
            ("inactive", True, False, True, True, False, "PostHog", None),
            ("left_organization", True, True, False, True, False, "PostHog", None),
            ("repository_removed", True, True, True, False, False, "PostHog", None),
            # No Flash after Full: a Full review published while the push waited stops it.
            ("full_review_published", True, True, True, True, True, "PostHog", None),
            ("placeholder_account_name", True, True, True, True, False, "installation-1234", "1234"),
        ]
    )
    def test_automatic_trigger_rechecks_eligible_author(
        self,
        _name: str,
        opted_in: bool,
        active: bool,
        member: bool,
        repository_added: bool,
        full_published: bool,
        account_name: str,
        installation_id: str | None,
    ) -> None:
        Integration.objects.create(
            team=self.team, kind="github", integration_id="1234", config={"account": {"name": account_name}}
        )
        if repository_added:
            ReviewInstallationClaim.objects.for_team(self.team.id).create(
                team=self.team, installation_id="1234", scope=ReviewInstallationClaim.Scope.SELECTED
            )
            ReviewRepository.objects.for_team(self.team.id).create(
                team=self.team, installation_id="1234", full_name="PostHog/posthog", selected=True
            )
        report = ReviewReport.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            repository="PostHog/posthog",
            pr_number=7,
            pr_url="https://github.com/PostHog/posthog/pull/7",
            head_branch="feat",
            base_branch="main",
            published_heads_by_mode={"full": "a" * 40} if full_published else None,
        )
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            preferences={"default_review_mode": "flash" if opted_in else "off"},
        )
        self.user.is_active = active
        self.user.save(update_fields=["is_active"])
        if not member:
            self.user.organization_memberships.filter(organization=self.organization).delete()
        result = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id,
                author_login="octocat",
                override_user_id=self.user.id,
                trigger_source=TRIGGER_AUTOMATIC,
                report_id=str(report.id),
                repository="posthog/PostHog",
                installation_id=installation_id,
            )
        )
        eligible = opted_in and active and member and repository_added and not full_published
        assert result.acting_user_id == (self.user.id if eligible else None)
        # The workflow gates the automatic run on this flag after the resolve.
        assert result.review_authored_prs is eligible
        report.refresh_from_db()
        assert report.status == (ReviewReport.Status.ACTIVE if eligible else ReviewReport.Status.IDLE)

    def test_settings_row_flows_into_the_result(self) -> None:
        # The user's saved preferences must reach the workflow — if resolve stops loading any of them,
        # the gates and publish silently revert to defaults. Each value is the OPPOSITE of its
        # default, so dropping one passthrough line fails here.
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            preferences={
                "review_inbox_prs": True,
                "urgency_threshold": "must_fix",
                "resolve_comments": True,
                "celebrate_clean_reviews": False,
            },
        )
        result = _resolve_acting_user(
            ResolveActingUserInput(team_id=self.team.id, author_login="octocat", override_user_id=None)
        )
        assert result.review_inbox_prs is True
        assert result.urgency_threshold == "must_fix"
        assert result.resolve_comments is True
        assert result.celebrate_clean_reviews is False

    def test_label_trigger_falls_back_to_the_run_user(self) -> None:
        # Unmapped author on a labeled PR → the run user the trigger already resolved, passed
        # through as default_user_id so acting and sandbox identity can never drift.
        result = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id,
                author_login="ghost",
                override_user_id=None,
                trigger_source=TRIGGER_LABEL,
                default_user_id=self.user.id,
            )
        )
        assert (result.acting_user_id, result.resolved_from) == (self.user.id, "default")

    def test_non_label_triggers_keep_the_author_only_contract(self) -> None:
        result = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id,
                author_login="ghost",
                override_user_id=None,
                trigger_source=TRIGGER_MANUAL,
                default_user_id=self.user.id,
            )
        )
        assert result.acting_user_id is None

    def test_personal_preferences_never_travel_with_a_borrowed_user(self) -> None:
        # self.user is both the mapped author (octocat) and the run-user fallback.
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            preferences={"resolve_comments": True, "celebrate_clean_reviews": False},
        )
        as_author = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id, author_login="octocat", override_user_id=None, trigger_source=TRIGGER_LABEL
            )
        )
        assert as_author.resolved_from == "author"
        assert as_author.resolve_comments is True
        # Acting as the borrowed run user on someone else's PR: the same row must NOT switch on
        # resolution for a PR that isn't theirs (the default posture applies).
        as_default = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id,
                author_login="ghost",
                override_user_id=None,
                trigger_source=TRIGGER_LABEL,
                default_user_id=self.user.id,
            )
        )
        assert (as_default.acting_user_id, as_default.resolved_from) == (self.user.id, "default")
        assert as_default.review_labeled_prs is True
        assert as_default.resolve_comments is False
        # Same borrowed-user protection: the run user's own media preference never shapes
        # someone else's PR.
        assert as_author.celebrate_clean_reviews is False
        assert as_default.celebrate_clean_reviews is True

    def test_urgency_threshold_follows_personal_sources_but_never_a_borrowed_default_user(self) -> None:
        # The publish-gate twin of the opt-out rule above: the run user's saved must_fix threshold
        # must not decide what lands on someone ELSE's PR — a default-resolved run gates at the
        # built-in default. Personal resolutions (author, requester override) keep the saved value.
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            preferences={"urgency_threshold": "must_fix", "celebrate_clean_reviews": False},
        )
        as_author = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id, author_login="octocat", override_user_id=None, trigger_source=TRIGGER_LABEL
            )
        )
        assert (as_author.resolved_from, as_author.urgency_threshold) == ("author", "must_fix")
        # The media switch follows the author: an override that IS the mapped author (a UI
        # self-review) keeps the saved value...
        as_author_override = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id,
                author_login="octocat",
                override_user_id=self.user.id,
                trigger_source=TRIGGER_LABEL,
            )
        )
        assert as_author_override.celebrate_clean_reviews is False
        # ...while an override by someone else (a UI requester on a teammate's PR) does not.
        as_override = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id, author_login="ghost", override_user_id=self.user.id, trigger_source=TRIGGER_LABEL
            )
        )
        assert (as_override.resolved_from, as_override.urgency_threshold) == ("override", "must_fix")
        assert as_override.celebrate_clean_reviews is True
        as_default = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id,
                author_login="ghost",
                override_user_id=None,
                trigger_source=TRIGGER_LABEL,
                default_user_id=self.user.id,
            )
        )
        assert (as_default.resolved_from, as_default.urgency_threshold) == ("default", "consider")

    def test_override_by_a_different_mapped_user_still_follows_the_authors_media_preference(self) -> None:
        # A teammate triggering a review from the UI supplies themselves as override_user_id while the
        # PR author is a distinct mapped user, so this must load the author's own opt-out rather than
        # falling through to the built-in default the way an unmapped author would.
        teammate = self._create_user("teammate@posthog.com")
        UserSocialAuth.objects.create(user=teammate, provider="github", uid="gh-2", extra_data={"login": "teammate"})
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=teammate.id, preferences={"celebrate_clean_reviews": False}
        )
        result = _resolve_acting_user(
            ResolveActingUserInput(team_id=self.team.id, author_login="teammate", override_user_id=self.user.id)
        )
        assert (result.acting_user_id, result.resolved_from) == (self.user.id, "override")
        assert result.celebrate_clean_reviews is False

    @parameterized.expand(
        [
            ("owner_opted_in_and_a_teammate_asks", "teammate", True, False, True),
            ("requester_opted_in_but_the_owner_did_not", "teammate", False, True, False),
            ("no_owner", "ghost", False, True, False),
        ]
    )
    def test_resolution_follows_the_pr_owners_opt_in(
        self,
        _name: str,
        author_login: str,
        owner_opted_in: bool,
        requester_opted_in: bool,
        expected: bool,
    ) -> None:
        teammate = self._create_user("teammate@posthog.com")
        UserSocialAuth.objects.create(user=teammate, provider="github", uid="gh-2", extra_data={"login": "teammate"})
        for user, opted_in in ((teammate, owner_opted_in), (self.user, requester_opted_in)):
            ReviewUserSettings.objects.for_team(self.team.id).create(
                team_id=self.team.id, user_id=user.id, preferences={"resolve_comments": opted_in}
            )
        result = _resolve_acting_user(
            ResolveActingUserInput(team_id=self.team.id, author_login=author_login, override_user_id=self.user.id)
        )

        assert result.acting_user_id == self.user.id
        assert result.owner_user_id == (teammate.id if author_login == "teammate" else None)
        assert result.resolve_comments is expected

    def test_automatic_bot_review_runs_as_the_connector_with_default_settings(self) -> None:
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="1234",
            config={"account": {"name": "PostHog"}},
            created_by=self.user,
        )
        ReviewInstallationClaim.objects.for_team(self.team.id).create(
            team=self.team, installation_id="1234", scope=ReviewInstallationClaim.Scope.ALL
        )
        ReviewProjectSettings.objects.for_team(self.team.id).create(
            team=self.team, bot_prs=ReviewProjectSettings.BotPullRequests.RUN
        )
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, preferences={"urgency_threshold": "must_fix"}
        )
        result = _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id,
                author_login="dependabot[bot]",
                override_user_id=self.user.id,
                trigger_source=TRIGGER_AUTOMATIC,
                repository="PostHog/posthog",
            )
        )
        assert (result.acting_user_id, result.review_authored_prs) == (self.user.id, True)
        # The connector only lends the credentials: their own threshold must not shape a bot's PR.
        assert result.urgency_threshold == "consider"

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
        _resolve_acting_user(
            ResolveActingUserInput(
                team_id=self.team.id, author_login="octocat", override_user_id=None, report_id=str(report.id)
            )
        )
        report.refresh_from_db()
        assert report.acting_user_id == self.user.id
