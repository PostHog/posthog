from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import Organization, User

from products.review_hog.backend.models import ReviewUserSettings
from products.review_hog.backend.settings_toggles import ToggleField, toggle_default

REVIEWHOG: ToggleField = "review_inbox_prs"
STAMPHOG: ToggleField = "stamphog_review_inbox_prs"
RESOLVE: ToggleField = "resolve_comments"
AUTHORED: ToggleField = "review_authored_prs"
OTHER_FIELD: dict[ToggleField, ToggleField] = {
    REVIEWHOG: STAMPHOG,
    STAMPHOG: REVIEWHOG,
    RESOLVE: REVIEWHOG,
    AUTHORED: REVIEWHOG,
}
COMMANDS = [
    ("enable_inbox_reviews", REVIEWHOG, True),
    ("disable_inbox_reviews", REVIEWHOG, False),
    ("enable_stamphog_inbox_reviews", STAMPHOG, True),
    ("disable_stamphog_inbox_reviews", STAMPHOG, False),
    ("enable_comment_resolution", RESOLVE, True),
    ("disable_comment_resolution", RESOLVE, False),
    ("enable_authored_pr_reviews", AUTHORED, True),
    ("disable_authored_pr_reviews", AUTHORED, False),
]


class TestSettingsToggleCommands(BaseTest):
    def _row(self, user: User) -> ReviewUserSettings | None:
        return ReviewUserSettings.objects.for_team(self.team.id).filter(user_id=user.id).first()

    def _member(self, email: str, **fields: object) -> User:
        user = User.objects.create_and_join(self.organization, email, None)
        if fields:
            ReviewUserSettings.objects.for_team(self.team.id).create(team_id=self.team.id, user_id=user.id, **fields)
        return user

    @parameterized.expand(COMMANDS)
    def test_whole_team_sets_only_its_toggle_for_active_org_members(
        self, command: str, field: ToggleField, enabled: bool
    ) -> None:
        member_without_row = self._member("no-row@example.com")
        member_opposite = self._member(
            "opposite@example.com",
            **{field: not enabled, OTHER_FIELD[field]: not enabled},
            urgency_threshold=ReviewUserSettings.UrgencyThreshold.MUST_FIX,
            flash_reasoning_effort=ReviewUserSettings.FlashReasoningEffort.XHIGH,
        )
        inactive_member = self._member("inactive@example.com", **{field: not enabled})
        inactive_member.is_active = False
        inactive_member.save()
        other_org = Organization.objects.create(name="other org")
        outsider = User.objects.create_and_join(other_org, "outsider@example.com", None)

        call_command(command, team_id=self.team.id)

        opposite_row = self._row(member_opposite)
        assert opposite_row is not None
        assert getattr(opposite_row, field) is enabled
        assert getattr(opposite_row, OTHER_FIELD[field]) is not enabled
        assert opposite_row.urgency_threshold == ReviewUserSettings.UrgencyThreshold.MUST_FIX
        assert opposite_row.flash_reasoning_effort == "xhigh"
        if enabled is not toggle_default(field):
            for member in (self.user, member_without_row):
                row = self._row(member)
                assert row is not None
                assert getattr(row, field) is enabled
                assert getattr(row, OTHER_FIELD[field]) is toggle_default(OTHER_FIELD[field])
        else:
            # A missing row already reads as the default, so no rows get created.
            assert self._row(self.user) is None
            assert self._row(member_without_row) is None
        inactive_row = self._row(inactive_member)
        assert inactive_row is not None
        assert getattr(inactive_row, field) is not enabled
        assert self._row(outsider) is None

    @parameterized.expand(
        [
            ("enable_inbox_reviews", REVIEWHOG, True),
            ("disable_inbox_reviews", REVIEWHOG, False),
            ("enable_authored_pr_reviews", AUTHORED, True),
            ("disable_authored_pr_reviews", AUTHORED, False),
        ]
    )
    def test_user_ids_change_only_those_users(self, command: str, field: ToggleField, enabled: bool) -> None:
        target = self._member("target@example.com", **{field: not enabled})
        untouched = self._member("untouched@example.com", **{field: not enabled})

        call_command(command, team_id=self.team.id, user_ids=[target.id])

        target_row, untouched_row = self._row(target), self._row(untouched)
        assert target_row is not None and getattr(target_row, field) is enabled
        assert untouched_row is not None and getattr(untouched_row, field) is not enabled
        assert self._row(self.user) is None

    def test_user_ids_outside_the_org_fail_before_writing(self) -> None:
        member = self._member("member@example.com", review_inbox_prs=False)
        other_org = Organization.objects.create(name="other org")
        outsider = User.objects.create_and_join(other_org, "outsider@example.com", None)

        with self.assertRaises(CommandError) as ctx:
            call_command("enable_inbox_reviews", team_id=self.team.id, user_ids=[member.id, outsider.id])

        assert str(outsider.id) in str(ctx.exception)
        member_row = self._row(member)
        assert member_row is not None and member_row.review_inbox_prs is False
        assert self._row(outsider) is None

    @parameterized.expand([("enable_inbox_reviews", True), ("disable_inbox_reviews", False)])
    def test_dry_run_writes_nothing(self, command: str, enabled: bool) -> None:
        member = self._member("member@example.com", review_inbox_prs=not enabled)

        call_command(command, team_id=self.team.id, dry_run=True)

        row = self._row(member)
        assert row is not None and row.review_inbox_prs is not enabled
        assert self._row(self.user) is None

    @parameterized.expand(["medium", "xhigh"])
    def test_authored_opt_in_sets_effort_for_new_and_already_enabled_users(self, effort: str) -> None:
        opposite_effort = "xhigh" if effort == "medium" else "medium"
        opted_in = self._member(
            "opted-in@example.com", review_authored_prs=True, flash_reasoning_effort=opposite_effort
        )
        untouched = self._member(
            "untouched@example.com", review_authored_prs=True, flash_reasoning_effort=opposite_effort
        )

        call_command(
            "enable_authored_pr_reviews", team_id=self.team.id, user_ids=[self.user.id, opted_in.id], effort=effort
        )

        for user in (self.user, opted_in):
            row = self._row(user)
            assert row is not None and row.review_authored_prs is True
            assert row.flash_reasoning_effort == effort
        untouched_row = self._row(untouched)
        assert untouched_row is not None and untouched_row.flash_reasoning_effort == opposite_effort

    def test_authored_effort_dry_run_includes_already_enabled_users_without_writing(self) -> None:
        opted_in = self._member("opted-in@example.com", review_authored_prs=True)
        output = StringIO()

        call_command(
            "enable_authored_pr_reviews",
            team_id=self.team.id,
            user_ids=[opted_in.id],
            effort="xhigh",
            dry_run=True,
            stdout=output,
        )

        row = self._row(opted_in)
        assert row is not None and row.flash_reasoning_effort == "medium"
        assert f"Would change user id(s): {opted_in.id}" in output.getvalue()
        assert "flash_reasoning_effort: xhigh" in output.getvalue()

    def test_authored_invalid_effort_fails_before_writing(self) -> None:
        with self.assertRaises(CommandError):
            call_command("enable_authored_pr_reviews", team_id=self.team.id, effort="high")

        assert self._row(self.user) is None
