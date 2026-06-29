import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from parameterized import parameterized

from products.warehouse_sources.backend.admin.external_data_schema_admin import ExternalDataSchemaAdmin
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_ADMIN_MODULE = "products.warehouse_sources.backend.admin.external_data_schema_admin"


class TestExternalDataSchemaAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.admin = ExternalDataSchemaAdmin(ExternalDataSchema, AdminSite())
        self.factory = RequestFactory()

    def _request(self, method: str, data: dict | None = None):
        request = getattr(self.factory, method)("/", data=data or {})
        request.session = {}
        request._messages = FallbackStorage(request)
        request.user = self.user
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

    @parameterized.expand(
        [
            (
                "md5",
                {"partition_mode": "md5", "partition_count": 72, "partitioning_enabled": True},
                {"partition_count": "10"},
                "partition_count_override",
                10,
                # The operator's count must land on *_override so it survives the bundled reset;
                # writing partition_count directly would be wiped and the source would re-derive its own value.
                {"partition_count": 72},
            ),
            (
                "numerical",
                {"partition_mode": "numerical", "partition_size": 1_000_000, "partitioning_enabled": True},
                {"partition_size": "5000000"},
                "partition_size_override",
                5_000_000,
                {},
            ),
        ]
    )
    def test_repartition_writes_override_key(
        self,
        _mode: str,
        initial_config: dict,
        post_data: dict,
        override_key: str,
        expected_value: int,
        extra_config_assertions: dict,
    ) -> None:
        schema = self._schema(sync_type_config=initial_config)

        with (
            patch(f"{_ADMIN_MODULE}.sync_connect"),
            patch(f"{_ADMIN_MODULE}._is_schedule_paused", return_value=True),
            patch(f"{_ADMIN_MODULE}._start_external_data_workflow") as mock_start,
        ):
            response = self.admin.repartition_view(self._request("post", post_data), schema.id)

        assert response.status_code == 302
        schema.refresh_from_db()
        assert schema.sync_type_config[override_key] == expected_value
        assert schema.sync_type_config["reset_pipeline"] is True
        for key, value in extra_config_assertions.items():
            assert schema.sync_type_config[key] == value
        mock_start.assert_called_once()

    @parameterized.expand(
        [
            (
                "md5_to_datetime",
                {"partition_mode": "md5", "partition_count": 30, "partitioning_enabled": True},
                {"partition_mode": "datetime", "partitioning_keys": "action_date", "partition_format": "month"},
                {
                    "partition_mode_override": "datetime",
                    "partitioning_keys_override": ["action_date"],
                    "partition_format": "month",
                },
            ),
            (
                "to_numerical",
                {"partition_mode": "md5", "partition_count": 30, "partitioning_enabled": True},
                {"partition_mode": "numerical", "partitioning_keys": "id", "partition_size": "1000000"},
                {
                    "partition_mode_override": "numerical",
                    "partitioning_keys_override": ["id"],
                    "partition_size_override": 1_000_000,
                },
            ),
            (
                "to_md5_with_keys",
                {"partition_mode": "datetime", "partition_format": "month", "partitioning_enabled": True},
                {"partition_mode": "md5", "partition_count": "10", "partitioning_keys": "record_id,action_date"},
                {
                    "partition_mode_override": "md5",
                    "partition_count_override": 10,
                    "partitioning_keys_override": ["record_id", "action_date"],
                },
            ),
            (
                # md5 without keys must explicitly clear a stale partitioning_keys_override left by a
                # prior datetime attempt — otherwise it survives the reset and md5 hashes the wrong
                # column instead of falling back to the table's primary keys.
                "to_md5_clears_stale_keys",
                {
                    "partition_mode": "datetime",
                    "partitioning_keys_override": ["action_date"],
                    "partition_format": "month",
                    "partitioning_enabled": True,
                },
                {"partition_mode": "md5", "partition_count": "10"},
                {
                    "partition_mode_override": "md5",
                    "partition_count_override": 10,
                    "partitioning_keys_override": None,
                },
            ),
        ]
    )
    def test_change_partition_mode_writes_overrides(
        self,
        _name: str,
        initial_config: dict,
        post_data: dict,
        expected_config: dict,
    ) -> None:
        schema = self._schema(sync_type_config=initial_config)

        with (
            patch(f"{_ADMIN_MODULE}.sync_connect"),
            patch(f"{_ADMIN_MODULE}._is_schedule_paused", return_value=True),
            patch(f"{_ADMIN_MODULE}._start_external_data_workflow") as mock_start,
        ):
            response = self.admin.change_partition_mode_view(self._request("post", post_data), schema.id)

        assert response.status_code == 302
        schema.refresh_from_db()
        for key, value in expected_config.items():
            assert schema.sync_type_config[key] == value
        assert schema.sync_type_config["reset_pipeline"] is True
        # The resync must be non-billable — the operator's reset shouldn't charge the customer.
        mock_start.assert_called_once()
        assert mock_start.call_args.args[2].billable is False

    @parameterized.expand(
        [
            # datetime/numerical need exactly one key. The change-mode count/size inputs are
            # intentionally not `required` (the form disables them when their mode isn't selected,
            # so a hidden control can't block submission), which means an empty submission reaches
            # the server and must be rejected here rather than blowing up on int("") or staging a
            # half-built override.
            (
                "datetime_without_single_key",
                {"partition_mode": "datetime", "partitioning_keys": "record_id,action_date"},
            ),
            ("md5_without_count", {"partition_mode": "md5"}),
            ("numerical_without_size", {"partition_mode": "numerical", "partitioning_keys": "id"}),
        ]
    )
    def test_change_partition_mode_rejects_invalid_input(self, _name: str, post_data: dict) -> None:
        schema = self._schema(sync_type_config={"partition_mode": "md5", "partition_count": 30})

        with (
            patch(f"{_ADMIN_MODULE}.sync_connect"),
            patch(f"{_ADMIN_MODULE}._start_external_data_workflow") as mock_start,
        ):
            response = self.admin.change_partition_mode_view(self._request("post", post_data), schema.id)

        assert response.status_code == 302
        schema.refresh_from_db()
        # Invalid input must not stage an override or kick off a resync.
        assert "partition_mode_override" not in schema.sync_type_config
        assert "reset_pipeline" not in schema.sync_type_config
        mock_start.assert_not_called()

    def test_change_partition_mode_denies_without_change_permission(self) -> None:
        schema = self._schema(sync_type_config={"partition_mode": "md5", "partition_count": 30})
        post_data = {"partition_mode": "md5", "partition_count": "10"}

        with (
            patch(f"{_ADMIN_MODULE}.sync_connect"),
            patch(f"{_ADMIN_MODULE}._start_external_data_workflow") as mock_start,
            patch.object(self.admin, "has_change_permission", return_value=False),
        ):
            with self.assertRaises(PermissionDenied):
                self.admin.change_partition_mode_view(self._request("post", post_data), schema.id)

        schema.refresh_from_db()
        assert "partition_mode_override" not in schema.sync_type_config
        mock_start.assert_not_called()
