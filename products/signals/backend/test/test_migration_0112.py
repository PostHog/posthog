from typing import Any

from posthog.test.base import NonAtomicTestMigrations


class BackfillSignalsResearchedMigrationTest(NonAtomicTestMigrations):
    """A researched report has to carry what its last pass covered, not 0.

    Left at 0 every report the inbox is already holding reads as never researched, so the next
    signal to arrive puts it at bucket 1 and re-researches the whole backlog. `signals_at_run` is
    the only surviving record of the count a past run started on, and every run stamps it as
    `signal_count + 3`.

    Non-atomic: rewinding to this migration has to reverse every later one, and the staleness
    indexes are created CONCURRENTLY, which an atomic rewind cannot replay.
    """

    migrate_from = "0111_signalreport_signals_researched"
    migrate_to = "0112_backfill_signals_researched"

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
        project = Project.objects.create(id=999995, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")

        def make_report(status: str, signal_count: int, signals_at_run: int) -> Any:
            return SignalReport.objects.create(
                team_id=team.id, status=status, signal_count=signal_count, signals_at_run=signals_at_run
            )

        self.researched_id = make_report("ready", 12, 10).id
        # A first pass that ran on a single signal: subtracting the stamp's increment underflows,
        # and 0 (never researched) is the only reading that does not skip bucket 1.
        self.early_id = make_report("ready", 4, 1).id
        self.never_ran_id = make_report("potential", 3, 0).id
        self.terminal_id = make_report("resolved", 8, 6).id

    def test_seeds_only_reports_whose_promotion_reads_the_count(self) -> None:
        assert self.apps is not None
        SignalReport = self.apps.get_model("signals", "SignalReport")

        # 10 - 3: the count the last run started on, so the next bucket is measured from there and
        # the 2 signals that landed since do not re-research the report on their own.
        assert SignalReport.objects.get(id=self.researched_id).signals_researched == 7
        assert SignalReport.objects.get(id=self.early_id).signals_researched == 0
        # `potential` promotes through the weight gate and `resolved` never reopens, so neither
        # reads the column and neither is seeded.
        assert SignalReport.objects.get(id=self.never_ran_id).signals_researched == 0
        assert SignalReport.objects.get(id=self.terminal_id).signals_researched == 0
