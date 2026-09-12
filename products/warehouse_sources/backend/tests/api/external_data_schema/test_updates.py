"""External schema update tests."""

import uuid
from datetime import timedelta

import pytest
from unittest import mock

from django.test.client import Client as HttpClient

from temporalio.service import RPCError

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.temporal.common.schedule import describe_schedule

from products.data_modeling.backend.facade.models import Edge, Node
from products.data_warehouse.backend.facade.api import DIRECT_POSTGRES_URL_PATTERN, DIRECT_SNOWFLAKE_URL_PATTERN
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.tests.api.utils import create_external_data_source_ok

pytestmark = [pytest.mark.django_db]


class TestUpdateExternalDataSchema:
    @pytest.fixture
    def organization(self):
        organization = create_organization("Test Org")

        yield organization

        organization.delete()

    @pytest.fixture
    def team(self, organization):
        team = create_team(organization)

        yield team

        # Creating a source syncs managed Revenue Analytics views into a DAG, leaving Node rows whose
        # saved_query FK is PROTECT. Team cascades to DataWarehouseSavedQuery, so the nodes/edges must
        # go first — same ordering production relies on in delete_bulky_postgres_data.
        Edge.objects.filter(team=team).delete()
        Node.objects.filter(team=team).delete()
        team.delete()

    @pytest.fixture
    def user(self, team):
        user = create_user("test@user.com", "Test User", team.organization)

        yield user

        user.delete()

    def test_update_schema_change_should_sync_on_without_existing_schedule(
        self, team, user, client: HttpClient, temporal
    ):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, should_sync=False).first()
        assert schema is not None

        # This is expected to raise an RPCError if the schedule doesn't exist yet
        with pytest.raises(RPCError):
            schedule_desc = describe_schedule(temporal, str(schema.id))

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is True

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is False

    def test_update_schema_change_should_sync_off(self, team, user, client: HttpClient, temporal):
        """Test that we can pause a schedule by setting should_sync to false.

        We try to simulate the behaviour in production as close as possible since the previous tests using mocks were
        not catching issues with us not updating the schedule in Temporal correctly.
        """
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, should_sync=True).first()
        assert schema is not None

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is False

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            # here we try to mimic the payload from the frontend, which actually sends all fields, not just should_sync
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": False,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is False

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is True

    def test_update_schema_change_should_sync_on_with_existing_schedule(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, should_sync=True).first()
        assert schema is not None

        # ensure schedule exists first
        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is False

        # pause the schedule
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": False,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is False

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is True

        # now turn it back on
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        # needed to appease mypy ;-(
        new_schema = schema
        assert new_schema.should_sync is True

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is False

    def test_update_schema_change_should_sync_on_without_sync_type(self, team, user, client: HttpClient, temporal):
        """Test that we can turn on a schema that doesn't have a sync type set.

        Not sure in which cases this can happen.
        """
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, should_sync=False).first()
        assert schema is not None
        schema.sync_type = None
        schema.save()

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": None,
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_schema_exposes_direct_postgres_table_without_sync_type(
        self, team, user, client: HttpClient, temporal
    ):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="accounts",
            should_sync=False,
            sync_type=None,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "foreign_keys": [],
                }
            },
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists"
            ) as mock_external_data_workflow_exists,
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow"
            ) as mock_sync_external_data_job_workflow,
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={
                    "id": str(schema.id),
                    "name": schema.name,
                    "should_sync": True,
                    "incremental": False,
                    "status": "Completed",
                    "sync_type": None,
                    "incremental_field": None,
                    "incremental_field_type": None,
                    "sync_frequency": "6hour",
                    "sync_time_of_day": "00:00:00",
                },
                content_type="application/json",
            )

            assert response.status_code == 200
            schema.refresh_from_db()
            assert schema.should_sync is True
            assert schema.table is not None
            assert schema.table.deleted is False
            assert schema.table.url_pattern == DIRECT_POSTGRES_URL_PATTERN
            mock_external_data_workflow_exists.assert_not_called()
            mock_sync_external_data_job_workflow.assert_not_called()

    def test_update_schema_hides_direct_postgres_table_when_disabled(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )
        table = DataWarehouseTable.objects.create(
            name="accounts",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=team,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={"id": {"clickhouse": "Int32", "hogql": "integer", "valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="accounts",
            should_sync=True,
            sync_type=None,
            table=table,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "foreign_keys": [],
                }
            },
        )

        with mock.patch(
            "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.Database.create_for"
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={
                    "id": str(schema.id),
                    "name": schema.name,
                    "should_sync": False,
                    "incremental": False,
                    "status": "Completed",
                    "sync_type": None,
                    "incremental_field": None,
                    "incremental_field_type": None,
                    "sync_frequency": "6hour",
                    "sync_time_of_day": "00:00:00",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        schema.refresh_from_db()
        assert schema.should_sync is False
        assert DataWarehouseTable.raw_objects.get(pk=table.pk).deleted is True

    def test_update_schema_exposes_direct_snowflake_table_without_sync_type(
        self, team, user, client: HttpClient, temporal
    ):
        # Exercises the Snowflake reproject branch: a non-Postgres direct source must rebuild via the
        # Snowflake helper (DIRECT_SNOWFLAKE_URL_PATTERN), not silently fall through to the MySQL one.
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.SNOWFLAKE,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"database": "ANALYTICS"},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="SALES.ACCOUNTS",
            should_sync=False,
            sync_type=None,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "ID", "data_type": "NUMBER", "is_nullable": False}],
                    "foreign_keys": [],
                    "source_catalog": "ANALYTICS",
                    "source_schema": "SALES",
                    "source_table_name": "ACCOUNTS",
                }
            },
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists"
            ) as mock_external_data_workflow_exists,
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow"
            ) as mock_sync_external_data_job_workflow,
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={
                    "id": str(schema.id),
                    "name": schema.name,
                    "should_sync": True,
                    "incremental": False,
                    "status": "Completed",
                    "sync_type": None,
                    "incremental_field": None,
                    "incremental_field_type": None,
                    "sync_frequency": "6hour",
                    "sync_time_of_day": "00:00:00",
                },
                content_type="application/json",
            )

            assert response.status_code == 200
            schema.refresh_from_db()
            assert schema.should_sync is True
            assert schema.table is not None
            assert schema.table.deleted is False
            assert schema.table.url_pattern == DIRECT_SNOWFLAKE_URL_PATTERN
            mock_external_data_workflow_exists.assert_not_called()
            mock_sync_external_data_job_workflow.assert_not_called()

    def test_update_schema_hides_direct_snowflake_table_when_disabled(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.SNOWFLAKE,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"database": "ANALYTICS"},
        )
        table = DataWarehouseTable.objects.create(
            name="SALES.ACCOUNTS",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=team,
            url_pattern=DIRECT_SNOWFLAKE_URL_PATTERN,
            external_data_source=source,
            columns={"ID": {"clickhouse": "Int64", "hogql": "integer", "valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="SALES.ACCOUNTS",
            should_sync=True,
            sync_type=None,
            table=table,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "ID", "data_type": "NUMBER", "is_nullable": False}],
                    "foreign_keys": [],
                }
            },
        )

        with mock.patch(
            "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.Database.create_for"
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={
                    "id": str(schema.id),
                    "name": schema.name,
                    "should_sync": False,
                    "incremental": False,
                    "status": "Completed",
                    "sync_type": None,
                    "incremental_field": None,
                    "incremental_field_type": None,
                    "sync_frequency": "6hour",
                    "sync_time_of_day": "00:00:00",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        schema.refresh_from_db()
        assert schema.should_sync is False
        assert DataWarehouseTable.raw_objects.get(pk=table.pk).deleted is True

    def test_update_schema_cdc_with_blank_source_schema_uses_physical_schema_metadata(
        self, team, user, client: HttpClient, temporal
    ):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={
                "schema": "",
                "cdc_enabled": True,
                "cdc_management_mode": "posthog",
                "cdc_slot_name": "test_slot",
                "cdc_publication_name": "test_pub",
            },
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="analytics.events",
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={
                "primary_key_columns": ["id"],
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "foreign_keys": [],
                    "source_schema": "analytics",
                    "source_table_name": "events",
                },
            },
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.is_cdc_enabled_for_team",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.add_table"
            ) as mock_add_table,
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
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={
                    "id": str(schema.id),
                    "name": schema.name,
                    "should_sync": True,
                    "incremental": False,
                    "status": "Completed",
                    "sync_type": "cdc",
                    "incremental_field": None,
                    "incremental_field_type": None,
                    "sync_frequency": "6hour",
                    "sync_time_of_day": "00:00:00",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        # The adapter reads the publication name from config itself, so the call is
        # (source, schema, table).
        mock_add_table.assert_called_once()
        assert mock_add_table.call_args.args == (source, "analytics", "events")

    def test_delete_data_hides_direct_postgres_table(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )
        table = DataWarehouseTable.objects.create(
            name="accounts",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=team,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={"id": {"clickhouse": "Int32", "hogql": "integer", "valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="accounts",
            should_sync=True,
            sync_type=None,
            table=table,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "foreign_keys": [],
                }
            },
        )

        response = client.delete(f"/api/environments/{team.pk}/external_data_schemas/{schema.id}/delete_data")

        assert response.status_code == 200
        schema.refresh_from_db()
        assert schema.should_sync is False
        assert schema.table_id == table.id
        assert DataWarehouseTable.raw_objects.get(pk=table.pk).deleted is True

    def test_update_schema_change_sync_type_with_invalid_type(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id).first()
        assert schema is not None

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "blah",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_schema_sync_frequency(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id).first()
        assert schema is not None

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "7day",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.sync_frequency_interval == timedelta(days=7)

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.spec.intervals[0].every == timedelta(days=7)

    def test_update_schema_sync_time_of_day_when_previously_not_set(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, sync_time_of_day=None).first()
        assert schema is not None

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "24hour",
                "sync_time_of_day": "15:30:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.sync_time_of_day is not None
        assert schema.sync_time_of_day.hour == 15
        assert schema.sync_time_of_day.minute == 30
        assert schema.sync_time_of_day.second == 0

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.spec.intervals[0].offset == timedelta(hours=15, minutes=30)

    def test_update_schema_sync_time_of_day_when_previously_set(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, sync_time_of_day__isnull=False).first()
        assert schema is not None

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "24hour",
                "sync_time_of_day": "15:30:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.sync_time_of_day is not None
        assert schema.sync_time_of_day.hour == 15
        assert schema.sync_time_of_day.minute == 30
        assert schema.sync_time_of_day.second == 0

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.spec.intervals[0].offset == timedelta(hours=15, minutes=30)

    def test_update_webhook_schema_reenable_triggers_reset_pipeline(self, team, user, client: HttpClient, temporal):
        source = ExternalDataSource.objects.create(
            team=team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            should_sync=False,
            initial_sync_complete=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
        )

        client.force_login(user)

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow",
            ) as mock_trigger,
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow",
            ),
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={"should_sync": True},
                content_type="application/json",
            )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is True
        assert schema.sync_type_config.get("reset_pipeline") is True
        mock_trigger.assert_called_once()

    def test_update_webhook_schema_reenable_skips_reset_if_never_synced(self, team, user, client: HttpClient, temporal):
        source = ExternalDataSource.objects.create(
            team=team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            should_sync=False,
            initial_sync_complete=False,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
        )

        client.force_login(user)

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.trigger_external_data_workflow",
            ) as mock_trigger,
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.sync_external_data_job_workflow",
            ),
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={"should_sync": True},
                content_type="application/json",
            )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is True
        assert schema.sync_type_config.get("reset_pipeline") is None
        mock_trigger.assert_not_called()

    def test_update_cdc_schema_reenable_triggers_reset_pipeline(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={
                "schema": "public",
                "cdc_enabled": True,
                "cdc_management_mode": "posthog",
                "cdc_slot_name": "test_slot",
                "cdc_publication_name": "test_pub",
            },
        )
        schema = ExternalDataSchema.objects.create(
            name="public.events",
            team=team,
            source=source,
            should_sync=False,
            initial_sync_complete=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_mode": "streaming", "primary_key_columns": ["id"]},
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.is_cdc_enabled_for_team",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.add_table"
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
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={"should_sync": True},
                content_type="application/json",
            )

        assert response.status_code == 200, response.content

        schema.refresh_from_db()
        assert schema.should_sync is True
        # Re-enable must wipe the warehouse table, not merge current rows over stale pre-disable ones.
        assert schema.sync_type_config.get("reset_pipeline") is True
        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.initial_sync_complete is False
