"""External schema API tests."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from django.conf import settings

import psycopg
import pytest_asyncio
from asgiref.sync import sync_to_async
from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.data_warehouse.backend.facade.contracts import WebhookHogFunctionCreateResult
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    WebhookCreationResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.source import RedshiftSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source import StripeSource


@pytest.fixture
def postgres_config():
    return {
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "database": "external_data_database",
        "schema": "external_data_schema",
        "host": settings.PG_HOST,
        "port": int(settings.PG_PORT),
    }


@pytest_asyncio.fixture
async def postgres_connection(postgres_config, setup_postgres_test_db):
    if setup_postgres_test_db:
        await anext(setup_postgres_test_db)

    connection = await psycopg.AsyncConnection.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        dbname=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
    )

    yield connection

    await connection.close()


pytestmark = [pytest.mark.django_db]


@pytest.mark.usefixtures("postgres_connection", "postgres_config")
class TestExternalDataSchema(APIBaseTest):
    @pytest.fixture(autouse=True)
    def _setup(self, postgres_connection, postgres_config, temporal):
        self.postgres_connection = postgres_connection
        self.postgres_config = postgres_config
        self.temporal = temporal

    def test_incremental_fields_stripe(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        with mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )
        payload = response.json()

        assert payload == {
            "incremental_fields": [
                {"label": "created_at", "type": "datetime", "field": "created", "field_type": "integer"}
            ],
            "incremental_available": False,
            "append_available": True,
            "cdc_available": None,
            "xmin_available": None,
            "full_refresh_available": True,
            "supports_webhooks": True,
            "webhook_only": False,
            "available_columns": [],
            "detected_primary_keys": None,
        }

    @parameterized.expand(
        [
            ("expected_source_error", Exception("Invalid API Key provided"), False),
            ("unclassified_error", RuntimeError("schema parser exploded"), True),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.capture_exception")
    def test_incremental_fields_capture_depends_on_non_retryable_classification(
        self, _name, raised_exception, should_capture, mock_capture_exception
    ):
        # `validate_credentials` above this call already probed the same connection successfully, so
        # a failure the source itself classifies as non-retryable (e.g. bad credentials, an
        # unreachable host) is an expected customer/upstream condition and must not flood error
        # tracking - mirrors `refresh_schemas`'s equivalent classification.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        with (
            mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(StripeSource, "get_schemas", side_effect=raised_exception),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )

        assert response.status_code == 400
        assert response.json()["message"] == str(raised_exception)
        assert mock_capture_exception.called is should_capture

    def test_incremental_fields_probe_uses_schema_pin_over_source_pin(self):
        # A schema-level api_version override must win over the source pin in capability probes,
        # matching sync-time precedence — consolidating probe callers to the source pin would
        # silently ignore overrides and no other test would fail.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
            api_version="v-source-pin",
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            api_version="v-schema-pin",
        )
        with (
            mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)) as validate,
            mock.patch.object(StripeSource, "get_schemas", return_value=[]) as get_schemas,
        ):
            self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )
        assert validate.call_args.kwargs["api_version"] == "v-schema-pin"
        assert get_schemas.call_args_list, "expected the probe to run discovery"
        assert all(c.kwargs["api_version"] == "v-schema-pin" for c in get_schemas.call_args_list)

    def test_sync_type_gate_probes_under_incoming_api_version(self):
        # A PATCH changing api_version and sync_type together must gate capabilities under the
        # incoming version (what the schema will sync with), not the stored one.
        current_version = StripeSource().supported_versions[0]
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            api_version="v-retired-pin",
        )
        with mock.patch.object(StripeSource, "get_schemas", return_value=[]) as get_schemas:
            self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/",
                data={"sync_type": "full_refresh", "api_version": current_version},
            )
        assert get_schemas.call_args_list, "expected the webhook-only gate to probe discovery"
        assert all(c.kwargs["api_version"] == current_version for c in get_schemas.call_args_list)

    def test_incremental_fields_missing_source_type(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="bad_source",
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )

        assert response.status_code == 400

    def test_incremental_fields_missing_table_name(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="Some_other_non_existent_table",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_incremental_fields_postgres(self):
        if not isinstance(self.postgres_connection, psycopg.AsyncConnection):
            postgres_connection: psycopg.AsyncConnection = await anext(self.postgres_connection)
        else:
            postgres_connection = self.postgres_connection

        await postgres_connection.execute(
            "CREATE TABLE IF NOT EXISTS {schema}.posthog_test (id integer)".format(
                schema=self.postgres_config["schema"]
            )
        )
        await postgres_connection.execute(
            "INSERT INTO {schema}.posthog_test (id) VALUES (1)".format(schema=self.postgres_config["schema"])
        )
        await postgres_connection.commit()

        source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=self.team,
            status="running",
            source_type="Postgres",
            job_inputs={
                "host": self.postgres_config["host"],
                "port": self.postgres_config["port"],
                "database": self.postgres_config["database"],
                "user": self.postgres_config["user"],
                "password": self.postgres_config["password"],
                "schema": self.postgres_config["schema"],
                "ssh_tunnel_enabled": False,
            },
        )

        schema = await sync_to_async(ExternalDataSchema.objects.create)(
            name="posthog_test",
            team=self.team,
            source=source,
        )

        response = await sync_to_async(self.client.post)(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )
        payload = response.json()

        assert payload == {
            "incremental_fields": [
                {
                    "label": "id",
                    "type": "integer",
                    "field": "id",
                    "field_type": "integer",
                    "nullable": True,
                    # Table has no index on `id`, so the warning UI will fire for this field.
                    "is_indexed": False,
                },
                # xmin is synthetic: advertised for any ordinary PG13+ table, unindexed by definition.
                {
                    "label": "xmin",
                    "type": "xid",
                    "field": "xmin",
                    "field_type": "xid",
                    "is_indexed": False,
                },
            ],
            "incremental_available": True,
            "append_available": True,
            "cdc_available": None,
            "xmin_available": True,
            "full_refresh_available": True,
            "supports_webhooks": False,
            "webhook_only": False,
            "available_columns": [
                {"field": "id", "label": "id", "type": "integer", "nullable": True},
            ],
            "detected_primary_keys": ["id"],
        }

    @parameterized.expand(
        [
            # (test name, source_cdc_enabled, team_ff_enabled, expected_cdc_available)
            ("source_enabled_team_enabled", True, True, True),
            ("source_enabled_team_disabled", True, False, None),
            ("source_disabled_team_enabled", False, True, None),
            ("source_disabled_team_disabled", False, False, None),
        ]
    )
    def test_incremental_fields_cdc_available_gating(
        self, _name: str, source_cdc_enabled: bool, team_ff_enabled: bool, expected_cdc_available
    ):
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

        job_inputs = {
            "host": "localhost",
            "port": 5432,
            "database": "postgres",
            "user": "postgres",
            "password": "postgres",
            "schema": "public",
            "ssh_tunnel_enabled": False,
        }
        if source_cdc_enabled:
            job_inputs["cdc_enabled"] = True

        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="Postgres",
            job_inputs=job_inputs,
        )
        schema = ExternalDataSchema.objects.create(
            name="some_table",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        fake_schema = SourceSchema(
            name="some_table",
            supports_incremental=False,
            supports_append=False,
            supports_cdc=True,
            incremental_fields=[],
            columns=[("id", "integer", False)],
            detected_primary_keys=["id"],
        )

        with (
            mock.patch.object(PostgresSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(PostgresSource, "get_schemas", return_value=[fake_schema]),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.viewset.is_cdc_enabled_for_team",
                return_value=team_ff_enabled,
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["cdc_available"] is expected_cdc_available

    @parameterized.expand(
        [
            # (test name, source_type, supports_xmin, expected_xmin_available)
            ("postgres_capable", ExternalDataSourceType.POSTGRES, True, True),
            ("postgres_not_capable", ExternalDataSourceType.POSTGRES, False, False),
            ("non_postgres_capable", ExternalDataSourceType.MYSQL, True, None),
        ]
    )
    def test_incremental_fields_xmin_available_gating(
        self, _name: str, source_type, supports_xmin: bool, expected_xmin_available
    ):
        # xmin is Postgres-only: the endpoint must report `xmin_available=None` for any other source,
        # even one that erroneously sets `supports_xmin=True`.
        from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source import MySQLSource
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

        source_impl = PostgresSource if source_type == ExternalDataSourceType.POSTGRES else MySQLSource
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=source_type,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="some_table",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        fake_schema = SourceSchema(
            name="some_table",
            supports_incremental=False,
            supports_append=False,
            supports_xmin=supports_xmin,
            incremental_fields=[],
            columns=[("id", "integer", False)],
            detected_primary_keys=["id"],
        )

        with (
            mock.patch.object(source_impl, "validate_credentials", return_value=(True, None)),
            mock.patch.object(source_impl, "get_schemas", return_value=[fake_schema]),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["xmin_available"] is expected_xmin_available

    def test_incremental_fields_matches_schema_by_name(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="C123",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
        )

        # Mimics sources (e.g. Slack) that ignore `names` and return every schema. The first
        # element is an unrelated table; the endpoint must pick the one matching instance.name.
        all_schemas = [
            SourceSchema(name="$channels", supports_incremental=False, supports_append=False, supports_webhooks=False),
            SourceSchema(name="C123", supports_incremental=False, supports_append=False, supports_webhooks=True),
        ]

        with (
            mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(StripeSource, "get_schemas", return_value=all_schemas),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["supports_webhooks"] is True

    @parameterized.expand(
        [
            (
                "empty_discovery",
                RedshiftSource,
                [],
                "Could not discover schema C999. The connection may be missing SELECT or schema access privileges, "
                "or discovery may not support this relation type. Check that the relation exists, restore read "
                "privileges, or expose it as a supported table or view, then try again.",
            ),
            (
                "nonempty_discovery",
                RedshiftSource,
                [SourceSchema(name="$channels", supports_incremental=False, supports_append=False)],
                "Schema with name C999 not found",
            ),
            (
                "nonempty_api_discovery",
                StripeSource,
                [SourceSchema(name="$channels", supports_incremental=False, supports_append=False)],
                "Schema with name C999 not found",
            ),
        ]
    )
    def test_incremental_fields_returns_400_when_schema_name_absent(
        self, _name, source_class, discovered_schemas, expected_message
    ):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=source_class().source_type,
            job_inputs={
                "host": "localhost",
                "port": 5439,
                "database": "dev",
                "user": "test",
                "password": "test",
                "schema": "public",
            }
            if source_class is RedshiftSource
            else {"stripe_secret_key": "test_key"},
        )
        schema = ExternalDataSchema.objects.create(
            name="C999",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
        )

        with (
            mock.patch.object(source_class, "validate_credentials", return_value=(True, None)),
            mock.patch.object(source_class, "get_schemas", return_value=discovered_schemas),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {"message": expected_message}

    def test_update_schema_change_sync_type(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_time_of_day="12:00:00",
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ) as mock_trigger_external_data_workflow,
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )

            assert response.status_code == 200
            mock_trigger_external_data_workflow.assert_not_called()
            schema.refresh_from_db()
            assert schema.sync_type_config.get("reset_pipeline") is None
            assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_sync_type_is_logged_to_activity(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )
            assert response.status_code == 200

        logs = ActivityLog.objects.filter(scope="ExternalDataSchema", item_id=str(schema.id), activity="updated")
        sync_type_changes = [
            c for log in logs for c in (log.detail or {}).get("changes", []) if c["field"] == "sync_type"
        ]
        assert sync_type_changes == [
            {
                "type": "ExternalDataSchema",
                "field": "sync_type",
                "action": "changed",
                "before": "incremental",
                "after": "full_refresh",
            }
        ]

    def test_update_schema_sets_and_clears_incremental_field_lookback_seconds(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={
                    "sync_type": "incremental",
                    "incremental_field": "updated_at",
                    "incremental_field_type": "timestamp",
                    "incremental_field_lookback_seconds": 3600,
                },
            )
            assert response.status_code == 200, response.json()
            assert response.json()["incremental_field_lookback_seconds"] == 3600
            schema.refresh_from_db()
            assert schema.sync_type_config["incremental_field_lookback_seconds"] == 3600

            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={
                    "sync_type": "incremental",
                    "incremental_field": "updated_at",
                    "incremental_field_type": "timestamp",
                    "incremental_field_lookback_seconds": None,
                },
            )
            assert response.status_code == 200, response.json()
            assert response.json()["incremental_field_lookback_seconds"] is None
            schema.refresh_from_db()
            assert schema.sync_type_config["incremental_field_lookback_seconds"] is None

    def test_update_incremental_field_without_sync_type_persists(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field": "created_at",
                "incremental_field_type": "timestamp",
                "incremental_field_last_value": "2026-06-14T15:33:31.802833",
            },
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            # A bare incremental_field edit — no sync_type re-sent — must actually persist, not just
            # echo the submitted value back in the response.
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"incremental_field": "updated_at"},
            )

            assert response.status_code == 200, response.json()
            assert response.json()["incremental_field"] == "updated_at"
            schema.refresh_from_db()
            assert schema.sync_type_config["incremental_field"] == "updated_at"

    def test_update_incremental_field_on_non_incremental_schema_errors(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            # Seed leftover config so the post-request assertion catches a regression that writes the
            # value rather than leaving it untouched (a missing key would pass trivially).
            sync_type_config={"incremental_field": "old_value", "primary_key_columns": ["id"]},
        )

        # Setting incremental_field on a full_refresh schema without switching sync_type can't be
        # applied — it must fail loudly instead of returning 200 and dropping the change.
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"incremental_field": "updated_at"},
        )

        assert response.status_code == 400, response.json()
        schema.refresh_from_db()
        assert schema.sync_type_config.get("incremental_field") == "old_value"

        # primary_key_columns is dropped the same way on a non-incremental schema, so it errors too.
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"primary_key_columns": ["other_id"]},
        )

        assert response.status_code == 400, response.json()
        schema.refresh_from_db()
        assert schema.sync_type_config.get("primary_key_columns") == ["id"]

    def test_incremental_field_lookback_seconds_survives_reset(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field": "updated_at",
                "incremental_field_type": "timestamp",
                "incremental_field_last_value": "2026-06-14T15:33:31.802833",
                "incremental_field_lookback_seconds": 7200,
            },
        )

        schema.update_sync_type_config_for_reset_pipeline()

        schema.refresh_from_db()
        assert "incremental_field_last_value" not in schema.sync_type_config
        assert schema.sync_type_config["incremental_field_lookback_seconds"] == 7200

    def test_create_source_persists_lookback_for_incremental_omits_for_non_incremental(self):
        incremental_schema = SourceSchema(
            name="Orders",
            supports_incremental=True,
            supports_append=False,
            supports_webhooks=False,
        )
        full_refresh_schema = SourceSchema(
            name="Products",
            supports_incremental=False,
            supports_append=False,
            supports_webhooks=False,
        )

        with (
            mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(StripeSource, "get_schemas", return_value=[incremental_schema, full_refresh_schema]),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "source_type": "Stripe",
                    "payload": {
                        "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                        "schemas": [
                            {
                                "name": "Orders",
                                "should_sync": True,
                                "sync_type": "incremental",
                                "incremental_field": "updated_at",
                                "incremental_field_type": "timestamp",
                                "incremental_field_lookback_seconds": 3600,
                            },
                            {
                                "name": "Products",
                                "should_sync": True,
                                "sync_type": "full_refresh",
                                "incremental_field_lookback_seconds": 3600,
                            },
                        ],
                    },
                },
                content_type="application/json",
            )

        assert response.status_code == 201, response.json()

        incremental = ExternalDataSchema.objects.get(
            source__team=self.team, name="Orders", sync_type=ExternalDataSchema.SyncType.INCREMENTAL
        )
        assert incremental.sync_type_config["incremental_field_lookback_seconds"] == 3600

        full_refresh = ExternalDataSchema.objects.get(
            source__team=self.team, name="Products", sync_type=ExternalDataSchema.SyncType.FULL_REFRESH
        )
        assert "incremental_field_lookback_seconds" not in full_refresh.sync_type_config

    def test_update_schema_rejects_lookback_above_60_days(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={
                    "sync_type": "incremental",
                    "incremental_field": "updated_at",
                    "incremental_field_type": "timestamp",
                    "incremental_field_lookback_seconds": 5_184_001,  # 60 days + 1 second
                },
            )

        assert response.status_code == 400

    def test_create_source_rejects_lookback_above_60_days(self):
        incremental_schema = SourceSchema(
            name="Orders",
            supports_incremental=True,
            supports_append=False,
            supports_webhooks=False,
        )

        with (
            mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(StripeSource, "get_schemas", return_value=[incremental_schema]),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "source_type": "Stripe",
                    "payload": {
                        "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                        "schemas": [
                            {
                                "name": "Orders",
                                "should_sync": True,
                                "sync_type": "incremental",
                                "incremental_field": "updated_at",
                                "incremental_field_type": "timestamp",
                                "incremental_field_lookback_seconds": 5_184_001,  # 60 days + 1 second
                            },
                        ],
                    },
                },
                content_type="application/json",
            )

        assert response.status_code == 400
        assert "5184000" in response.json().get("message", "")
        assert not ExternalDataSource.objects.filter(team=self.team, source_type="Stripe").exists()

    @parameterized.expand(
        [
            # Stored PK from earlier discovery — reuse it; no caller override needed.
            (
                "reuses_stored_primary_key",
                {"primary_key_columns": ["id"], "schema_metadata": {}},
                None,
                status.HTTP_200_OK,
                ExternalDataSchema.SyncType.CDC,
                ["id"],
            ),
            # Caller explicitly provides PK — takes precedence over (and persists alongside)
            # whatever was stored.
            (
                "caller_override_wins",
                {"primary_key_columns": ["old"], "schema_metadata": {}},
                ["new_pk"],
                status.HTTP_200_OK,
                ExternalDataSchema.SyncType.CDC,
                ["new_pk"],
            ),
            # No stored PK, no override → refuse the switch.
            (
                "rejects_when_no_primary_key_available",
                {"schema_metadata": {}},
                None,
                status.HTTP_400_BAD_REQUEST,
                ExternalDataSchema.SyncType.FULL_REFRESH,
                None,
            ),
        ]
    )
    def test_update_schema_to_cdc(
        self,
        _name: str,
        initial_sync_type_config: dict,
        payload_pk: list[str] | None,
        expected_status: int,
        expected_sync_type: str,
        expected_pk_columns: list[str] | None,
    ):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="quotes",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config=initial_sync_type_config,
        )

        request_body: dict[str, Any] = {"sync_type": "cdc"}
        if payload_pk is not None:
            request_body["primary_key_columns"] = payload_pk

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.is_cdc_enabled_for_team",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data=request_body,
            )

        assert response.status_code == expected_status, response.content
        if expected_status == status.HTTP_400_BAD_REQUEST:
            assert "primary key" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.sync_type == expected_sync_type
        if expected_pk_columns is not None:
            assert schema.sync_type_config["primary_key_columns"] == expected_pk_columns
            assert schema.sync_type_config["cdc_mode"] == "snapshot"

    def test_update_cdc_schema_rejects_primary_key_change_with_existing_data(self):
        # CDC uses the PK as the UPDATE/DELETE merge key, so — same as incremental — it can't be
        # changed once data has synced (the schema has a materialized table).
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_mode": "streaming", "primary_key_columns": ["id"]},
            table=table,
        )

        with mock.patch(
            "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.is_cdc_enabled_for_team",
            return_value=True,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "cdc", "primary_key_columns": ["order_key"]},
            )

        assert response.status_code == 400
        assert "primary key cannot be changed" in str(response.json()).lower()

        schema.refresh_from_db()
        assert schema.sync_type_config["primary_key_columns"] == ["id"]

    def _xmin_postgres_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )

    @staticmethod
    def _xmin_discovery_patch(supports_xmin: bool = True):
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

        fake_schema = SourceSchema(
            name="public.orders",
            supports_incremental=False,
            supports_append=False,
            supports_xmin=supports_xmin,
            incremental_fields=[],
            columns=[("id", "integer", False)],
            detected_primary_keys=["id"],
        )
        return mock.patch.object(PostgresSource, "get_schemas", return_value=[fake_schema])

    def test_update_schema_to_xmin_succeeds_with_primary_key(self):
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={},
        )

        with self._xmin_discovery_patch():
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"]},
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.XMIN
        assert schema.sync_type_config["primary_key_columns"] == ["id"]
        # xmin never sets CDC state.
        assert "cdc_mode" not in schema.sync_type_config

    def test_update_schema_to_xmin_rejected_without_primary_key(self):
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={},
        )

        with self._xmin_discovery_patch():
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin"},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "primary key" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_to_xmin_rejected_for_non_postgres(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.MYSQL,
            job_inputs={"host": "h", "port": 3306, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={"primary_key_columns": ["id"]},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"sync_type": "xmin", "primary_key_columns": ["id"]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "postgres" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_to_xmin_rejected_when_table_not_capable(self):
        # A plain view / partitioned parent reports supports_xmin=False — reject even with a PK.
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={"primary_key_columns": ["id"]},
        )

        with self._xmin_discovery_patch(supports_xmin=False):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"]},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not available" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_xmin_accepts_row_filters(self):
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.XMIN,
            sync_type_config={
                "primary_key_columns": ["id"],
                "schema_metadata": {"columns": [{"name": "id", "data_type": "integer", "is_nullable": False}]},
            },
        )

        with self._xmin_discovery_patch():
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"row_filters": [{"column": "id", "operator": ">", "value": "5"}]},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        schema.refresh_from_db()
        assert schema.row_filters == [{"column": "id", "operator": ">", "value": "5"}]

    @parameterized.expand(
        [
            ("one_minute_rejected", "1min", 400),
            ("five_minute_accepted", "5min", 200),
        ]
    )
    def test_update_schema_xmin_floors_at_five_minutes(self, _name, sync_frequency, expected_status):
        # xmin floors at the 5-minute minimum like every other sync type.
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.XMIN,
            sync_type_config={"primary_key_columns": ["id"]},
        )

        with (
            self._xmin_discovery_patch(),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow"
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"], "sync_frequency": sync_frequency},
            )

        assert response.status_code == expected_status, response.content
        if expected_status == 400:
            assert "not a valid sync frequency" in str(response.json()).lower()

    def test_update_schema_to_xmin_forces_full_resync(self):
        # Switching to xmin from another strategy adds the `_ph_xmin` control column to the physical
        # schema, so the existing Delta table must be rebuilt — force a full resync.
        source = self._xmin_postgres_source()
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={"primary_key_columns": ["id"]},
            table=table,
        )

        with (
            self._xmin_discovery_patch(),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ) as mock_trigger,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"]},
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.XMIN
        assert schema.sync_type_config.get("reset_pipeline") is True
        mock_trigger.assert_called_once()

    def test_update_schema_from_xmin_forces_full_resync(self):
        # Leaving xmin for another strategy must also rebuild the table — the lingering `_ph_xmin`
        # column would otherwise break the incremental write.
        source = self._xmin_postgres_source()
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.XMIN,
            sync_type_config={"primary_key_columns": ["id"], "xmin_last_value": 123},
            table=table,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ) as mock_trigger,
            mock.patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "incremental", "incremental_field": "id", "incremental_field_type": "integer"},
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.INCREMENTAL
        assert schema.sync_type_config.get("reset_pipeline") is True
        mock_trigger.assert_called_once()

    @parameterized.expand(
        [
            ("incremental_one_minute", ExternalDataSchema.SyncType.INCREMENTAL, "1min", 400),
            ("full_refresh_one_minute", ExternalDataSchema.SyncType.FULL_REFRESH, "1min", 400),
            ("cdc_one_minute", ExternalDataSchema.SyncType.CDC, "1min", 400),
            ("cdc_five_minutes", ExternalDataSchema.SyncType.CDC, "5min", 200),
        ]
    )
    def test_update_schema_sync_frequency_floors_at_five_minutes(
        self, _name, sync_type, sync_frequency, expected_status
    ):
        # The 5-minute floor applies to every sync type, CDC included. The backend must enforce it
        # regardless of caller (UI, API, or MCP).
        is_cdc = sync_type == ExternalDataSchema.SyncType.CDC
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES if is_cdc else ExternalDataSourceType.STRIPE,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=sync_type,
            sync_type_config={"primary_key_columns": ["id"]} if is_cdc else {},
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.is_cdc_enabled_for_team",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow"
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_cdc_extraction_schedule"
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_frequency": sync_frequency},
            )

        assert response.status_code == expected_status, response.content
        if expected_status == 400:
            assert "not a valid sync frequency" in str(response.json()).lower()
            schema.refresh_from_db()
            # Rejected before the interval is persisted.
            assert schema.sync_frequency_interval != timedelta(minutes=1)

    def test_update_schema_one_minute_clamps_on_switch_away_from_cdc(self):
        # A schema whose stored interval predates the 5-minute floor (a legacy 1-minute CDC row)
        # switched to a non-CDC sync type without re-sending sync_frequency must not dead-end:
        # the inherited cadence is clamped to the floor so the switch goes through.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"primary_key_columns": ["id"]},
            sync_frequency_interval=timedelta(minutes=1),
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow"
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_cdc_extraction_schedule"
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )

        assert response.status_code == 200, response.content
        schema.refresh_from_db()
        assert schema.sync_frequency_interval == timedelta(minutes=5)
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_stored_one_minute_interval_still_deserializes(self):
        # Rows written before the 5-minute floor still carry a 1-minute interval until the
        # migration command runs. Reading them must keep working, or every list/retrieve
        # containing such a row 500s.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"primary_key_columns": ["id"]},
            sync_frequency_interval=timedelta(minutes=1),
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}")

        assert response.status_code == 200, response.content
        assert response.json()["sync_frequency"] == "1min"

    def test_update_schema_frequency_on_disabled_schema_does_not_touch_missing_schedule(self):
        # A disabled / never-activated schema has no Temporal schedule. Changing its sync frequency
        # must not try to update a schedule that doesn't exist (which raises "workflow not found");
        # the new frequency is just saved, to apply if/when the schema is enabled.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_frequency_interval=timedelta(hours=6),
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow"
            ) as mock_sync_workflow,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_frequency": "30day"},
            )

        assert response.status_code == 200, response.content
        # The frequency is saved...
        schema.refresh_from_db()
        assert schema.sync_frequency_interval == timedelta(days=30)
        # ...but no schedule create/update is attempted, because the schema has no schedule to touch.
        mock_sync_workflow.assert_not_called()

    def test_update_schema_frequency_on_enabled_schema_without_schedule_creates_it(self):
        # An enabled schema whose Temporal schedule is missing should have it created when the
        # cadence is edited (even when should_sync isn't re-sent), not left silently unscheduled.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_frequency_interval=timedelta(hours=6),
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow"
            ) as mock_sync_workflow,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_frequency": "30day"},
            )

        assert response.status_code == 200, response.content
        schema.refresh_from_db()
        assert schema.sync_frequency_interval == timedelta(days=30)
        # The missing schedule is created (recovered) with the new cadence, not left absent.
        mock_sync_workflow.assert_called_once()
        assert mock_sync_workflow.call_args.kwargs["create"] is True

    def test_update_schema_enable_should_sync_rejects_cdc_without_primary_key(self):
        # Schemas already in CDC mode with an empty primary_key_columns (created before the
        # API gate landed) must not be re-enabled until a PK is added on the source side.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="tracking_link",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_mode": "snapshot", "primary_key_columns": []},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"should_sync": True},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "primary key" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.should_sync is False

    @parameterized.expand(
        [ExternalDataSchema.SyncType.APPEND, ExternalDataSchema.SyncType.INCREMENTAL],
    )
    def test_update_schema_to_webhook_does_not_reset_pipeline(self, from_sync_type):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=from_sync_type,
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "incremental_field_last_value": 1000,
                "incremental_field_earliest_value": 500,
            },
            table=table,
        )

        mock_hog_fn_result = WebhookHogFunctionCreateResult(
            hog_function_id=str(uuid.uuid4()),
            webhook_url="https://test.com/webhook",
            hog_function_created=False,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ) as mock_trigger_external_data_workflow,
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ),
        ):
            # The frontend sends null incremental fields alongside the switch — they must not
            # wipe the cursor config, or the webhook initial sync degrades to an unbounded
            # full-history scan with no durable watermark progress.
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": None, "incremental_field_type": None},
            )

            assert response.status_code == 200
            mock_trigger_external_data_workflow.assert_not_called()

            schema.refresh_from_db()

            assert schema.sync_type == ExternalDataSchema.SyncType.WEBHOOK
            assert schema.sync_type_config.get("reset_pipeline") is None
            assert schema.sync_type_config.get("incremental_field") == "created"
            assert schema.sync_type_config.get("incremental_field_type") == "integer"
            assert schema.sync_type_config.get("incremental_field_last_value") == 1000
            assert schema.sync_type_config.get("incremental_field_earliest_value") == 500

    def test_update_schema_change_sync_type_incremental_field(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "some_other_field", "incremental_field_type": "integer"},
            table=table,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow"
            ) as mock_trigger_external_data_workflow,
            mock.patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "incremental", "incremental_field": "field", "incremental_field_type": "integer"},
            )

            assert response.status_code == 200
            mock_trigger_external_data_workflow.assert_not_called()

            schema.refresh_from_db()

            assert schema.sync_type_config.get("reset_pipeline") is None
            assert schema.sync_type_config.get("incremental_field") == "field"
            assert schema.sync_type_config.get("incremental_field_type") == "integer"
            assert schema.sync_type_config.get("incremental_field_last_value") == 1

    def test_update_schema_with_primary_key_columns(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={
                "sync_type": "incremental",
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["_id", "source_id"],
            },
        )

        assert response.status_code == 200

        schema.refresh_from_db()

        assert schema.sync_type_config.get("primary_key_columns") == ["_id", "source_id"]
        assert schema.primary_key_columns == ["_id", "source_id"]

    @parameterized.expand(
        [
            ("swapping_an_established_key_is_rejected", ["id"], 400, ["id"]),
            ("setting_the_first_key_is_allowed", None, 200, ["_id"]),
        ]
    )
    def test_update_schema_primary_key_change_with_existing_data(
        self, _name: str, stored_pk: list[str] | None, expected_status: int, expected_pk: list[str]
    ):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "incremental_field_last_value": 1,
                **({"primary_key_columns": stored_pk} if stored_pk else {}),
            },
            table=table,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={
                "sync_type": "incremental",
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["_id"],
            },
        )

        assert response.status_code == expected_status

        schema.refresh_from_db()
        assert schema.sync_type_config.get("primary_key_columns") == expected_pk

    def test_update_schema_primary_key_columns_not_reset_on_full_refresh(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["_id"],
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"sync_type": "full_refresh"},
        )

        assert response.status_code == 200

        schema.refresh_from_db()

        assert schema.sync_type_config.get("primary_key_columns") == ["_id"]

    def test_switch_synced_incremental_schema_to_append_with_existing_pk(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["id"],
            },
            table=table,
        )

        with mock.patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={
                    "sync_type": "append",
                    "incremental_field": "created",
                    "incremental_field_type": "integer",
                    "primary_key_columns": None,
                },
            )

            assert response.status_code == 200

            schema.refresh_from_db()
            assert schema.sync_type == ExternalDataSchema.SyncType.APPEND
            assert schema.sync_type_config.get("primary_key_columns") is None

    def test_primary_key_columns_returned_in_serializer(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["_id"],
            },
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_schemas/",
        )

        assert response.status_code == 200
        assert response.json()["results"][0]["primary_key_columns"] == ["_id"]

    def test_update_schema_to_webhook_triggers_webhook_creation(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        mock_hog_fn_result = WebhookHogFunctionCreateResult(
            hog_function_id=str(uuid.uuid4()),
            webhook_url="https://test.com/webhook",
            hog_function_created=True,
        )
        mock_webhook_schemas = [
            SourceSchema(name="Charge", supports_incremental=True, supports_append=True, supports_webhooks=True),
        ]

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ) as mock_get_or_create,
            mock.patch.object(
                StripeSource, "create_webhook", return_value=WebhookCreationResult(success=True)
            ) as mock_create_webhook,
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_webhook_schemas),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_called_once()
        mock_create_webhook.assert_called_once()

    def test_update_schema_to_webhook_existing_function_reconciles_events(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        # hog_function_created=False → existing webhook, so the reconcile path (not create) runs.
        mock_hog_fn_result = WebhookHogFunctionCreateResult(
            hog_function_id=str(uuid.uuid4()),
            webhook_url="https://test.com/webhook",
            hog_function_created=False,
        )
        mock_webhook_schemas = [
            SourceSchema(name="Charge", supports_incremental=True, supports_append=True, supports_webhooks=True),
        ]

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ),
            mock.patch.object(
                StripeSource, "create_webhook", return_value=WebhookCreationResult(success=True)
            ) as mock_create_webhook,
            mock.patch.object(
                StripeSource, "sync_webhook_events", return_value=WebhookSyncResult(success=True)
            ) as mock_sync_events,
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_webhook_schemas),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        # Existing webhook: reconcile events, never re-create.
        mock_sync_events.assert_called_once()
        mock_create_webhook.assert_not_called()

    def test_update_schema_to_webhook_existing_function_reconcile_failure_does_not_block(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        mock_hog_fn_result = WebhookHogFunctionCreateResult(
            hog_function_id=str(uuid.uuid4()),
            webhook_url="https://test.com/webhook",
            hog_function_created=False,
        )
        mock_webhook_schemas = [
            SourceSchema(name="Charge", supports_incremental=True, supports_append=True, supports_webhooks=True),
        ]

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ),
            mock.patch.object(
                StripeSource,
                "sync_webhook_events",
                return_value=WebhookSyncResult(success=False, error="add Write permission"),
            ),
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_webhook_schemas),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        # Reconcile failure must not hard-fail the schema enable.
        assert response.status_code == 200
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.WEBHOOK

    def test_update_schema_to_webhook_reconcile_raising_does_not_block(self):
        # The dangerous case: sync_webhook_events RAISES (bad creds, OAuth expired, network)
        # before any internal handling. This must never roll back the schema enable.
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        mock_hog_fn_result = WebhookHogFunctionCreateResult(
            hog_function_id=str(uuid.uuid4()),
            webhook_url="https://test.com/webhook",
            hog_function_created=False,
        )
        mock_webhook_schemas = [
            SourceSchema(name="Charge", supports_incremental=True, supports_append=True, supports_webhooks=True),
        ]

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ),
            mock.patch.object(StripeSource, "sync_webhook_events", side_effect=ValueError("Missing Stripe API key")),
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_webhook_schemas),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.WEBHOOK

    def test_update_schema_to_incremental_does_not_trigger_webhook(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.get_or_create_webhook_hog_function"
            ) as mock_get_or_create,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "incremental", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_not_called()

    def test_update_schema_to_full_refresh_does_not_trigger_webhook(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.get_or_create_webhook_hog_function"
            ) as mock_get_or_create,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_not_called()

    def test_update_schema_to_webhook_non_webhook_source_no_webhook_result(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "test",
                "user": "user",
                "password": "pass",
                "schema": "public",
                "ssh_tunnel_enabled": False,
            },
        )
        schema = ExternalDataSchema.objects.create(
            name="some_table",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.get_or_create_webhook_hog_function"
            ) as mock_get_or_create,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "id", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_not_called()

    def test_update_schema_to_webhook_non_webhook_schema_no_webhook_result(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="CustomerBalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        mock_non_webhook_schemas = [
            SourceSchema(
                name="CustomerBalanceTransaction",
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=False,
            ),
        ]

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_non_webhook_schemas),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.get_or_create_webhook_hog_function"
            ) as mock_get_or_create,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_not_called()
