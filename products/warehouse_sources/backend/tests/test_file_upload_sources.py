import io

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team

from products.warehouse_sources.backend.facade.testing import (
    find_replaced_self_managed_table,
    migrate_team_self_managed_tables,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

VIEW_MODULE = "products.data_warehouse.backend.presentation.views.table"
MODEL_MODULE = "products.warehouse_sources.backend.models.table"
UPLOAD_ID = "11111111-2222-4333-8444-555555555555"
NEW_UPLOAD_ID = "22222222-2222-4333-8444-555555555555"

# Stand-in for what `DataWarehouseTable.get_columns()` reads off the object in place — patched so the
# create tests never reach chdb/ClickHouse, which can't introspect a fake S3 object.
FAKE_COLUMNS = {
    "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
    "total": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
}


class _CapturingBuffer(io.BytesIO):
    """A BytesIO that publishes its contents to a sink on close, so the endpoint's
    context-managed write is captured once the file handle is closed."""

    def __init__(self, sink: dict[str, bytes], path: str) -> None:
        super().__init__()
        self._sink = sink
        self._path = path

    def close(self) -> None:
        self._sink[self._path] = self.getvalue()
        super().close()


class _FakeS3:
    """Captures what the endpoint writes, standing in for the object store boundary."""

    def __init__(self, *, exists_result: bool = True) -> None:
        self.written: dict[str, bytes] = {}
        self.removed: list[str] = []
        self._exists_result = exists_result

    def open(self, path: str, mode: str) -> io.BytesIO:
        return _CapturingBuffer(self.written, path)

    def exists(self, path: str) -> bool:
        return self._exists_result

    def rm(self, path: str) -> None:
        self.removed.append(path)


SERVICE_MODULE = "products.warehouse_sources.backend.file_upload_sources"
STORAGE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.storage"
SOURCE_VIEWS = "products.warehouse_sources.backend.presentation.views.external_data_source.base"
REPLACEMENT_COLUMNS = {
    "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
    "placed_at": {"hogql": "DateTimeDatabaseField", "clickhouse": "Nullable(DateTime64(6))"},
}


def _warehouse_api_flag(flag_key: str, *args: object, **kwargs: object) -> bool:
    return flag_key == "warehouse-api"


@override_settings(DATAWAREHOUSE_BUCKET="test-bucket", DATAWAREHOUSE_BUCKET_DOMAIN="warehouse.posthog.test")
class TestFileUploadSources(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base_url = f"/api/environments/{self.team.pk}/warehouse_tables"
        self.s3 = _FakeS3()
        self.trigger_count = 0
        patches = [
            patch("posthoganalytics.feature_enabled", return_value=False),
            patch(f"{VIEW_MODULE}.get_s3_client", return_value=self.s3),
            patch(f"{STORAGE_MODULE}.get_s3_client", return_value=self.s3),
            patch(f"{VIEW_MODULE}.validate_data_warehouse_table_columns.delay"),
            patch(f"{MODEL_MODULE}.DataWarehouseTable.detect_csv_double_quotes_setting", return_value=False),
            patch(f"{SERVICE_MODULE}.sync_connect"),
            patch(f"{SERVICE_MODULE}.sync_external_data_job_workflow"),
            patch(f"{SERVICE_MODULE}.trigger_ad_hoc_sync", side_effect=self._trigger),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.flag, self.schedule, self.trigger = mocks[0], mocks[6], mocks[7]
        self.columns = patch(f"{MODEL_MODULE}.DataWarehouseTable.get_columns", return_value=dict(FAKE_COLUMNS))
        self.get_columns = self.columns.start()
        self.addCleanup(self.columns.stop)

    def _trigger(self, *_args: object, **_kwargs: object) -> MagicMock:
        self.trigger_count += 1
        return MagicMock(workflow_id=f"workflow-{self.trigger_count}", schedule_paused_now=False)

    def _create(self, upload_id: str = UPLOAD_ID, **payload: str):
        return self.client.post(
            f"{self.base_url}/create_from_upload/?include_columns=false",
            data={"upload_id": upload_id, "filename": "orders.csv", "file_format": "csv", "table_name": "orders"}
            | payload,
            format="json",
        )

    def _table_with_source(self) -> tuple[DataWarehouseTable, ExternalDataSchema]:
        response = self._create()
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        table = DataWarehouseTable.objects.get(id=response.json()["id"])
        schema = ExternalDataSchema.objects.select_related("source").get(table=table)
        return table, schema

    def _replace(self, table: DataWarehouseTable, upload_id: str = NEW_UPLOAD_ID, **payload: str):
        return self.client.post(
            f"{self.base_url}/{table.id}/replace_file/?include_columns=false",
            data={"upload_id": upload_id, "filename": "orders_v2.csv", "file_format": "csv"} | payload,
            format="json",
        )

    def test_an_upload_becomes_a_file_upload_source_and_one_billable_sync(self) -> None:
        response = self._create()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        table = DataWarehouseTable.objects.get(id=response.json()["id"])
        # Until the first sync imports it, the table reads the file in place.
        assert (table.name, table.external_data_source_id, table.credential_id) == ("orders", None, None)
        assert (
            table.url_pattern
            == f"https://warehouse.posthog.test/file_uploads/team_{self.team.pk}/{UPLOAD_ID}/orders.csv"
        )
        assert response.json()["external_schema"] is not None

        schema = ExternalDataSchema.objects.select_related("source").get(table=table)
        assert schema.source.source_type == "FileUpload"
        assert schema.source.job_inputs == {
            "upload_id": UPLOAD_ID,
            "filename": "orders.csv",
            "file_format": "csv",
            "schema_name": "orders",
        }
        assert (schema.name, schema.should_sync, schema.sync_type) == ("orders", False, "full_refresh")
        assert schema.schema_metadata is not None
        assert schema.schema_metadata["csv"] == {
            "has_header": True,
            "allow_double_quotes": False,
            "column_types": {"id": "integer", "total": "integer"},
        }
        self.schedule.assert_called_once_with(schema, create=True, should_sync=False, trigger_immediately=False)
        assert self.trigger.call_args.kwargs == {
            "billable": True,
            "reset_pipeline": False,
            "workflow_id_prefix": "file-upload",
        }

    def test_a_sync_that_fails_to_start_still_leaves_a_working_table(self) -> None:
        self.trigger.side_effect = RuntimeError("temporal is down")

        response = self._create()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        table = DataWarehouseTable.objects.get(id=response.json()["id"])
        assert ExternalDataSchema.objects.filter(table=table, source__source_type="FileUpload").exists()

    @parameterized.expand(
        [
            ("traversal", "../orders.csv"),
            ("other_folder", "team_1/orders.csv"),
            ("hidden", ".orders.csv"),
        ]
    )
    def test_a_filename_upload_file_could_not_have_returned_is_refused(self, _name: str, filename: str) -> None:
        response = self._create(filename=filename)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not DataWarehouseTable.objects.filter(team=self.team).exists()

    def test_replacing_the_file_keeps_the_table_and_starts_a_billable_full_refresh(self) -> None:
        table, schema = self._table_with_source()
        self.get_columns.return_value = dict(REPLACEMENT_COLUMNS)

        response = self._replace(table)

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert response.json()["id"] == str(table.id)
        schema.refresh_from_db()
        schema.source.refresh_from_db()
        assert schema.source.job_inputs["upload_id"] == NEW_UPLOAD_ID
        assert schema.source.job_inputs["filename"] == "orders_v2.csv"
        assert schema.schema_metadata is not None
        assert schema.schema_metadata["csv"]["column_types"] == {"id": "integer", "placed_at": "datetime"}
        [superseded] = (schema.source.connection_metadata or {})["file_upload"]["superseded"]
        assert (superseded["upload_id"], superseded["filename"]) == (UPLOAD_ID, "orders.csv")
        assert self.trigger_count == 2
        assert self.trigger.call_args.kwargs["billable"] is True
        assert schema.sync_type == "full_refresh"
        # The old file stays until a sync of the new one succeeds.
        assert self.s3.removed == []
        table.refresh_from_db()
        assert table.name == "orders"

    def test_replacing_the_file_of_an_append_schema_switches_it_to_full_refresh(self) -> None:
        table, schema = self._table_with_source()
        ExternalDataSchema.objects.filter(pk=schema.pk).update(sync_type=ExternalDataSchema.SyncType.APPEND)
        self.get_columns.return_value = dict(REPLACEMENT_COLUMNS)

        response = self._replace(table)

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    @parameterized.expand(["missing_file", "unreadable_file", "sync_running", "not_a_file_upload_table"])
    def test_a_replacement_that_cannot_go_ahead_changes_nothing(self, case: str) -> None:
        table, schema = self._table_with_source()
        if case == "missing_file":
            self.s3._exists_result = False
        elif case == "unreadable_file":
            self.get_columns.side_effect = Exception("DB::Exception: Cannot extract table structure")
        elif case == "sync_running":
            ExternalDataJob.objects.create(
                team=self.team, pipeline=schema.source, schema=schema, status=ExternalDataJob.Status.RUNNING
            )
        else:
            table = DataWarehouseTable.objects.create(
                team=self.team,
                name="linked",
                format="CSVWithNames",
                url_pattern=f"https://warehouse.posthog.test/file_uploads/team_{self.team.pk}/{UPLOAD_ID}/orders.csv",
                columns={},
            )

        response = self._replace(table)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        schema.source.refresh_from_db()
        assert schema.source.job_inputs["upload_id"] == UPLOAD_ID
        assert "file_upload" not in (schema.source.connection_metadata or {})
        assert self.trigger_count == 1

    def test_the_source_update_endpoint_cannot_repoint_the_upload(self) -> None:
        _, schema = self._table_with_source()

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{schema.source_id}/",
            {
                "job_inputs": {
                    "upload_id": NEW_UPLOAD_ID,
                    "filename": "../../team_1/secret.csv",
                    "file_format": "parquet",
                    "schema_name": "other",
                }
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        schema.source.refresh_from_db()
        assert schema.source.job_inputs == {
            "upload_id": UPLOAD_ID,
            "filename": "orders.csv",
            "file_format": "csv",
            "schema_name": "orders",
        }

    def test_the_generic_source_endpoint_cannot_create_one(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            {
                "source_type": "FileUpload",
                "payload": {
                    "upload_id": UPLOAD_ID,
                    "filename": "orders.csv",
                    "file_format": "csv",
                    "schema_name": "orders",
                },
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "can't be created here" in response.json()["message"]
        assert not ExternalDataSource.objects.filter(team=self.team).exists()

    def test_its_schedule_cannot_be_turned_on(self) -> None:
        _, schema = self._table_with_source()

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/",
            {"should_sync": True, "sync_frequency": "24hour"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "can't be turned on" in str(response.json())
        schema.refresh_from_db()
        assert schema.should_sync is False

    def test_its_table_is_deleted_through_the_source(self) -> None:
        table, _ = self._table_with_source()

        response = self.client.delete(f"{self.base_url}/{table.id}")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        table.refresh_from_db()
        assert table.deleted is False
        assert self.s3.removed == []

    @patch(f"{SOURCE_VIEWS}.delete_discover_schemas_schedule")
    @patch(f"{SOURCE_VIEWS}.delete_external_data_schedule")
    @patch(f"{SOURCE_VIEWS}.bulk_delete_external_data_schedules", return_value=[])
    def test_deleting_the_source_deletes_the_table_and_its_files(self, *_mocks: object) -> None:
        table, schema = self._table_with_source()
        self.get_columns.return_value = dict(REPLACEMENT_COLUMNS)
        assert self._replace(table).status_code == status.HTTP_202_ACCEPTED

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{schema.source_id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        table.refresh_from_db()
        assert table.deleted is True
        prefix = f"{settings.DATAWAREHOUSE_BUCKET}/file_uploads/team_{self.team.pk}/"
        assert sorted(self.s3.removed) == sorted(
            [f"{prefix}{NEW_UPLOAD_ID}/orders_v2.csv", f"{prefix}{UPLOAD_ID}/orders.csv"]
        )

    def _migrated_table(self, key: str) -> tuple[DataWarehouseTable, ExternalDataSchema]:
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="orders",
            format="CSVWithNames",
            url_pattern=f"https://warehouse.posthog.test/{key.format(team=self.team.pk, upload=UPLOAD_ID)}",
            columns=dict(FAKE_COLUMNS),
            options={"csv_allow_double_quotes": False},
        )
        [outcome] = migrate_team_self_managed_tables(self.team.pk)
        assert outcome.action == "linked", outcome
        assert outcome.status.schema_id is not None
        schema = ExternalDataSchema.objects.select_related("source").get(pk=outcome.status.schema_id)
        return table, schema

    def _legacy_file_action(self, filename: str = "orders_v2.csv"):
        return self.client.post(
            f"{self.base_url}/file/",
            {"file": SimpleUploadedFile(filename, b"id,total\n1,2\n"), "name": "orders", "format": "CSVWithNames"},
            format="multipart",
        )

    @parameterized.expand(
        [
            ("upload_folder_replace_file", "file_uploads/team_{team}/{upload}/orders.csv", "replace_file"),
            ("legacy_folder_replace_file", "managed/team_{team}/orders.csv", "replace_file"),
            ("legacy_folder_file_action", "managed/team_{team}/orders.csv", "file"),
        ]
    )
    def test_a_new_file_for_a_migrated_table_starts_the_sync_that_adopts_it(
        self, _name: str, key: str, path: str
    ) -> None:
        self.flag.side_effect = _warehouse_api_flag
        table, schema = self._migrated_table(key)
        old_url = table.url_pattern
        self.get_columns.return_value = dict(REPLACEMENT_COLUMNS)

        with patch(f"{VIEW_MODULE}.boto3.client") as legacy_s3:
            if path == "replace_file":
                response = self._replace(table)
            else:
                response = self._legacy_file_action()

        expected_status = status.HTTP_202_ACCEPTED if path == "replace_file" else status.HTTP_201_CREATED
        assert response.status_code == expected_status, response.json()
        assert response.json()["id"] == str(table.id)
        # The legacy action no longer writes over the file the table reads.
        legacy_s3.assert_not_called()
        schema.refresh_from_db()
        schema.source.refresh_from_db()
        job_inputs = schema.source.job_inputs
        if path == "replace_file":
            assert job_inputs["upload_id"] == NEW_UPLOAD_ID
        else:
            [written] = self.s3.written
            assert written == (f"test-bucket/file_uploads/team_{self.team.pk}/{job_inputs['upload_id']}/orders_v2.csv")
        assert (job_inputs["filename"], job_inputs["file_format"]) == ("orders_v2.csv", "csv")
        [superseded] = (schema.source.connection_metadata or {})["file_upload"]["superseded"]
        if key.startswith("managed/"):
            assert superseded["legacy_filename"] == "orders.csv"
        else:
            assert (superseded["upload_id"], superseded["filename"]) == (UPLOAD_ID, "orders.csv")
        assert schema.schema_metadata is not None
        assert schema.schema_metadata["csv"]["column_types"] == {"id": "integer", "placed_at": "datetime"}
        assert schema.schema_metadata["self_managed_table"]["table_id"] == str(table.id)
        self.schedule.assert_called_once_with(schema, create=True, should_sync=False, trigger_immediately=False)
        assert self.trigger_count == 1
        assert self.trigger.call_args.kwargs["billable"] is True
        # Until that sync publishes, the table reads its old file, and the sync still adopts the same row.
        table.refresh_from_db()
        assert (table.name, table.url_pattern, table.external_data_source_id) == ("orders", old_url, None)
        assert find_replaced_self_managed_table(schema, schema.source) == table
        assert self.s3.removed == []

    @parameterized.expand(["sync_running", "table_changed_since_migration"])
    def test_a_migrated_table_refuses_a_new_file_it_cant_take(self, case: str) -> None:
        table, schema = self._migrated_table("managed/team_{team}/orders.csv")
        if case == "sync_running":
            ExternalDataJob.objects.create(
                team=self.team, pipeline=schema.source, schema=schema, status=ExternalDataJob.Status.RUNNING
            )
        else:
            DataWarehouseTable.objects.filter(pk=table.pk).update(
                url_pattern=f"https://warehouse.posthog.test/managed/team_{self.team.pk}/other.csv"
            )

        response = self._replace(table)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        schema.source.refresh_from_db()
        assert schema.source.job_inputs["upload_id"] == ""
        assert "file_upload" not in (schema.source.connection_metadata or {})
        self.trigger.assert_not_called()

    def test_a_migrated_source_can_be_updated_before_its_next_upload(self) -> None:
        _, schema = self._migrated_table("managed/team_{team}/orders.csv")

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{schema.source_id}/",
            {"description": "Orders", "job_inputs": {"upload_id": NEW_UPLOAD_ID, "filename": "orders_v2.csv"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        schema.source.refresh_from_db()
        assert schema.source.description == "Orders"
        assert (schema.source.job_inputs["upload_id"], schema.source.job_inputs["filename"]) == ("", "")

    def test_a_refused_legacy_file_action_deletes_the_file_it_stored(self) -> None:
        self.flag.side_effect = _warehouse_api_flag
        _, schema = self._migrated_table("managed/team_{team}/orders.csv")
        ExternalDataJob.objects.create(
            team=self.team, pipeline=schema.source, schema=schema, status=ExternalDataJob.Status.RUNNING
        )
        self.get_columns.return_value = dict(REPLACEMENT_COLUMNS)

        with patch(f"{VIEW_MODULE}.boto3.client"):
            response = self._legacy_file_action()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        [written] = self.s3.written
        assert self.s3.removed == [written]
        schema.source.refresh_from_db()
        assert schema.source.job_inputs["upload_id"] == ""
        self.trigger.assert_not_called()

    @parameterized.expand(["reload", "resync"])
    def test_a_migrated_table_cant_sync_before_its_next_upload(self, action: str) -> None:
        _, schema = self._migrated_table("managed/team_{team}/orders.csv")

        response = self.client.post(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/{action}/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Upload the file" in response.json()["message"]
        assert not ExternalDataJob.objects.filter(team=self.team).exists()
        self.trigger.assert_not_called()

    @parameterized.expand(["reload", "resync"])
    def test_a_table_that_imported_its_file_points_to_replace_file(self, action: str) -> None:
        _, schema = self._table_with_source()
        ExternalDataJob.objects.create(
            team=self.team, pipeline=schema.source, schema=schema, status=ExternalDataJob.Status.COMPLETED
        )
        self.trigger.reset_mock()

        response = self.client.post(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/{action}/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Replace file" in response.json()["message"]
        self.trigger.assert_not_called()

    @parameterized.expand(
        [
            ("linked", None),
            ("pinned", "managed/team_{team}/orders.csv"),
            ("pinned_in_upload_folder", "file_uploads/team_{team}/{upload}/orders.csv"),
        ]
    )
    def test_the_schema_and_source_name_the_table_and_the_file(self, _name: str, migrated_key: str | None) -> None:
        if migrated_key is None:
            table, schema = self._table_with_source()
        else:
            table, schema = self._migrated_table(migrated_key)
            assert schema.table_id is None

        schema_body = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/").json()
        source_body = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/{schema.source_id}/"
        ).json()

        assert schema_body["table_id"] == str(table.id)
        assert source_body["schemas"][0]["table_id"] == str(table.id)
        assert source_body["file_name"] == "orders.csv"
        assert schema_body["source"]["file_name"] == "orders.csv"
        assert source_body["job_inputs"] == {}

    @parameterized.expand(["other_team", "deleted"])
    def test_a_pinned_table_that_is_not_live_in_the_team_is_not_returned(self, case: str) -> None:
        table, schema = self._migrated_table("managed/team_{team}/orders.csv")
        if case == "deleted":
            DataWarehouseTable.objects.filter(pk=table.pk).update(deleted=True)
        else:
            other_team = Team.objects.create(organization=self.organization, name="Other")
            DataWarehouseTable.objects.filter(pk=table.pk).update(team=other_team)

        body = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/").json()

        assert body["table_id"] is None

    @patch(f"{SOURCE_VIEWS}.delete_discover_schemas_schedule")
    @patch(f"{SOURCE_VIEWS}.delete_external_data_schedule")
    @patch(f"{SOURCE_VIEWS}.bulk_delete_external_data_schedules", return_value=[])
    def test_deleting_a_migrated_source_never_deletes_the_file_its_table_reads(self, *_mocks: object) -> None:
        table, schema = self._migrated_table("managed/team_{team}/orders.csv")
        self.get_columns.return_value = dict(REPLACEMENT_COLUMNS)
        # The sync of the new file never finishes, so the table still reads the old one.
        assert self._replace(table).status_code == status.HTTP_202_ACCEPTED

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{schema.source_id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        table.refresh_from_db()
        assert table.deleted is False
        assert self.s3.removed == [f"test-bucket/file_uploads/team_{self.team.pk}/{NEW_UPLOAD_ID}/orders_v2.csv"]
