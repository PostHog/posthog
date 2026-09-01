from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import NonAtomicTestMigrations

# Non-atomic: 0117 creates its indexes CONCURRENTLY, which an atomic rewind cannot replay.
_CREATED = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class BackfillReportStalenessClocksMigrationTest(NonAtomicTestMigrations):
    """The clocks have to be seeded, not left null.

    A null clock resolves to the report's birth, so an unseeded backlog would read as archivable
    on the first enforcing sweep, on evidence that was never collected. Same for the opt-in: an
    unseeded config row reads as opted in, which is the mass archive this backfill exists to stop.
    """

    migrate_from = "0117_signalreport_staleness_indexes"
    migrate_to = "0118_backfill_report_staleness_clocks"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "signals"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        User = apps.get_model("posthog", "User")
        SignalReport = apps.get_model("signals", "SignalReport")
        SignalReportArtefact = apps.get_model("signals", "SignalReportArtefact")
        SignalTeamConfig = apps.get_model("signals", "SignalTeamConfig")

        org = Organization.objects.create(name="Test Organization")
        project = Project.objects.create(id=999996, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")
        user = User.objects.create(email="someone@example.com", first_name="Someone", password="x")

        def make_report(status: str, **kwargs: Any) -> Any:
            report = SignalReport.objects.create(team_id=team.id, status=status, **kwargs)
            # `created_at`/`updated_at` are auto fields, so they have to be pushed back after the
            # insert for the seeded values to be anything other than "now".
            SignalReport.objects.filter(id=report.id).update(created_at=_CREATED, updated_at=_CREATED)
            return report

        self.reapable_id = make_report("ready", last_run_at=_CREATED + timedelta(days=3)).id
        self.untouched_id = make_report("candidate").id
        self.terminal_id = make_report("resolved").id

        self.touched_at = _CREATED + timedelta(days=5)
        touched = make_report("pending_input")
        self.touched_id = touched.id
        artefact = SignalReportArtefact.objects.create(
            team_id=team.id, report_id=touched.id, type="note", content="{}", created_by_id=user.id
        )
        SignalReportArtefact.objects.filter(id=artefact.id).update(created_at=self.touched_at)

        self.opted_out_id = SignalTeamConfig.objects.create(team_id=team.id).id

    def test_seeds_both_clocks_and_opts_existing_teams_out(self) -> None:
        assert self.apps is not None
        SignalReport = self.apps.get_model("signals", "SignalReport")
        SignalTeamConfig = self.apps.get_model("signals", "SignalTeamConfig")

        # `last_activity_at` takes the newest timestamp the report already carried.
        assert SignalReport.objects.get(id=self.reapable_id).last_activity_at == _CREATED + timedelta(days=3)
        # No later evidence anywhere, so both clocks start from the report's birth rather than null.
        untouched = SignalReport.objects.get(id=self.untouched_id)
        assert untouched.last_activity_at == _CREATED
        assert untouched.last_human_touch_at == _CREATED
        # A person-attributed artefact is what the human clock is seeded from.
        assert SignalReport.objects.get(id=self.touched_id).last_human_touch_at == self.touched_at
        # Terminal statuses are never swept, so they are not seeded either.
        assert SignalReport.objects.get(id=self.terminal_id).last_activity_at is None

        assert SignalTeamConfig.objects.get(id=self.opted_out_id).stale_report_sweep_enabled is False
