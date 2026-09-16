"""External schema serializer tests."""

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

pytestmark = [pytest.mark.django_db]


class TestExternalDataSchemaSerializerValidation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"stripe_secret_key": "123"},
        )
        self.schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=self.source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
        )

    def test_update_sync_type_null_clears_existing_value(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/",
            {"sync_type": None},
            format="json",
        )
        assert response.status_code == 200
        self.schema.refresh_from_db()
        assert self.schema.sync_type is None

    def test_update_absent_sync_type_preserves_existing_value(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/",
            {"should_sync": True},
            format="json",
        )
        assert response.status_code == 200
        self.schema.refresh_from_db()
        assert self.schema.sync_type == ExternalDataSchema.SyncType.INCREMENTAL


class TestSerializerLostUpdateProtection(APIBaseTest):
    """A PATCH must not revert what another writer committed after the request loaded the row —
    a sync_type_config key from a CDC extract activity, or the link fields "Delete data" clears."""

    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            # self_managed so the CDC publication hook in update() returns early without touching the source.
            job_inputs={
                "host": "h",
                "port": 5432,
                "database": "d",
                "user": "u",
                "password": "p",
                "schema": "public",
                "cdc_enabled": True,
                "cdc_management_mode": "self_managed",
                "cdc_slot_name": "s",
                "cdc_publication_name": "p",
            },
        )
        self.schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=self.source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={
                "cdc_mode": "streaming",
                "cdc_table_mode": "consolidated",
                "cdc_last_log_position": "0/100",
                "primary_key_columns": ["id"],
                "schema_metadata": {"columns": [{"name": "id", "data_type": "integer", "is_nullable": False}]},
            },
        )

    def test_patch_does_not_clobber_concurrent_activity_position(self):
        from products.warehouse_sources.backend.presentation.views.external_data_schema.serializers import (
            ExternalDataSchemaSerializer,
        )

        # The serializer's in-memory copy is loaded here, holding position 0/100.
        instance = ExternalDataSchema.objects.get(id=self.schema.id)

        # A CDC extract activity commits a newer position while the request is mid-flight.
        update_sync_type_config_keys(self.schema.id, self.team.pk, updates={"cdc_last_log_position": "0/900"})

        # A user PATCH edits an unrelated (non-sync_type_config) field off the stale copy and saves.
        serializer = ExternalDataSchemaSerializer(
            instance,
            data={"enabled_columns": ["id"]},
            partial=True,
            context={"team_id": self.team.pk, "post_commit_actions": []},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        self.schema.refresh_from_db()
        # The user's edit applied AND the concurrent position survived (not reverted to 0/100).
        assert self.schema.enabled_columns == ["id"]
        assert self.schema.sync_type_config["cdc_last_log_position"] == "0/900"

    def test_patch_changing_sync_type_config_key_keeps_concurrent_write(self):
        from products.warehouse_sources.backend.presentation.views.external_data_schema.serializers import (
            ExternalDataSchemaSerializer,
        )

        instance = ExternalDataSchema.objects.get(id=self.schema.id)  # in-memory copy, position 0/100

        # A CDC extract activity commits a newer position while the request is mid-flight.
        update_sync_type_config_keys(self.schema.id, self.team.pk, updates={"cdc_last_log_position": "0/900"})

        # The user changes a sync_type_config key (cdc_table_mode). The re-snapshot it would trigger is
        # deferred to post-commit (which we don't run), so only the merge itself is under test here.
        serializer = ExternalDataSchemaSerializer(
            instance,
            data={"cdc_table_mode": "both"},
            partial=True,
            context={"team_id": self.team.pk, "post_commit_actions": []},
        )
        with mock.patch(
            "products.warehouse_sources.backend.presentation.views.external_data_schema.serializers.is_any_external_data_schema_paused",
            return_value=False,
        ):
            serializer.is_valid(raise_exception=True)
            serializer.save()

        self.schema.refresh_from_db()
        # The user's key change landed AND the concurrent position (a key the request didn't touch) survived.
        assert self.schema.cdc_table_mode == "both"
        assert self.schema.sync_type_config["cdc_last_log_position"] == "0/900"

    def test_patch_does_not_revert_a_concurrent_delete_data(self):
        from products.warehouse_sources.backend.presentation.views.external_data_schema.serializers import (
            ExternalDataSchemaSerializer,
        )

        table = DataWarehouseTable.objects.create(
            team=self.team, name="orders", format="Parquet", external_data_source=self.source
        )
        self.schema.table = table
        self.schema.initial_sync_complete = True
        self.schema.save()

        instance = ExternalDataSchema.objects.get(id=self.schema.id)  # in-memory copy, still linked

        with mock.patch("products.data_warehouse.backend.facade.api.get_s3_client"):
            ExternalDataSchema.objects.get(id=self.schema.id).delete_table()

        serializer = ExternalDataSchemaSerializer(
            instance,
            data={"should_sync": False},
            partial=True,
            context={"team_id": self.team.pk, "post_commit_actions": []},
        )
        serializer.is_valid(raise_exception=True)
        saved = serializer.save()

        self.schema.refresh_from_db()
        table.refresh_from_db()
        assert saved.table_id is None
        assert saved.initial_sync_complete is False
        assert self.schema.should_sync is False
        assert self.schema.table_id is None
        assert self.schema.status is None
        assert self.schema.last_synced_at is None
        assert self.schema.initial_sync_complete is False
        assert table.deleted is True
