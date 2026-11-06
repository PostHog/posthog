from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models.team.team import Team

from products.signals.backend.facade.api import waiting_reports
from products.signals.backend.models import SignalReport


class TestWaitingReports(BaseTest):
    def _report(self, **kwargs: object) -> SignalReport:
        defaults: dict[str, object] = {
            "team_id": self.team.id,
            "status": SignalReport.Status.READY,
            "title": "Checkout throws on retry",
            "first_visible_at": timezone.now(),
        }
        defaults.update(kwargs)
        return SignalReport.objects.create(**defaults)

    def test_the_newest_reports_are_named_first_and_within_the_limit(self) -> None:
        older = self._report(title="Older", first_visible_at=timezone.now() - timedelta(hours=2))
        newer = self._report(title="Newer", first_visible_at=timezone.now())

        waiting = waiting_reports(self.team.id, limit=1)

        assert [report.report_id for report in waiting.offerable] == [str(newer.id)]
        assert str(older.id) not in {report.report_id for report in waiting.offerable}
        # The limit bounds what gets named, never what the user is told is waiting for them.
        assert waiting.count == 2

    @parameterized.expand(
        [
            ("archived by the user", SignalReport.Status.SUPPRESSED),
            ("deleted", SignalReport.Status.DELETED),
            ("already resolved", SignalReport.Status.RESOLVED),
            ("a failed run", SignalReport.Status.FAILED),
            ("back in research", SignalReport.Status.IN_PROGRESS),
        ]
    )
    def test_a_report_nobody_can_act_on_is_neither_counted_nor_named(self, _name: str, status: str) -> None:
        # `first_visible_at` survives every one of these transitions, so status is the only guard.
        # Without it onboarding counts finished work as waiting and offers it to a first-time user.
        self._report(status=status)

        waiting = waiting_reports(self.team.id)

        assert waiting.count == 0
        assert waiting.offerable == ()

    def test_a_report_that_never_surfaced_is_neither_counted_nor_named(self) -> None:
        self._report(first_visible_at=None)

        waiting = waiting_reports(self.team.id)

        assert waiting.count == 0
        assert waiting.offerable == ()

    @parameterized.expand([("no title", None), ("a blank title", "")])
    def test_a_report_with_no_title_is_counted_but_not_named(self, _name: str, title: str | None) -> None:
        # The inbox renders one of these from its summary, so it is genuinely waiting for them and
        # the count has to match what they will see. There is just nothing to call it in a sentence,
        # so it is skipped rather than offered as a blank row.
        self._report(title=title)

        waiting = waiting_reports(self.team.id)

        assert waiting.count == 1
        assert waiting.offerable == ()

    def test_another_team_s_reports_stay_out_of_this_one_s(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._report(team_id=other_team.id, title="Someone else's problem")

        waiting = waiting_reports(self.team.id)

        assert waiting.count == 0
        assert waiting.offerable == ()
