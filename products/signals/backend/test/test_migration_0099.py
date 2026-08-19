from datetime import UTC, datetime
from typing import Any

from posthog.test.base import NonAtomicTestMigrations


# Non-atomic so a future signals migration with a CONCURRENTLY index doesn't break the rewind.
class BackfillFirstVisibleAtMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0098_signalreport_first_visible_index"
    migrate_to = "0099_backfill_first_visible_at"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "signals"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        SignalReport = apps.get_model("signals", "SignalReport")

        org = Organization.objects.create(name="Test Organization")
        project = Project.objects.create(id=999997, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")

        def make_report(status: str, **kwargs: Any) -> Any:
            return SignalReport.objects.create(team_id=team.id, status=status, **kwargs)

        self.stamped_ids = [
            make_report("ready").id,
            make_report("pending_input").id,
            make_report("resolved").id,
            make_report("suppressed", status_before_suppression="ready").id,
        ]
        self.untouched_ids = [
            make_report("potential").id,
            make_report("failed").id,
            make_report("suppressed", status_before_suppression="potential").id,
        ]
        self.preset_stamp = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
        self.preset_id = make_report("ready", first_visible_at=self.preset_stamp).id

    def test_backfills_only_previously_visible_unstamped_reports(self) -> None:
        assert self.apps is not None
        SignalReport = self.apps.get_model("signals", "SignalReport")

        for report_id in self.stamped_ids:
            report = SignalReport.objects.get(id=report_id)
            assert report.first_visible_at == report.created_at

        for report_id in self.untouched_ids:
            assert SignalReport.objects.get(id=report_id).first_visible_at is None

        assert SignalReport.objects.get(id=self.preset_id).first_visible_at == self.preset_stamp
