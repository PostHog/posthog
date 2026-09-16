from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import Organization, User

from products.review_hog.backend.models import ReviewUserSettings

REVIEWHOG, STAMPHOG = "review_inbox_prs", "stamphog_review_inbox_prs"
OTHER_FIELD = {REVIEWHOG: STAMPHOG, STAMPHOG: REVIEWHOG}
COMMANDS = [
    ("enable_inbox_reviews", REVIEWHOG, True),
    ("disable_inbox_reviews", REVIEWHOG, False),
    ("enable_stamphog_inbox_reviews", STAMPHOG, True),
    ("disable_stamphog_inbox_reviews", STAMPHOG, False),
]


class TestInboxReviewCommands(BaseTest):
    def _row(self, user: User) -> ReviewUserSettings | None:
        return ReviewUserSettings.objects.for_team(self.team.id).filter(user_id=user.id).first()

    def _member(self, email: str, **fields: object) -> User:
        user = User.objects.create_and_join(self.organization, email, None)
        if fields:
            ReviewUserSettings.objects.for_team(self.team.id).create(team_id=self.team.id, user_id=user.id, **fields)
        return user

    @parameterized.expand(COMMANDS)
    def test_whole_team_sets_only_its_toggle_for_active_org_members(
        self, command: str, field: str, enabled: bool
    ) -> None:
        member_without_row = self._member("no-row@example.com")
        member_opposite = self._member(
            "opposite@example.com",
            **{field: not enabled, OTHER_FIELD[field]: not enabled},
            urgency_threshold=ReviewUserSettings.UrgencyThreshold.MUST_FIX,
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
        if enabled:
            for member in (self.user, member_without_row):
                row = self._row(member)
                assert row is not None
                assert getattr(row, field) is True
                assert getattr(row, OTHER_FIELD[field]) is False
        else:
            # No row already means off, so turning off must not create rows.
            assert self._row(self.user) is None
            assert self._row(member_without_row) is None
        inactive_row = self._row(inactive_member)
        assert inactive_row is not None
        assert getattr(inactive_row, field) is not enabled
        assert self._row(outsider) is None

    @parameterized.expand([("enable_inbox_reviews", True), ("disable_inbox_reviews", False)])
    def test_user_ids_change_only_those_users(self, command: str, enabled: bool) -> None:
        target = self._member("target@example.com", review_inbox_prs=not enabled)
        untouched = self._member("untouched@example.com", review_inbox_prs=not enabled)

        call_command(command, team_id=self.team.id, user_ids=[target.id])

        target_row, untouched_row = self._row(target), self._row(untouched)
        assert target_row is not None and target_row.review_inbox_prs is enabled
        assert untouched_row is not None and untouched_row.review_inbox_prs is not enabled
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
