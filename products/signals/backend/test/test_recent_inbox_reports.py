from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.team.team import Team

from products.signals.backend.facade.api import recent_inbox_reports
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

    def test_a_report_nobody_can_act_on_is_never_offered(self) -> None:
        # Onboarding puts these behind a button, so offering an archived or never-surfaced report
        # sends a first-time user to something that is not in their inbox.
        self._report(status=SignalReport.Status.SUPPRESSED)
        self._report(status=SignalReport.Status.DELETED)
        self._report(first_visible_at=None)
        self._report(title=None)

        assert recent_inbox_reports(self.team.id) == []

    def test_another_team_s_reports_stay_out_of_this_one_s(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._report(team_id=other_team.id, title="Someone else's problem")

        assert recent_inbox_reports(self.team.id) == []
