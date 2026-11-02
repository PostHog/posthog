from io import StringIO

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.signals.backend.management.commands.seed_inbox_data import Command
from products.signals.backend.models import SignalReport
from products.signals.backend.report_generation.research import ReportResearchOutput


class TestSeedInboxDataCommand(BaseTest):
    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY),
            ("pending_input", SignalReport.Status.PENDING_INPUT),
        ]
    )
    def test_advance_to_final_reaches_the_requested_status(self, _name: str, final_status: SignalReport.Status) -> None:
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.POTENTIAL, signal_count=1, total_weight=1.0
        )
        report.save(update_fields=report.transition_to(SignalReport.Status.CANDIDATE))
        report.save(update_fields=report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=1))
        result = ReportResearchOutput(title="Signup form drops users", summary="Half of the signups stop at step two.")

        Command(stdout=StringIO())._advance_to_final(report, result, final_status)

        report.refresh_from_db()
        assert report.status == final_status
        assert report.title == "Signup form drops users"
