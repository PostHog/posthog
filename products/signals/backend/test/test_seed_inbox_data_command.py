from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

from products.signals.backend.management.commands import seed_inbox_data
from products.signals.backend.models import SignalReport


class TestSeedInboxDataCommand(BaseTest):
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
        assert {call.kwargs["source"].id for call in create_task.call_args_list} == {
            str(report_id) for report_id in reports.exclude(pk=pending.pk).values_list("pk", flat=True)
        }
