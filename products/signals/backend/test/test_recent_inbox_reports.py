from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models.team.team import Team

from products.signals.backend.facade.api import recent_inbox_reports, waiting_report_count
from products.signals.backend.models import SignalReport


class TestRecentInboxReports(BaseTest):
    def _report(self, **kwargs: object) -> SignalReport:
        defaults: dict[str, object] = {
            "team_id": self.team.id,
            "status": SignalReport.Status.READY,
            "title": "Checkout throws on retry",
            "first_visible_at": timezone.now(),
        }
        defaults.update(kwargs)
        return SignalReport.objects.create(**defaults)

    def test_the_newest_reports_come_back_first_and_within_the_limit(self) -> None:
        older = self._report(title="Older", first_visible_at=timezone.now() - timedelta(hours=2))
        newer = self._report(title="Newer", first_visible_at=timezone.now())

        reports = recent_inbox_reports(self.team.id, limit=1)

        assert [report.report_id for report in reports] == [str(newer.id)]
        assert str(older.id) not in {report.report_id for report in reports}

    @parameterized.expand(
        [
            ("archived by the user", SignalReport.Status.SUPPRESSED),
            ("deleted", SignalReport.Status.DELETED),
            ("already resolved", SignalReport.Status.RESOLVED),
            ("a failed run", SignalReport.Status.FAILED),
            ("back in research", SignalReport.Status.IN_PROGRESS),
        ]
    )
    def test_a_report_nobody_can_act_on_is_never_offered(self, _name: str, status: str) -> None:
        # Onboarding puts these behind a button, so a finished or failed finding offered as one
        # that is waiting sends a first-time user to something nobody needs to look at.
        # `first_visible_at` survives every one of these transitions, so status is the only guard.
        self._report(status=status)

        assert recent_inbox_reports(self.team.id) == []

    def test_a_report_with_nothing_to_show_is_never_offered(self) -> None:
        self._report(first_visible_at=None)
        self._report(title=None)

        assert recent_inbox_reports(self.team.id) == []

    def test_the_count_never_promises_more_findings_than_can_be_named(self) -> None:
        # The opening message states this count, and the agent then offers reports by id. A count
        # that includes finished work makes onboarding claim findings it cannot produce.
        self._report()
        self._report(status=SignalReport.Status.RESOLVED)
        self._report(status=SignalReport.Status.SUPPRESSED)

        assert waiting_report_count(self.team.id) == 1
        assert len(recent_inbox_reports(self.team.id, limit=10)) == 1

    def test_another_team_s_reports_stay_out_of_this_one_s(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._report(team_id=other_team.id, title="Someone else's problem")

        assert recent_inbox_reports(self.team.id) == []
