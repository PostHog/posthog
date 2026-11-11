import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.messages import get_messages

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_ACTIONS_MODULE = "products.warehouse_sources.backend.logic.schema_staff_actions"
_SHARED_MODULE = "products.warehouse_sources.backend.ad_hoc_sync"
TOOL_URL = "/admin/console/tools/warehouse-sources/"


class TestWarehouseSourcesConsoleTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _run(self, schema: ExternalDataSchema, operation: str, data: dict | None = None):
        return self.client.post(
            f"{TOOL_URL}{operation}/?schema={schema.id}", {"reason": "Customer asked", **(data or {})}
        )

    @staticmethod
    def _messages(response) -> list[str]:
        return [str(message) for message in get_messages(response.wsgi_request)]

    def _schema(self, **kwargs) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(team_id=self.team.pk, source=source, name="public.users", **kwargs)

    def test_schema_page_shows_partitioning_jobs_and_operations(self) -> None:
        schema = self._schema(sync_type_config={"partition_mode": "md5", "partition_count": 30})

        response = self.client.get(f"{TOOL_URL}?schema={schema.id}")

        content = response.content.decode()
        assert response.status_code == 200
        assert "public.users" in content and "partition_count" in content
        assert "No jobs found for this schema." in content
        for label in ("Repartition", "Trigger sync", "Pause schedule", "Unpause schedule", "Recreate schedule"):
            assert label in content

    def test_source_page_lists_its_schemas(self) -> None:
        schema = self._schema()

        response = self.client.get(f"{TOOL_URL}?source={schema.source_id}")

        assert response.status_code == 200
        assert f"{TOOL_URL}?schema={schema.id}" in response.content.decode()

    def test_pause_schedule_returns_to_the_schema_page(self) -> None:
        schema = self._schema()
        with patch(f"{_ACTIONS_MODULE}.pause_external_data_schedule") as mock_pause:
            response = self._run(schema, "pause-schedule")
        assert response.status_code == 302
        assert response["Location"] == f"{TOOL_URL}?schema={schema.id}"
        mock_pause.assert_called_once_with(str(schema.id))

    @parameterized.expand([("repartition",), ("trigger-sync",), ("pause-schedule",), ("recreate-schedule",)])
    def test_old_admin_urls_redirect_to_the_schema_page(self, action: str) -> None:
        schema = self._schema()

        response = self.client.get(f"/admin/warehouse_sources/externaldataschema/{schema.id}/{action}/")

        assert response.status_code == 302
        assert response["Location"] == f"{TOOL_URL}?schema={schema.id}"

    def test_reset_streaming_cdc_flips_to_snapshot_non_billable(self) -> None:
        schema = self._schema(
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_mode": "streaming", "cdc_last_log_position": "0/ABC"},
            initial_sync_complete=True,
        )

        with (
            patch(f"{_ACTIONS_MODULE}.sync_connect"),
            patch(f"{_SHARED_MODULE}.is_schedule_paused", return_value=True),
            # No sync of the table can hand over, so the reset is staged here. The real check reads
            # the load queue, which lives in a database this test does not create.
            patch(f"{_SHARED_MODULE}.cancel_sync_that_could_hand_over", return_value=False),
            patch(f"{_SHARED_MODULE}.start_external_data_workflow") as mock_start,
        ):
            response = self._run(schema, "trigger-sync", {"reset_pipeline": "on"})

        assert response.status_code == 302
        schema.refresh_from_db()
        assert schema.cdc_mode == "snapshot"
        assert schema.initial_sync_complete is False
        assert "cdc_last_log_position" not in schema.sync_type_config

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
                {"partition_mode": "md5", "partition_count": 10, "partition_size": None, "partition_format": None},
            ),
            (
                "numerical",
                {"partition_mode": "numerical", "partition_size": 1_000_000, "partitioning_enabled": True},
                {"partition_size": "5000000"},
                {"partition_mode": "numerical", "partition_size": 5_000_000, "partition_count": None},
            ),
        ]
    )
    def test_repartition_queues_pending_target_without_reset(
        self,
        _mode: str,
        initial_config: dict,
        post_data: dict,
        expected_pending: dict,
    ) -> None:
        # In-place repartition writes a `repartition_pending` target consumed by the next run's
        # pre-extraction activity — it must NOT set reset_pipeline (no source re-pull) or stage *_override
        # keys (those drove the old reset-resync path).
        schema = self._schema(sync_type_config=initial_config)

        with (
            patch(f"{_ACTIONS_MODULE}.sync_connect"),
            patch(f"{_ACTIONS_MODULE}.is_schedule_paused", return_value=True),
            patch(f"{_ACTIONS_MODULE}.start_external_data_workflow") as mock_start,
        ):
            response = self._run(schema, "repartition", post_data)

        assert response.status_code == 302
        schema.refresh_from_db()
        pending = schema.sync_type_config["repartition_pending"]
        assert pending["trigger_reason"] == "admin"
        assert pending["attempts"] == 0
        for key, value in expected_pending.items():
            assert pending[key] == value
        assert "reset_pipeline" not in schema.sync_type_config
        assert "partition_count_override" not in schema.sync_type_config
        mock_start.assert_called_once()
        assert mock_start.call_args.args[2].billable is False

    @parameterized.expand(
        [
            (
                "md5_to_datetime",
                {"partition_mode": "md5", "partition_count": 30, "partitioning_enabled": True},
                {"partition_mode": "datetime", "partitioning_keys": "action_date", "partition_format": "month"},
                {
                    "partition_mode": "datetime",
                    "partition_keys": ["action_date"],
                    "partition_format": "month",
                },
            ),
            (
                "to_numerical",
                {"partition_mode": "md5", "partition_count": 30, "partitioning_enabled": True},
                {"partition_mode": "numerical", "partitioning_keys": "id", "partition_size": "1000000"},
                {
                    "partition_mode": "numerical",
                    "partition_keys": ["id"],
                    "partition_size": 1_000_000,
                },
            ),
            (
                "to_md5_with_keys",
                {"partition_mode": "datetime", "partition_format": "month", "partitioning_enabled": True},
                {"partition_mode": "md5", "partition_count": "10", "partitioning_keys": "record_id,action_date"},
                {
                    "partition_mode": "md5",
                    "partition_count": 10,
                    "partition_keys": ["record_id", "action_date"],
                },
            ),
            (
                # md5 without keys must not carry a stale partitioning_keys_override from a prior datetime
                # attempt — otherwise md5 would hash the wrong column instead of the table's primary keys.
                "to_md5_clears_stale_keys",
                {
                    "partition_mode": "datetime",
                    "partitioning_keys_override": ["action_date"],
                    "partition_format": "month",
                    "partitioning_enabled": True,
                },
                {"partition_mode": "md5", "partition_count": "10"},
                {
                    "partition_mode": "md5",
                    "partition_count": 10,
                    "partition_keys": [],
                },
            ),
            (
                # In-place format change with the mode unchanged — keys carry over from the existing scheme.
                "datetime_in_place_format_change",
                {
                    "partition_mode": "datetime",
                    "partition_format": "week",
                    "partitioning_keys": ["action_date"],
                    "partitioning_enabled": True,
                },
                {"partition_mode": "datetime", "partition_format": "day"},
                {
                    "partition_mode": "datetime",
                    "partition_format": "day",
                    "partition_keys": ["action_date"],
                },
            ),
        ]
    )
    def test_change_partition_mode_queues_pending_target(
        self,
        _name: str,
        initial_config: dict,
        post_data: dict,
        expected_pending: dict,
    ) -> None:
        schema = self._schema(sync_type_config=initial_config)

        with (
            patch(f"{_ACTIONS_MODULE}.sync_connect"),
            patch(f"{_ACTIONS_MODULE}.is_schedule_paused", return_value=True),
            patch(f"{_ACTIONS_MODULE}.start_external_data_workflow") as mock_start,
        ):
            response = self._run(schema, "repartition", post_data)

        assert response.status_code == 302
        schema.refresh_from_db()
        pending = schema.sync_type_config["repartition_pending"]
        for key, value in expected_pending.items():
            assert pending[key] == value
        assert pending["trigger_reason"] == "admin"
        # In-place: no source re-pull, and the run must be non-billable.
        assert "reset_pipeline" not in schema.sync_type_config
        mock_start.assert_called_once()
        assert mock_start.call_args.args[2].billable is False

    @parameterized.expand(
        [
            # datetime/numerical need exactly one key (here a mode change supplies none / too many).
            # The count/size inputs are intentionally not `required` (the form disables them when
            # their mode isn't selected, so a hidden control can't block submission), which means an
            # empty submission reaches the server and must be rejected here rather than blowing up on
            # int("") or staging a half-built override.
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
            patch(f"{_ACTIONS_MODULE}.sync_connect"),
            patch(f"{_ACTIONS_MODULE}.start_external_data_workflow") as mock_start,
        ):
            response = self._run(schema, "repartition", post_data)

        assert response.status_code == 400
        schema.refresh_from_db()
        # Invalid input must not queue a repartition or kick off a run.
        assert "repartition_pending" not in schema.sync_type_config
        assert "reset_pipeline" not in schema.sync_type_config
        mock_start.assert_not_called()

    @parameterized.expand([(True,), (False,)])
    def test_recreate_schedule_passes_should_sync_through(self, should_sync: bool) -> None:
        # Guards the recovery action for schemas left without a Temporal schedule: it must
        # recreate with the schema's own should_sync so a disabled schema comes back paused
        # instead of silently starting recurring syncs, and it must not trigger a run (runs
        # fired through the schedule are always billable; operators use "Trigger sync" for a
        # non-billable one).
        schema = self._schema(should_sync=should_sync)

        with patch(f"{_ACTIONS_MODULE}.sync_external_data_job_workflow") as mock_sync:
            response = self._run(schema, "recreate-schedule")

        assert response.status_code == 302
        mock_sync.assert_called_once_with(schema, create=True, should_sync=should_sync, trigger_immediately=False)

    def test_recreate_schedule_rejects_direct_query_source(self) -> None:
        # Direct-query sources have no per-schema schedules by design; recreating one would
        # start scheduled syncs on a source that is only ever queried live.
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        schema = ExternalDataSchema.objects.create(team_id=self.team.pk, source=source, name="public.users")

        with patch(f"{_ACTIONS_MODULE}.sync_external_data_job_workflow") as mock_sync:
            page = self.client.get(f"{TOOL_URL}?schema={schema.id}")
            response = self._run(schema, "recreate-schedule")

        assert "Recreate schedule" not in page.content.decode()
        assert response.status_code == 404
        mock_sync.assert_not_called()

    def test_recreate_schedule_temporal_failure_flashes_error(self) -> None:
        # A Temporal outage must surface as a console message, not a 500.
        schema = self._schema()

        with patch(
            f"{_ACTIONS_MODULE}.sync_external_data_job_workflow",
            side_effect=Exception("connect failed"),
        ):
            response = self._run(schema, "recreate-schedule")

        assert response.status_code == 302
        assert "Failed to recreate schedule: connect failed" in self._messages(response)
