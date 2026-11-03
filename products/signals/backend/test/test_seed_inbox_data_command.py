from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

from parameterized import parameterized

from products.signals.backend.management.commands import seed_inbox_data
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

        seed_inbox_data.Command(stdout=StringIO())._advance_to_final(report, result, final_status)

        report.refresh_from_db()
        assert report.status == final_status
        assert report.title == "Signup form drops users"

    @override_settings(DEBUG=True)
    def test_default_seed_leaves_reports_needing_input_without_an_implementation_run(self) -> None:
        with (
            patch.object(seed_inbox_data, "_persist_agentic_report_artefacts"),
            patch.object(seed_inbox_data.tasks_facade, "create_and_run_task") as create_task,
        ):
            create_task.return_value.latest_run = None
            call_command("seed_inbox_data", team_id=self.team.id, stdout=StringIO())

        reports = SignalReport.objects.filter(team=self.team)
        pending = reports.get(status=SignalReport.Status.PENDING_INPUT)
        assert pending.title and pending.summary and pending.error
        assert reports.filter(status=SignalReport.Status.READY).exists()
        assert {call.kwargs["signal_report_id"] for call in create_task.call_args_list} == {
            str(report_id) for report_id in reports.exclude(pk=pending.pk).values_list("pk", flat=True)
        }
