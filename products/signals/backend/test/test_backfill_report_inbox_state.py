import uuid

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.signals.backend.models import SignalReport, SignalReportAssignment, SignalScoutConfig, SignalScoutRun
from products.tasks.backend.models import Task, TaskRun


class TestBackfillReportInboxState(BaseTest):
    def _report(self) -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="t", summary="s")

    def _run(self, *, emitted_report_ids: list[str]) -> SignalScoutRun:
        task = Task.objects.create(
            team=self.team, title="scout", description="", origin_product=Task.OriginProduct.SIGNALS_SCOUT
        )
        config = SignalScoutConfig.objects.create(team=self.team, skill_name=f"signals-scout-{uuid.uuid4().hex[:8]}")
        return SignalScoutRun.objects.create(
            task_run=TaskRun.objects.create(task=task, team=self.team),
            team=self.team,
            scout_config=config,
            skill_name=config.skill_name,
            skill_version=1,
            emitted_report_ids=emitted_report_ids,
        )

    def _flags(self, report: SignalReport) -> tuple[bool, bool]:
        row = SignalReport.objects.filter(id=report.id).values_list(
            "has_implementation_pr", "has_active_implementation_pr"
        )[0]
        return row[0], row[1]

    def test_copies_the_emitting_run_config_onto_its_reports(self) -> None:
        authored = self._report()
        untouched = self._report()
        run = self._run(emitted_report_ids=[str(authored.id), "not-a-uuid"])

        call_command("backfill_report_inbox_state", "--team-id", str(self.team.id), "--only", "authorship")

        authored.refresh_from_db()
        untouched.refresh_from_db()
        assert authored.authoring_scout_config_id == run.scout_config_id
        assert untouched.authoring_scout_config_id is None

    def test_corrects_implementation_pr_flags_that_disagree_with_the_links(self) -> None:
        open_pr = self._report()
        merged_pr = self._report()
        stale = self._report()
        for report, number, merged in ((open_pr, 1, False), (merged_pr, 2, True)):
            SignalReportAssignment.all_teams.create(
                team=self.team,
                report=report,
                pr_url=f"https://github.com/example/app/pull/{number}",
                repository="example/app",
                pr_number=number,
                pr_state="merged" if merged else "open",
                pr_merged=merged,
            )
        SignalReport.objects.filter(id__in=[open_pr.id, merged_pr.id]).update(
            has_implementation_pr=False, has_active_implementation_pr=False
        )
        SignalReport.objects.filter(id=stale.id).update(has_implementation_pr=True, has_active_implementation_pr=True)

        call_command(
            "backfill_report_inbox_state",
            "--team-id",
            str(self.team.id),
            "--only",
            "implementation-pr",
            "--batch-size",
            "2",
        )

        assert self._flags(open_pr) == (True, True)
        assert self._flags(merged_pr) == (True, False)
        assert self._flags(stale) == (False, False)
