from typing import Any

from posthog.test.base import TestMigrations


class BackfillGoogleAdsIncrementalLookbackMigrationTest(TestMigrations):
    """0051 backfills a default incremental lookback onto existing Google Ads incremental stats
    schemas, which were created before the source set one and so re-fetch only the newest day,
    freezing every prior day at its first-imported, not-yet-final value. It must touch only Google
    Ads incremental schemas with no lookback yet — never full_refresh, never other sources, never a
    soft-deleted row, and never an explicit user value (including 0, which means "no overlap").
    """

    migrate_from = "0051_warehousecolumnstatistics"
    migrate_to = "0052_backfill_google_ads_incremental_lookback"

    DEFAULT = 30 * 24 * 60 * 60

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
        project = Project.objects.create(id=987_654, organization=org, name="Proj")
        team = Team.objects.create(organization=org, project=project, name="Team")

        google = ExternalDataSource.objects.create(
            team=team, source_id="g", connection_id="cg", status="Completed", source_type="GoogleAds"
        )
        postgres = ExternalDataSource.objects.create(
            team=team, source_id="p", connection_id="cp", status="Completed", source_type="Postgres"
        )

        incremental = {"incremental_field": "segments.date", "incremental_field_type": "date"}

        def make(source, name, sync_type, config, deleted=False) -> str:
            return ExternalDataSchema.objects.create(
                team=team, source=source, name=name, sync_type=sync_type, sync_type_config=config, deleted=deleted
            ).id

        self.needs_backfill_id = make(google, "campaign_stats", "incremental", {**incremental})
        self.explicit_value_id = make(
            google, "ad_stats", "incremental", {**incremental, "incremental_field_lookback_seconds": 86_400}
        )
        self.explicit_zero_id = make(
            google, "keyword_stats", "incremental", {**incremental, "incremental_field_lookback_seconds": 0}
        )
        self.full_refresh_id = make(google, "campaign", "full_refresh", {})
        self.other_source_id = make(
            postgres, "users", "incremental", {"incremental_field": "updated_at", "incremental_field_type": "timestamp"}
        )
        self.deleted_id = make(google, "video_stats", "incremental", {**incremental}, deleted=True)

    def _config(self, schema_id: str) -> dict:
        return self.ExternalDataSchema.objects.get(id=schema_id).sync_type_config

    def test_backfills_only_google_ads_incremental_schemas_missing_a_lookback(self) -> None:
        # The broken case the migration fixes: a Google Ads incremental schema with no lookback.
        assert self._config(self.needs_backfill_id)["incremental_field_lookback_seconds"] == self.DEFAULT

        # An explicit user value is preserved — including 0, which means "no overlap re-read".
        assert self._config(self.explicit_value_id)["incremental_field_lookback_seconds"] == 86_400
        assert self._config(self.explicit_zero_id)["incremental_field_lookback_seconds"] == 0

        # Untouched: full_refresh (lookback is a no-op there), other source types, soft-deleted rows.
        assert "incremental_field_lookback_seconds" not in self._config(self.full_refresh_id)
        assert "incremental_field_lookback_seconds" not in self._config(self.other_source_id)
        assert "incremental_field_lookback_seconds" not in self._config(self.deleted_id)
