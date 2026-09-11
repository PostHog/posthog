"""External schema configuration tests."""

import contextlib
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized

from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import VersionDeprecation
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source import StripeSource

pytestmark = [pytest.mark.django_db]


class TestAvailableColumnsAcrossSqlSources(APIBaseTest):
    """`available_columns` is source-type-agnostic — it reads `schema_metadata.columns`.
    Parameterized across every SQL source to lock in that the serializer doesn't regress
    to Postgres-only behavior."""

    @parameterized.expand(
        [
            (ExternalDataSourceType.POSTGRES,),
            (ExternalDataSourceType.MYSQL,),
            (ExternalDataSourceType.MSSQL,),
            (ExternalDataSourceType.BIGQUERY,),
            (ExternalDataSourceType.SNOWFLAKE,),
            (ExternalDataSourceType.REDSHIFT,),
        ]
    )
    def test_available_columns_populated_from_schema_metadata(self, source_type: ExternalDataSourceType):
        source = ExternalDataSource.objects.create(team=self.team, source_type=source_type)
        schema = ExternalDataSchema.objects.create(
            name="customers",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type_config={
                "schema_metadata": {
                    "columns": [
                        {"name": "id", "data_type": "integer", "is_nullable": False},
                        {"name": "email", "data_type": "text", "is_nullable": True},
                    ],
                    "foreign_keys": [],
                },
            },
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/",
        )
        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["available_columns"] == [
            {"name": "id", "data_type": "integer", "is_nullable": False},
            {"name": "email", "data_type": "text", "is_nullable": True},
        ]

    @parameterized.expand(
        [
            (ExternalDataSourceType.POSTGRES,),
            (ExternalDataSourceType.MYSQL,),
            (ExternalDataSourceType.MSSQL,),
            (ExternalDataSourceType.BIGQUERY,),
            (ExternalDataSourceType.SNOWFLAKE,),
            (ExternalDataSourceType.REDSHIFT,),
        ]
    )
    def test_available_columns_empty_when_schema_metadata_missing(self, source_type: ExternalDataSourceType):
        source = ExternalDataSource.objects.create(team=self.team, source_type=source_type)
        schema = ExternalDataSchema.objects.create(
            name="customers",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/",
        )
        assert response.status_code == 200, response.json()
        assert response.json()["available_columns"] == []

    def test_available_columns_falls_back_to_synced_table_for_pipeline_projected_source(self):
        # Non-SQL sources match selections against dlt-normalized Arrow columns, so the synced
        # table remains a safe fallback when observed source metadata is unavailable. Internal
        # plumbing columns (`_dlt_id`, …) stay hidden.
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.HUBSPOT)
        table = DataWarehouseTable.objects.create(
            name="billing_customer",
            format="DeltaS3Wrapper",
            team=self.team,
            url_pattern="https://bucket.s3/data/*",
            columns={
                "id": {"clickhouse": "String"},
                "balance": {"clickhouse": "Nullable(Int64)"},
                "_dlt_id": {"clickhouse": "String"},
            },
        )
        schema = ExternalDataSchema.objects.create(
            name="billing_customer",
            team=self.team,
            source=source,
            table=table,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/",
        )
        assert response.status_code == 200, response.json()
        # Sort by name: `columns` is JSONB, which doesn't preserve key insertion order.
        assert sorted(response.json()["available_columns"], key=lambda column: column["name"]) == [
            {"name": "balance", "data_type": "Int64", "is_nullable": True},
            {"name": "id", "data_type": "String", "is_nullable": False},
        ]

    def test_available_columns_fallback_preserves_descriptions_for_source_projection(self):
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.POSTGRES)
        table = DataWarehouseTable.objects.create(
            name="billing_customer",
            format="DeltaS3Wrapper",
            team=self.team,
            url_pattern="https://bucket.s3/data/*",
            columns={"account_id": {"clickhouse": "String"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="billing_customer",
            team=self.team,
            source=source,
            table=table,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/")

        assert response.status_code == 200, response.json()
        assert response.json()["available_columns"] == [
            {"name": "account_id", "data_type": "String", "is_nullable": False}
        ]
        assert response.json()["source_column_metadata_available"] is False

    def test_enabled_columns_rejected_without_source_metadata_for_source_projection(self):
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.POSTGRES)
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"enabled_columns": ["account_id"]},
        )

        assert response.status_code == 400
        assert "Pull new schemas" in str(response.json())

    def test_unchanged_enabled_columns_do_not_block_unrelated_update_without_source_metadata(self):
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.POSTGRES)
        schema = ExternalDataSchema.objects.create(
            name="customers", team=self.team, source=source, enabled_columns=["account_id"], should_sync=True
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"enabled_columns": ["account_id"], "should_sync": False},
        )

        assert response.status_code == 200, response.json()
        schema.refresh_from_db()
        assert schema.should_sync is False

    def test_empty_enabled_columns_allowed_without_source_metadata(self):
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.POSTGRES)
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}", data={"enabled_columns": []}
        )

        assert response.status_code == 200, response.json()

    @parameterized.expand(
        [
            # source_type, expected — column selection is available for every registered source
            # (SQL projects in its SELECT, others drop before the Delta write) EXCEPT managed-schema
            # sources (Stripe/Paddle/Zendesk), whose canonical HogQL schema needs the full column set.
            (ExternalDataSourceType.POSTGRES, True),
            (ExternalDataSourceType.SNOWFLAKE, True),
            (ExternalDataSourceType.CLICKHOUSE, True),
            (ExternalDataSourceType.HUBSPOT, True),
            (ExternalDataSourceType.STRIPE, False),
            (ExternalDataSourceType.ZENDESK, False),
        ]
    )
    def test_source_supports_column_selection_flag(self, source_type: ExternalDataSourceType, expected: bool):
        source = ExternalDataSource.objects.create(team=self.team, source_type=source_type)

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
        )
        assert response.status_code == 200, response.json()
        assert response.json()["supports_column_selection"] is expected

    def test_enabled_columns_rejected_for_managed_schema_source(self):
        # Stripe/Paddle/Zendesk expose a fixed canonical HogQL schema; dropping a referenced
        # column makes the s3() structure miss it and the query fails to resolve the field.
        # Reject the selection at save so column selection can't corrupt those tables.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(name="Payout", team=self.team, source=source)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"enabled_columns": ["id", "status"]},
        )
        assert response.status_code == 400
        assert "Column selection is not supported" in str(response.json())


