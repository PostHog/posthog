from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models import Organization, User

from products.review_hog.backend.models import ReviewUserSettings


class TestEnableInboxReviews(BaseTest):
    def _row(self, user: User) -> ReviewUserSettings | None:
        return ReviewUserSettings.objects.for_team(self.team.id).filter(user_id=user.id).first()

    def test_enables_both_toggles_for_active_org_members_and_nobody_else(self) -> None:
        member_without_row = User.objects.create_and_join(self.organization, "no-row@example.com", None)
        # An explicit opt-out gets flipped on too, but only the two inbox toggles: the row's other
        # fields (here the urgency threshold) must survive the run.
        member_opted_out = User.objects.create_and_join(self.organization, "opted-out@example.com", None)
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=member_opted_out.id,
            review_inbox_prs=False,
            stamphog_review_inbox_prs=False,
            urgency_threshold=ReviewUserSettings.UrgencyThreshold.MUST_FIX,
        )
        inactive_member = User.objects.create_and_join(self.organization, "inactive@example.com", None)
        inactive_member.is_active = False
        inactive_member.save()
        other_org = Organization.objects.create(name="other org")
        outsider = User.objects.create_and_join(other_org, "outsider@example.com", None)

        call_command("enable_inbox_reviews", team_id=self.team.id)

        for member in (self.user, member_without_row, member_opted_out):
            row = self._row(member)
            assert row is not None
            assert row.review_inbox_prs is True
            assert row.stamphog_review_inbox_prs is True
        opted_out_row = self._row(member_opted_out)
        assert opted_out_row is not None
        assert opted_out_row.urgency_threshold == ReviewUserSettings.UrgencyThreshold.MUST_FIX
        assert self._row(inactive_member) is None
        assert self._row(outsider) is None

    def test_dry_run_writes_nothing(self) -> None:
        member_opted_out = User.objects.create_and_join(self.organization, "opted-out@example.com", None)
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=member_opted_out.id,
            review_inbox_prs=False,
            stamphog_review_inbox_prs=False,
        )

        call_command("enable_inbox_reviews", team_id=self.team.id, dry_run=True)

        row = self._row(member_opted_out)
        assert row is not None
        assert row.review_inbox_prs is False
        assert row.stamphog_review_inbox_prs is False
        assert self._row(self.user) is None
