import uuid
import importlib
from types import SimpleNamespace

import pytest

from django.apps import apps
from django.db import connection

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

migration_module = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0141_drop_backfilled_google_ads_lookback"
)
drop_backfilled_google_ads_lookback = migration_module.drop_backfilled_google_ads_lookback

BACKFILLED = migration_module.BACKFILLED_LOOKBACK_SECONDS
LOOKBACK_KEY = migration_module.LOOKBACK_KEY


def run_migration():
    # The migration only needs a connection off its schema_editor, and the historical models it
    # resolves are identical to the live ones for this data-only change.
    drop_backfilled_google_ads_lookback(apps, SimpleNamespace(connection=connection))


@pytest.fixture
def schema_factory(team):
    def _create(source_type, sync_type, config, deleted=False):
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type=source_type,
            job_inputs={},
        )
        return ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name=f"schema_{uuid.uuid4().hex[:8]}",
            sync_type=sync_type,
            sync_type_config=config,
            deleted=deleted,
        )

    return _create


def google_ads_stats_config(**overrides):
    return {"incremental_field": "segments.date", "incremental_field_type": "date", **overrides}


@pytest.mark.django_db
class TestDropBackfilledGoogleAdsLookback:
    def test_clears_the_backfilled_window_and_keeps_the_rest_of_the_config(self, schema_factory):
        # The regression: an account that never configured a lookback re-reads a trailing month on
        # every incremental run. Clearing the key must not disturb the cursor sitting beside it —
        # losing that would force the genuine full sync this migration exists to prevent.
        schema = schema_factory(
            "GoogleAds",
            "incremental",
            google_ads_stats_config(
                incremental_field_lookback_seconds=BACKFILLED,
                incremental_field_last_value="2026-08-01",
                primary_key_columns=["campaign_id", "segments.date"],
            ),
        )

        run_migration()

        schema.refresh_from_db()
        assert LOOKBACK_KEY not in schema.sync_type_config
        assert schema.sync_type_config["incremental_field_last_value"] == "2026-08-01"
        assert schema.sync_type_config["primary_key_columns"] == ["campaign_id", "segments.date"]
        assert schema.sync_type_config["incremental_field"] == "segments.date"

    def test_clears_soft_deleted_google_ads_schemas(self, schema_factory):
        # Deliberately wider than the 0052 backfill it undoes: the creation-path default reached
        # soft-deleted rows too, and a restored schema must not resume on the wide window.
        schema = schema_factory(
            "GoogleAds",
            "incremental",
            google_ads_stats_config(incremental_field_lookback_seconds=BACKFILLED),
            deleted=True,
        )

        run_migration()

        schema.refresh_from_db()
        assert LOOKBACK_KEY not in schema.sync_type_config

    @pytest.mark.parametrize(
        "source_type,sync_type,lookback,reason",
        [
            ("GoogleAds", "incremental", 3600, "a user-tuned window is not the backfilled value"),
            ("GoogleAds", "incremental", 0, "an explicit 0 means the user turned the re-read off"),
            ("GoogleAds", "full_refresh", BACKFILLED, "the lookback is a no-op on full_refresh"),
            ("Postgres", "incremental", BACKFILLED, "other source types were never backfilled"),
        ],
    )
    def test_leaves_other_schemas_untouched(self, schema_factory, source_type, sync_type, lookback, reason):
        schema = schema_factory(
            source_type,
            sync_type,
            google_ads_stats_config(incremental_field_lookback_seconds=lookback),
        )

        run_migration()

        schema.refresh_from_db()
        assert schema.sync_type_config[LOOKBACK_KEY] == lookback, reason

    def test_clears_every_row_past_one_batch_and_is_idempotent(self, schema_factory, monkeypatch):
        # The batched LIMIT loop relies on updated rows dropping out of the filter to advance. If that
        # ever stops holding, the loop either spins forever or leaves the tail of the fleet on the
        # wide window.
        monkeypatch.setattr(migration_module, "BATCH_SIZE", 2)
        schemas = [
            schema_factory(
                "GoogleAds",
                "incremental",
                google_ads_stats_config(incremental_field_lookback_seconds=BACKFILLED),
            )
            for _ in range(5)
        ]

        run_migration()
        run_migration()

        for schema in schemas:
            schema.refresh_from_db()
            assert LOOKBACK_KEY not in schema.sync_type_config