class TestExternalDataSchemaRetrieveSource(APIBaseTest):
    def _create(self, source_type: ExternalDataSourceType = ExternalDataSourceType.STRIPE):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=source_type,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(name="Customers", team=self.team, source=source)
        return source, schema

    @parameterized.expand(
        [
            # source_type, expected supports_column_selection, expected supports_row_filters.
            # Stripe is a managed-schema source (no column selection); row filters are SQL-only.
            (ExternalDataSourceType.STRIPE, False, False),
            (ExternalDataSourceType.POSTGRES, True, True),
        ]
    )
    def test_retrieve_includes_source_summary(
        self, source_type: ExternalDataSourceType, expected_column_selection: bool, expected_row_filters: bool
    ):
        source, schema = self._create(source_type=source_type)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/")
        assert response.status_code == 200, response.json()
        summary = response.json()["source"]
        assert summary["id"] == str(source.id)
        assert summary["source_type"] == source_type.value
        # The schema page reads this to hide sync-history UI on direct-query sources.
        assert summary["access_method"] == source.access_method
        assert summary["supports_column_selection"] is expected_column_selection
        assert summary["supports_row_filters"] is expected_row_filters
        assert "user_access_level" in summary

    def test_list_omits_source_summary(self):
        self._create()
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) > 0
        assert all(item["source"] is None for item in results)

    def test_retrieve_cross_team_is_404(self):
        other_team = create_team(organization=self.organization)
        source = ExternalDataSource.objects.create(
            team=other_team, source_type=ExternalDataSourceType.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(name="Customers", team=other_team, source=source)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/")
        assert response.status_code == 404


class TestExternalDataSchemaRowFilters(APIBaseTest):
    """PATCH-level validation for the row_filters field. A plain row_filters update needs no
    source DB connection or temporal schedule — it only reads the schema's discovered columns."""

    SCHEMA_METADATA = {
        "columns": [
            {"name": "id", "data_type": "integer", "is_nullable": False},
            {"name": "created_at", "data_type": "timestamp", "is_nullable": True},
            {"name": "name", "data_type": "varchar(255)", "is_nullable": True},
            {"name": "geom", "data_type": "geometry", "is_nullable": True},
        ]
    }

    def _create(self) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": "5432", "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        # schema_metadata is a read-only property backed by sync_type_config.
        return ExternalDataSchema.objects.create(
            name="Customers",
            team=self.team,
            source=source,
            sync_type_config={"schema_metadata": self.SCHEMA_METADATA},
        )

    def _patch(self, schema: ExternalDataSchema, row_filters: Any):
        return self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"row_filters": row_filters},
        )

    def test_valid_row_filters_persist(self):
        schema = self._create()
        filters = [
            {"column": "id", "operator": ">", "value": 10},
            {"column": "created_at", "operator": ">=", "value": "2026-01-01"},
        ]
        response = self._patch(schema, filters)
        assert response.status_code == 200, response.json()
        schema.refresh_from_db()
        assert schema.row_filters == filters

    def test_null_clears_row_filters(self):
        schema = self._create()
        schema.row_filters = [{"column": "id", "operator": ">", "value": 1}]
        schema.save(update_fields=["row_filters"])
        response = self._patch(schema, None)
        assert response.status_code == 200, response.json()
        schema.refresh_from_db()
        assert schema.row_filters is None

    def test_row_filters_returned_in_serializer(self):
        schema = self._create()
        filters = [{"column": "id", "operator": "<=", "value": 5}]
        schema.row_filters = filters
        schema.save(update_fields=["row_filters"])
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/")
        assert response.status_code == 200
        assert response.json()["row_filters"] == filters

    @parameterized.expand(
        [
            ("unknown_column", [{"column": "does_not_exist", "operator": ">", "value": 1}], "Unknown column"),
            ("disallowed_operator", [{"column": "id", "operator": "LIKE", "value": 1}], None),
            ("type_mismatch", [{"column": "id", "operator": ">", "value": "not-an-int"}], None),
            ("bad_date_value", [{"column": "created_at", "operator": ">", "value": "nope"}], None),
            ("unsupported_column_type", [{"column": "geom", "operator": "=", "value": "x"}], None),
        ]
    )
    def test_invalid_row_filter_rejected(self, _name, row_filters, expected_message):
        schema = self._create()
        response = self._patch(schema, row_filters)
        assert response.status_code == 400
        if expected_message:
            assert expected_message in str(response.json())

    @parameterized.expand(
        [
            ("postgres", ExternalDataSourceType.POSTGRES),
            ("mysql", ExternalDataSourceType.MYSQL),
            ("snowflake", ExternalDataSourceType.SNOWFLAKE),
        ]
    )
    def test_row_filters_rejected_for_direct_query_sources(self, _name, source_type):
        # No direct-query executor enforces row filters (they all read the table live), so accepting
        # a filter for any direct engine would silently leave excluded rows visible.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=source_type,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "h", "port": "5432", "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="Customers",
            team=self.team,
            source=source,
            sync_type_config={"schema_metadata": self.SCHEMA_METADATA},
        )
        response = self._patch(schema, [{"column": "id", "operator": ">", "value": 10}])
        assert response.status_code == 400
        assert "not supported for direct-query sources" in str(response.json())

    def test_row_filters_rejected_for_source_without_pushdown(self):
        # Only sources that push filters into their query (SQL WHERE) honor them — accepting a
        # filter for an API source would save it and then silently sync unfiltered rows.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="Customers",
            team=self.team,
            source=source,
            sync_type_config={"schema_metadata": self.SCHEMA_METADATA},
        )
        response = self._patch(schema, [{"column": "id", "operator": ">", "value": 10}])
        assert response.status_code == 400
        assert "not supported for this source type" in str(response.json())

    def test_row_filters_rejected_for_cdc_schema(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": "5432", "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="Customers",
            team=self.team,
            source=source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"schema_metadata": self.SCHEMA_METADATA},
        )
        response = self._patch(schema, [{"column": "id", "operator": ">", "value": 10}])
        assert response.status_code == 400
        assert "not supported for CDC" in str(response.json())


