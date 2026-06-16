from typing import Any

from posthog.test.base import TestMigrations

from parameterized import parameterized


class BackfillS3FolderNameMigrationTest(TestMigrations):
    migrate_from = "0010_externaldataschema_s3_folder_name"
    migrate_to = "0011_backfill_externaldataschema_s3_folder_name"

    @property
    def app(self) -> str:
        return "warehouse_sources"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
        ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")
        self.ExternalDataSchema = ExternalDataSchema

        org = Organization.objects.create(name="Org")
        project = Project.objects.create(id=999_999, organization=org, name="Proj")
        team = Team.objects.create(organization=org, project=project, name="Team")
        source = ExternalDataSource.objects.create(
            team=team, source_id="src", connection_id="conn", status="Completed", source_type="Postgres"
        )

        def make(name: str, **kwargs: Any) -> str:
            return ExternalDataSchema.objects.create(team=team, source=source, name=name, **kwargs).id

        self.ids = {
            # Migrated row: dwh_storage_key pins the original pre-qualification folder.
            "legacy_key": make("public.users", sync_type_config={"dwh_storage_key": "users"}),
            # Legacy key that isn't already normalized.
            "legacy_key_unnormalized": make("public.My Table", sync_type_config={"dwh_storage_key": "My Table"}),
            # Plain never-migrated row, name already normalized.
            "plain": make("orders", sync_type_config={}),
            # Never-migrated row whose raw name needs normalizing — the case raw `schema.name` got wrong.
            "needs_normalize": make("My Table", sync_type_config={}),
            # Qualified dotted name, no legacy key.
            "dotted": make("analytics.Events", sync_type_config={}),
            # Already populated before the backfill — must be left untouched.
            "preset": make("anything", sync_type_config={}, s3_folder_name="preset_value"),
        }

    @parameterized.expand(
        [
            ("legacy_key", "users"),
            ("legacy_key_unnormalized", "my_table"),
            ("plain", "orders"),
            ("needs_normalize", "my_table"),
            ("dotted", "analytics_events"),
            ("preset", "preset_value"),
        ]
    )
    def test_s3_folder_name_backfilled(self, key: str, expected: str) -> None:
        schema = self.ExternalDataSchema.objects.get(id=self.ids[key])
        assert schema.s3_folder_name == expected

    def test_every_row_populated(self) -> None:
        # The migration edits every row; none should be left NULL.
        assert not self.ExternalDataSchema.objects.filter(s3_folder_name__isnull=True).exists()
