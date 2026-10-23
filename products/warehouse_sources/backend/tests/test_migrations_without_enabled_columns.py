import importlib
from typing import Any

from posthog.test.base import BaseTest

from django.apps import apps
from django.db import connection

from parameterized import parameterized

from products.warehouse_sources.backend.models import ExternalDataSchema, ExternalDataSource


def _forwards(module_name: str) -> Any:
    return importlib.import_module(f"products.warehouse_sources.backend.migrations.{module_name}").forwards


class TestDataMigrationsWithoutEnabledColumns(BaseTest):
    @parameterized.expand(
        [
            (
                "0070_fix_stripe_incremental_fields",
                "Stripe",
                "Charge",
                {"incremental_field": "created_at"},
                {"incremental_field": "created", "incremental_field_type": "integer"},
            ),
            (
                "0120_fix_sentry_events_incremental_field",
                "Sentry",
                "issue_events",
                {"incremental_field": "dateCreated"},
                {"incremental_field": "dateReceived"},
            ),
            (
                "0157_reset_plausible_page_breakdowns",
                "Plausible",
                "entry_pages",
                {},
                {"reset_pipeline": True},
            ),
        ]
    )
    def test_repairs_schema_before_data_warehouse_adds_enabled_columns(
        self,
        module_name: str,
        source_type: str,
        schema_name: str,
        sync_type_config: dict[str, Any],
        expected: dict[str, Any],
    ) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source-id",
            connection_id="connection-id",
            status="Completed",
            source_type=source_type,
        )
        schema = ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name=schema_name,
            deleted=False,
            sync_type_config=sync_type_config,
        )

        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE posthog_externaldataschema DROP COLUMN enabled_columns")

        _forwards(module_name)(apps, None)

        with connection.cursor() as cursor:
            cursor.execute("SELECT sync_type_config FROM posthog_externaldataschema WHERE id = %s", [schema.id])
            row = cursor.fetchone()
        assert row is not None
        assert expected.items() <= row[0].items()