class TestExternalDataSchemaApiVersionOverride(APIBaseTest):
    def _create_schema(self, sync_type=ExternalDataSchema.SyncType.FULL_REFRESH, api_version=None):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            api_version=StripeSource.default_version,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        return ExternalDataSchema.objects.create(
            name="Customer",
            team=self.team,
            source=source,
            should_sync=True,
            sync_type=sync_type,
            api_version=api_version,
        )

    def _patch(self, schema, payload):
        return self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data=payload,
        )

    def test_create_via_api_is_blocked(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/",
            data={"name": "Customer", "source": str(source.id), "api_version": "not-validated"},
        )
        assert response.status_code == 405

    def test_set_and_clear_api_version_override(self):
        schema = self._create_schema()

        response = self._patch(schema, {"api_version": StripeSource.default_version})
        assert response.status_code == 200, response.json()
        schema.refresh_from_db()
        assert schema.api_version == StripeSource.default_version
        assert response.json()["api_version"] == StripeSource.default_version

        response = self._patch(schema, {"api_version": None})
        assert response.status_code == 200, response.json()
        schema.refresh_from_db()
        assert schema.api_version is None

    @parameterized.expand(
        [
            ("unsupported_version", ExternalDataSchema.SyncType.FULL_REFRESH, "1999-01-01"),
            ("webhook_schema", ExternalDataSchema.SyncType.WEBHOOK, None),  # None -> uses a supported version
        ]
    )
    def test_api_version_override_rejected(self, _name, sync_type, version):
        schema = self._create_schema(sync_type=sync_type)
        response = self._patch(schema, {"api_version": version or StripeSource.default_version})
        assert response.status_code == 400
        schema.refresh_from_db()
        assert schema.api_version is None

    def test_switching_to_webhook_blocked_while_override_present(self):
        schema = self._create_schema(api_version=StripeSource.default_version)
        response = self._patch(schema, {"sync_type": "webhook"})
        assert response.status_code == 400
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_unchanged_override_is_not_revalidated_on_full_payload_patch(self):
        schema = self._create_schema(api_version="2001-retired")
        response = self._patch(schema, {"api_version": "2001-retired", "should_sync": False})
        assert response.status_code == 200, response.json()
        schema.refresh_from_db()
        assert schema.api_version == "2001-retired"
        assert schema.should_sync is False

    def test_setting_override_on_unregistered_source_type_returns_400(self):
        schema = self._create_schema()
        schema.source.source_type = "NoSuchVendor"
        schema.source.save(update_fields=["source_type"])
        response = self._patch(schema, {"api_version": "v2"})
        assert response.status_code == 400

    @mock.patch(
        "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.cancel_external_data_workflow"
    )
    def test_repin_cancels_running_sync(self, mock_cancel):
        from products.warehouse_sources.backend.facade.models import ExternalDataJob

        schema = self._create_schema()
        ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            workflow_id="test-workflow-id",
        )

        response = self._patch(schema, {"api_version": StripeSource.default_version})
        assert response.status_code == 200, response.json()
        mock_cancel.assert_called_once_with("test-workflow-id")

        # An unrelated edit (no version change) must not cancel anything.
        mock_cancel.reset_mock()
        response = self._patch(schema, {"api_version": StripeSource.default_version, "should_sync": False})
        assert response.status_code == 200, response.json()
        mock_cancel.assert_not_called()

    def test_api_version_deprecation_surfaces_for_deprecated_override_only(self):
        schema = self._create_schema(api_version="1999-legacy")
        url = f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}"

        assert self.client.get(url).json()["api_version_deprecation"] is None

        deprecated = (VersionDeprecation(version="1999-legacy", sunset_at=None),)
        with mock.patch.object(StripeSource, "deprecated_versions", deprecated):
            payload = self.client.get(url).json()
        assert payload["api_version_deprecation"] == {
            "version": "1999-legacy",
            "sunset_at": None,
            "default_version": StripeSource.default_version,
        }


