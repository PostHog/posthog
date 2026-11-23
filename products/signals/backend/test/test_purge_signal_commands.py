import json
from datetime import UTC, datetime
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.billing import SIGNALS_CREDITS_PER_REPORT_WITH_PR
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportRefund,
    SignalScoutRun,
    SignalScratchpad,
)

COMMAND_MODULE = "products.signals.backend.management.commands.purge_signal_reports"


class TestPurgeSignalReports(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.target = self._report(self.team)
        self.untouched = self._report(self.team)
        self.other_team = Team.objects.create(organization=self.organization, name="Other")
        self.other_team_report = self._report(self.other_team)

        self.fetch_signal_ids = self._patch("fetch_report_signal_ids", MagicMock(return_value=["signal-1", "signal-2"]))
        self.submit_updates = self._patch("submit_signal_metadata_updates", AsyncMock())
        self.tombstone = self._patch("emit_report_tombstone", MagicMock())

    def _patch(self, name: str, mock):
        patcher = patch(f"{COMMAND_MODULE}.{name}", mock)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def _report(self, team: Team, status: str = SignalReport.Status.DELETED) -> SignalReport:
        report = SignalReport.objects.create(team=team, status=status, title="Report", summary="Text")
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
            content=json.dumps({"choice": True}),
        )
        return report

    def _purge(self, *report_ids, execute: bool = False, **options) -> str:
        output = StringIO()
        call_command(
            "purge_signal_reports",
            team_id=self.team.id,
            report_ids=[str(report_id) for report_id in report_ids],
            execute=execute,
            stdout=output,
            **options,
        )
        return output.getvalue()

    def _surviving_report_ids(self) -> set:
        return set(SignalReport.objects.values_list("id", flat=True))

    def test_preview_writes_nothing(self) -> None:
        output = self._purge(self.target.id)

        assert "Preview only" in output
        assert "document_id IN ('signal-1', 'signal-2')" in output
        assert self._surviving_report_ids() == {self.target.id, self.untouched.id, self.other_team_report.id}
        assert SignalReportArtefact.objects.filter(report_id=self.target.id).exists()
        self.submit_updates.assert_not_awaited()
        self.tombstone.assert_not_called()

    def test_execute_purges_only_the_listed_reports(self) -> None:
        self._purge(self.target.id, execute=True)

        assert self._surviving_report_ids() == {self.untouched.id, self.other_team_report.id}
        assert not SignalReportArtefact.objects.filter(report_id=self.target.id).exists()
        assert SignalReportArtefact.objects.filter(report_id=self.untouched.id).exists()
        change = self.submit_updates.await_args.kwargs["change"]
        assert self.submit_updates.await_args.kwargs["signal_ids"] == ["signal-1", "signal-2"]
        assert change.clear_content and change.deleted and change.expected_report_id == str(self.target.id)

    @parameterized.expand(
        [
            ("other_team", lambda test: test.other_team_report.id, "do not belong to team"),
            ("missing", lambda test: "00000000-0000-0000-0000-000000000000", "not found"),
            ("not_deleted", lambda test: test._report(test.team, SignalReport.Status.READY).id, "not deleted yet"),
        ]
    )
    def test_execute_refuses_the_whole_list(self, _name: str, bad_report_id, message: str) -> None:
        bad_id = bad_report_id(self)
        before = self._surviving_report_ids()

        with self.assertRaisesMessage(CommandError, message):
            self._purge(self.target.id, bad_id, execute=True)

        assert self._surviving_report_ids() == before
        self.submit_updates.assert_not_awaited()

    def test_refund_record_blocks_the_purge(self) -> None:
        SignalReportRefund.objects.create(
            team=self.team,
            report=self.target,
            reason=SignalReportRefund.Reason.PR_INCORRECT,
            billing_path=SignalReportRefund.BillingPath.EXCLUDED,
            credits=SIGNALS_CREDITS_PER_REPORT_WITH_PR,
            pr_url="https://github.com/x/y/pull/1",
            pr_run_created_at=datetime(2026, 6, 10, tzinfo=UTC),
        )

        with self.assertRaisesMessage(CommandError, "refund record"):
            self._purge(self.target.id, execute=True)

        assert SignalReport.objects.filter(id=self.target.id).exists()


class TestPurgeSignalScratchpad(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scout_run = self._run("signals-scout-errors")
        self.other_run = self._run("signals-scout-general")
        SignalScratchpad.objects.create(team=self.team, key="errors:a", content="x", created_by_run=self.scout_run)
        SignalScratchpad.objects.create(team=self.team, key="general:a", content="x", created_by_run=self.other_run)
        SignalScratchpad.objects.create(team=self.team, key="manual:a", content="x")
        self.other_team = Team.objects.create(organization=self.organization, name="Other")
        SignalScratchpad.objects.create(team=self.other_team, key="errors:a", content="x")

    def _run(self, skill_name: str) -> SignalScoutRun:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team, title="scout", description="scout", origin_product=Task.OriginProduct.SIGNALS_SCOUT
        )
        task_run = TaskRun.objects.create(task=task, team=self.team)
        return SignalScoutRun.objects.create(team=self.team, task_run=task_run, skill_name=skill_name, skill_version=1)

    def _purge(self, *, execute: bool = False, **selection) -> str:
        output = StringIO()
        call_command("purge_signal_scratchpad", team_id=self.team.id, execute=execute, stdout=output, **selection)
        return output.getvalue()

    def _keys(self, team: Team) -> set[str]:
        return set(SignalScratchpad.objects.for_team(team.id, canonical=True).values_list("key", flat=True))

    def test_preview_writes_nothing(self) -> None:
        output = self._purge(all=True)

        assert "Preview only" in output
        assert self._keys(self.team) == {"errors:a", "general:a", "manual:a"}

    @parameterized.expand(
        [
            ("scout", {"scout_skill": "signals-scout-errors"}, {"general:a", "manual:a"}),
            ("keys", {"keys": ["manual:a", "absent"]}, {"errors:a", "general:a"}),
            ("all", {"all": True}, set()),
        ]
    )
    def test_execute_deletes_only_the_selection(self, _name: str, selection: dict, kept: set[str]) -> None:
        self._purge(execute=True, **selection)

        assert self._keys(self.team) == kept
        assert self._keys(self.other_team) == {"errors:a"}
