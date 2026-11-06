from datetime import timedelta

from django.utils import timezone

from posthog.models.scoping import team_scope

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun
from products.tasks.backend.models import Task, TaskRun


class TestScannerScoutReports(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()
        self.other_scanner = self._create_scanner(name="another-scanner")
        self.report = self._file_report(self.scanner, "signals-scout-daily-digest", "Digest", "**Found something.**")

    def _reports_url(self, scanner_id: str) -> str:
        return f"/api/environments/{self.team.id}/vision/scanners/{scanner_id}/scout_reports/"

    def _file_report(self, scanner: ReplayScanner, skill_name: str, title: str, summary: str) -> SignalReport:
        with team_scope(self.team.id):
            config, _ = SignalScoutConfig.objects.get_or_create(
                team=self.team,
                skill_name=skill_name,
                defaults={"source_product": SCOUT_SOURCE_PRODUCT, "source_id": str(scanner.id)},
            )
            report = SignalReport.objects.create(team=self.team, title=title, summary=summary)
            task = Task.objects.create(team=self.team, title=f"Scout run: {skill_name}")
            task_run = TaskRun.objects.create(
                team=self.team, task=task, status=TaskRun.Status.COMPLETED, environment="", stage=""
            )
            SignalScoutRun.objects.create(
                team=self.team,
                task_run=task_run,
                scout_config=config,
                skill_name=skill_name,
                skill_version=1,
                emitted_report_ids=[str(report.id)],
            )
        return report

    def test_lists_and_reads_reports_filed_for_this_scanner(self) -> None:
        listed = self.client.get(self._reports_url(str(self.scanner.id)))
        assert listed.status_code == 200, listed.json()
        assert [r["report_id"] for r in listed.json()] == [str(self.report.id)]

        read = self.client.get(f"{self._reports_url(str(self.scanner.id))}{self.report.id}/")
        assert read.status_code == 200, read.json()
        assert read.json()["summary"] == "**Found something.**"
        assert read.json()["skill_name"] == "signals-scout-daily-digest"

    def test_report_from_another_scanner_is_not_readable_through_this_one(self) -> None:
        # The whole reason this endpoint exists: the project-wide report endpoint would serve this,
        # because it scopes to the team and can't tell which scanner produced the report.
        other_report = self._file_report(self.other_scanner, "signals-scout-other", "Theirs", "Not yours.")

        response = self.client.get(f"{self._reports_url(str(self.scanner.id))}{other_report.id}/")
        assert response.status_code == 404

        listed = self.client.get(self._reports_url(str(self.scanner.id)))
        assert str(other_report.id) not in [r["report_id"] for r in listed.json()]

    def test_scout_without_this_scanner_as_its_source_is_not_exposed(self) -> None:
        # The source pair is the ownership record; a scout that does not carry it is not this
        # scanner's to show, so its reports must not ride along.
        with team_scope(self.team.id):
            SignalScoutConfig.objects.filter(skill_name="signals-scout-daily-digest").update(source_id=None)

        response = self.client.get(f"{self._reports_url(str(self.scanner.id))}{self.report.id}/")
        assert response.status_code == 404

    def test_filed_at_comes_from_the_run_not_the_report_row(self) -> None:
        # The report row's timestamps move when a scout edits it; a reader means "when did this land".
        with team_scope(self.team.id):
            run = SignalScoutRun.objects.get(skill_name="signals-scout-daily-digest")
            filed_at = timezone.now() - timedelta(days=3)
            SignalScoutRun.objects.filter(pk=run.pk).update(created_at=filed_at)

        response = self.client.get(f"{self._reports_url(str(self.scanner.id))}{self.report.id}/")
        assert response.json()["filed_at"].startswith(filed_at.strftime("%Y-%m-%d"))

    def test_unknown_scanner_is_not_found(self) -> None:
        response = self.client.get(f"{self._reports_url('01a01111-2222-3333-4444-555566667777')}{self.report.id}/")
        assert response.status_code == 404

    def test_a_report_this_scanners_scout_merely_edited_is_not_exposed(self) -> None:
        # `edit_report` resolves its target by team alone, so a scout can edit a report it did not
        # write. This route is gated on scanner + recording access, not inbox access, so an edit must
        # never be enough to read someone else's report through it.
        with team_scope(self.team.id):
            someone_elses = SignalReport.objects.create(team=self.team, title="Theirs", summary="Not yours.")
            run = SignalScoutRun.objects.get(skill_name="signals-scout-daily-digest")
            SignalScoutRun.objects.filter(pk=run.pk).update(edited_report_ids=[str(someone_elses.id)])

        response = self.client.get(f"{self._reports_url(str(self.scanner.id))}{someone_elses.id}/")
        assert response.status_code == 404

        listed = self.client.get(self._reports_url(str(self.scanner.id)))
        assert str(someone_elses.id) not in [r["report_id"] for r in listed.json()]

    def test_deleted_and_suppressed_reports_stay_hidden(self) -> None:
        # The platform decided not to show these; this route must not route around that.
        for status in (SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED):
            with team_scope(self.team.id):
                SignalReport.objects.filter(pk=self.report.pk).update(status=status)
            response = self.client.get(f"{self._reports_url(str(self.scanner.id))}{self.report.id}/")
            assert response.status_code == 404, status