class TestFanoutParentSelection(APIBaseTest):
    """Fan-out parents and children are selected independently.

    Warehouse parent reuse is an optimization the run-time gate applies when it can, so the
    API constrains nothing here: no selection is refused and no parent is enabled as a side
    effect. Deliberately not in TestExternalDataSchema: its autouse fixture needs a live
    Temporal server, while every Temporal touchpoint here is behind a mock.
    """

    def _create_sentry_fanout_pair(self, parent_sync_type, child_should_sync=False, parent_should_sync=False):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.SENTRY,
            job_inputs={"auth_token": "token", "organization_slug": "acme"},
        )
        parent = ExternalDataSchema.objects.create(
            name="issues",
            team=self.team,
            source=source,
            should_sync=parent_should_sync,
            sync_type=parent_sync_type,
        )
        child = ExternalDataSchema.objects.create(
            name="issue_events",
            team=self.team,
            source=source,
            should_sync=child_should_sync,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        return source, parent, child

    def _temporal_patches(self):
        return (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow"
            ),
            mock.patch("products.data_warehouse.backend.facade.api.external_data_workflow_exists", return_value=False),
            mock.patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow"),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.pause_external_data_schedule"
            ),
            mock.patch("products.data_warehouse.backend.facade.api.pause_external_data_schedule"),
        )

    def _patch_schema(self, schema_id, data):
        with contextlib.ExitStack() as stack:
            for p in self._temporal_patches():
                stack.enter_context(p)
            return self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema_id}",
                data=data,
            )

    @parameterized.expand(
        [
            ("unconfigured_parent", None, False),
            ("disabled_parent", ExternalDataSchema.SyncType.INCREMENTAL, False),
            ("append_parent", ExternalDataSchema.SyncType.APPEND, True),
            ("enabled_parent", ExternalDataSchema.SyncType.INCREMENTAL, True),
        ]
    )
    def test_enabling_child_never_blocks_on_or_touches_its_parent(self, _name, parent_sync_type, parent_should_sync):
        # These are the configurations teams already run, so enabling the child has to keep
        # working. The parent must come out byte-identical either way: enabling one bills its
        # rows, and even a redundant write would churn its Temporal schedule.
        _, parent, child = self._create_sentry_fanout_pair(
            parent_sync_type=parent_sync_type, parent_should_sync=parent_should_sync
        )
        parent_updated_at = parent.updated_at

        response = self._patch_schema(child.id, {"should_sync": True})

        assert response.status_code == 200, response.json()
        child.refresh_from_db()
        assert child.should_sync is True
        parent.refresh_from_db()
        assert parent.should_sync is parent_should_sync
        assert parent.updated_at == parent_updated_at

    @parameterized.expand([("disable",), ("delete",)])
    def test_parent_stays_editable_while_a_child_syncs_from_it(self, action):
        # The child degrades to the parent-API path instead of stranding, so neither write is
        # protected against.
        _, parent, _child = self._create_sentry_fanout_pair(
            parent_sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            parent_should_sync=True,
            child_should_sync=True,
        )

        if action == "disable":
            response = self._patch_schema(parent.id, {"should_sync": False})
            assert response.status_code == 200, response.json()
            parent.refresh_from_db()
            assert parent.should_sync is False
        else:
            with contextlib.ExitStack() as stack:
                for p in self._temporal_patches():
                    stack.enter_context(p)
                response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_schemas/{parent.id}")
            assert response.status_code == 204
