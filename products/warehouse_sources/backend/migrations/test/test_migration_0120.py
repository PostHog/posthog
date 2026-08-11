import importlib

import pytest

from django.apps import apps

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

migration_module = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0120_fix_sentry_events_incremental_field"
)
forwards = migration_module.forwards


@pytest.fixture
def schema_factory(team):
    def _create(source_type, schema_name, incremental_field):
        source = ExternalDataSource.objects.create(
            source_id="src", connection_id="conn", team=team, source_type=source_type
        )
        return ExternalDataSchema.objects.create(
            name=schema_name,
            team=team,
            source=source,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": incremental_field},
        )

    return _create


@pytest.mark.django_db
class TestFixSentryEventsIncrementalField:
    @pytest.mark.parametrize(
        "source_type, schema_name, incremental_field, expected",
        [
            ("Sentry", "issue_events", "dateCreated", "dateReceived"),  # broken value gets fixed
            ("Sentry", "project_events", "dateCreated", "dateReceived"),  # both affected schemas fixed
            ("Sentry", "issue_events", "dateReceived", "dateReceived"),  # already-correct value untouched
            ("Sentry", "issues", "lastSeen", "lastSeen"),  # unrelated schema name untouched
            ("Stripe", "issue_events", "dateCreated", "dateCreated"),  # unrelated source type untouched
        ],
    )
    def test_forwards(self, schema_factory, source_type, schema_name, incremental_field, expected):
        schema = schema_factory(source_type, schema_name, incremental_field)

        forwards(apps, None)
        forwards(apps, None)  # idempotent

        schema.refresh_from_db()
        assert schema.sync_type_config["incremental_field"] == expected
