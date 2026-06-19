from typing import Any

from posthog.test.base import TestMigrations


class BackfillDirectQueryEnabledMigrationTest(TestMigrations):
    """0028 defaults every row to True. The backfill must opt existing synced (warehouse) sources out so
    the direct-connect capability gate only lights up sources a user explicitly enables; direct sources
    keep True.
    """

    migrate_from = "0028_externaldatasource_direct_query_enabled"
    migrate_to = "0029_backfill_externaldatasource_direct_query_enabled"

    @property
    def app(self) -> str:
        return "warehouse_sources"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
        self.ExternalDataSource = ExternalDataSource

        org = Organization.objects.create(name="Org")
        project = Project.objects.create(id=999_999, organization=org, name="Proj")
        team = Team.objects.create(organization=org, project=project, name="Team")

        def make(access_method: str) -> str:
            return ExternalDataSource.objects.create(
                team=team,
                source_id="src",
                connection_id="conn",
                status="Completed",
                source_type="Postgres",
                access_method=access_method,
            ).id

        self.warehouse_id = make("warehouse")
        self.direct_id = make("direct")

    def test_warehouse_source_is_disabled(self) -> None:
        source = self.ExternalDataSource.objects.get(id=self.warehouse_id)
        assert source.direct_query_enabled is False

    def test_direct_source_stays_enabled(self) -> None:
        source = self.ExternalDataSource.objects.get(id=self.direct_id)
        assert source.direct_query_enabled is True
