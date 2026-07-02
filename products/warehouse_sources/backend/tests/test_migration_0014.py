from typing import Any

from posthog.test.base import TestMigrations

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention


class BackfillS3FolderNameMigrationTest(TestMigrations):
    """The backfill must reproduce the exact folder the sync readers compute today, or existing
    Delta data is orphaned. Readers resolve `normalize_identifier(dwh_storage_key or name)`, so:
      - no legacy key (the vast majority of rows) -> the normalized schema name
      - a legacy key (rows migrated to multi-schema) -> the normalized key
    Every case below asserts the stored value equals that folder.
    """

    migrate_from = "0013_externaldataschema_s3_folder_name"
    migrate_to = "0014_backfill_externaldataschema_s3_folder_name"

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

        # No legacy key → folder is the normalized name. This is the common path (almost all sources).
        self.no_key = {
            "already_normalized": make("users", sync_type_config={}),
            "needs_casefold": make("MyTable", sync_type_config={}),
            "needs_space_strip": make("My Table", sync_type_config={}),
            "qualified_dotted": make("analytics.Events", sync_type_config={}),
            "null_key": make("orders", sync_type_config={"dwh_storage_key": None}),
            "empty_key": make("invoices", sync_type_config={"dwh_storage_key": ""}),
        }
        # Legacy key present (multi-schema migrated rows) → folder is the normalized key, pinning the
        # original pre-qualification path even though `name` is now qualified.
        self.with_key = {
            "key_normalized": make("public.users", sync_type_config={"dwh_storage_key": "users"}),
            "key_needs_norm": make("public.My Table", sync_type_config={"dwh_storage_key": "My Table"}),
        }
        # Already populated before the backfill — the NULL filter must skip it.
        self.preset = make("anything", sync_type_config={}, s3_folder_name="preset_value")

    @parameterized.expand(
        [
            ("already_normalized", "users", "users"),
            ("needs_casefold", "MyTable", "my_table"),
            ("needs_space_strip", "My Table", "my_table"),
            ("qualified_dotted", "analytics.Events", "analytics_events"),
            ("null_key", "orders", "orders"),
            ("empty_key", "invoices", "invoices"),
        ]
    )
    def test_no_key_uses_normalized_name(self, key: str, name: str, expected: str) -> None:
        schema = self.ExternalDataSchema.objects.get(id=self.no_key[key])
        # Equals both the hand-computed folder and the readers' own normalization of the name.
        assert schema.s3_folder_name == expected
        assert schema.s3_folder_name == NamingConvention.normalize_identifier(name)

    @parameterized.expand(
        [
            ("key_normalized", "users", "users"),
            ("key_needs_norm", "My Table", "my_table"),
        ]
    )
    def test_legacy_key_uses_normalized_key(self, key: str, legacy_key: str, expected: str) -> None:
        schema = self.ExternalDataSchema.objects.get(id=self.with_key[key])
        assert schema.s3_folder_name == expected
        assert schema.s3_folder_name == NamingConvention.normalize_identifier(legacy_key)

    def test_existing_value_is_not_overwritten(self) -> None:
        schema = self.ExternalDataSchema.objects.get(id=self.preset)
        assert schema.s3_folder_name == "preset_value"

    def test_every_row_is_populated(self) -> None:
        # The migration edits every row; none may be left NULL or a sync would orphan its data.
        assert not self.ExternalDataSchema.objects.filter(s3_folder_name__isnull=True).exists()
