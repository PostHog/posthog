import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from products.warehouse_sources.backend.admin.external_data_schema_admin import ExternalDataSchemaAdmin
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_ADMIN_MODULE = "products.warehouse_sources.backend.admin.external_data_schema_admin"


class TestExternalDataSchemaAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.admin = ExternalDataSchemaAdmin(ExternalDataSchema, AdminSite())
        self.factory = RequestFactory()

    def _request(self, method: str, data: dict | None = None):
        request = getattr(self.factory, method)("/", data=data or {})
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def _schema(self, **kwargs) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(team_id=self.team.pk, source=source, name="public.users", **kwargs)

    def test_trigger_sync_get_redirects_to_change_page(self) -> None:
        # Guards the admin-app-label reverse: resolving the change URL must not raise NoReverseMatch.
        schema = self._schema()
        response = self.admin.trigger_sync_view(self._request("get"), schema.id)
        assert response.status_code == 302
        assert str(schema.id) in response.url

    def test_pause_schedule_redirects_to_change_page(self) -> None:
        schema = self._schema()
        with patch(f"{_ADMIN_MODULE}.pause_external_data_schedule"):
            response = self.admin.pause_schedule_view(self._request("post"), schema.id)
        assert response.status_code == 302
        assert str(schema.id) in response.url

    def test_reset_streaming_cdc_flips_to_snapshot_non_billable(self) -> None:
        schema = self._schema(
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_mode": "streaming", "cdc_last_log_position": "0/ABC", "cdc_deferred_runs": [{}]},
            initial_sync_complete=True,
        )

        with (
            patch(f"{_ADMIN_MODULE}.sync_connect"),
            patch(f"{_ADMIN_MODULE}._is_schedule_paused", return_value=True),
            patch(f"{_ADMIN_MODULE}._start_external_data_workflow") as mock_start,
        ):
            response = self.admin.trigger_sync_view(self._request("post", {"reset_pipeline": "on"}), schema.id)

        assert response.status_code == 302
        schema.refresh_from_db()
        assert schema.cdc_mode == "snapshot"
        assert schema.initial_sync_complete is False
        assert "cdc_last_log_position" not in schema.sync_type_config
        assert "cdc_deferred_runs" not in schema.sync_type_config

        # The re-snapshot must persist before the workflow starts (the source reloads cdc_mode), and
        # the job must be non-billable so the initial full refresh isn't charged to the customer.
        mock_start.assert_called_once()
        inputs = mock_start.call_args.args[2]
        assert inputs.billable is False
