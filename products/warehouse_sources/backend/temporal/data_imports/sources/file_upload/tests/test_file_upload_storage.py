from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from products.warehouse_sources.backend.file_uploads import LegacyUpload, UploadLocation
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.storage import (
    SupersededUpload,
    delete_source_uploads,
    release_superseded_uploads,
    superseded_metadata,
    superseded_uploads,
)

STORAGE = "products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.storage"
BUCKET = "ph-warehouse"
DOMAIN = "warehouse.example.com"
CURRENT_ID = "11111111-2222-4333-8444-555555555555"
OLD_ID = "22222222-2222-4333-8444-555555555555"
NEWER_ID = "33333333-2222-4333-8444-555555555555"
SYNC_STARTED_AT = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@override_settings(DATAWAREHOUSE_BUCKET=BUCKET, DATAWAREHOUSE_BUCKET_DOMAIN=DOMAIN)
class TestFileUploadStorage(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.s3 = MagicMock()
        patcher = patch(f"{STORAGE}.get_s3_client", return_value=self.s3)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _upload(self, upload_id: str, filename: str = "orders.csv") -> UploadLocation:
        return UploadLocation(team_id=self.team.pk, upload_id=upload_id, filename=filename)

    def _source(self, job_inputs: dict[str, Any], *superseded: SupersededUpload) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id="s",
            connection_id="c",
            status="Running",
            source_type="FileUpload",
            job_inputs=job_inputs,
            connection_metadata=superseded_metadata(*superseded),
        )

    def _inputs(self, upload_id: str, filename: str = "orders.csv") -> dict[str, str]:
        return {"upload_id": upload_id, "filename": filename, "file_format": "csv", "schema_name": "orders"}

    def _removed(self) -> list[str]:
        return [call.args[0] for call in self.s3.rm.call_args_list]

    def test_a_completed_sync_deletes_only_the_uploads_replaced_before_it_started(self) -> None:
        before = SupersededUpload(upload=self._upload(OLD_ID), superseded_at=SYNC_STARTED_AT - timedelta(minutes=1))
        after = SupersededUpload(upload=self._upload(NEWER_ID), superseded_at=SYNC_STARTED_AT + timedelta(minutes=1))
        source = self._source(self._inputs(CURRENT_ID), before, after)

        released = release_superseded_uploads(str(source.pk), self.team.pk, SYNC_STARTED_AT)

        assert released == [before.upload]
        assert self._removed() == [f"{BUCKET}/file_uploads/team_{self.team.pk}/{OLD_ID}/orders.csv"]
        source.refresh_from_db()
        assert superseded_uploads(source) == [after]

    @parameterized.expand(["another_source", "in_place_table", "superseded_by_another_source"])
    def test_an_upload_something_else_reads_is_kept(self, reader: str) -> None:
        old = self._upload(OLD_ID)
        entry = SupersededUpload(upload=old, superseded_at=SYNC_STARTED_AT - timedelta(minutes=1))
        source = self._source(self._inputs(CURRENT_ID), entry)
        if reader == "another_source":
            self._source(self._inputs(OLD_ID))
        elif reader == "in_place_table":
            DataWarehouseTable.objects.create(
                team=self.team, name="orders_copy", format="CSVWithNames", url_pattern=old.url_pattern, columns={}
            )
        else:
            self._source(self._inputs(NEWER_ID), entry)

        assert release_superseded_uploads(str(source.pk), self.team.pk, SYNC_STARTED_AT) == []
        self.s3.rm.assert_not_called()
        # The entry is done with either way: the other reader owns the file now.
        source.refresh_from_db()
        assert superseded_uploads(source) == []

    @parameterized.expand([("reads_it_in_place", False), ("adopted_into_its_source", True)])
    def test_a_legacy_file_a_migrated_table_read_is_deleted_only_once_no_table_reads_it(
        self, _name: str, deleted: bool
    ) -> None:
        legacy = LegacyUpload(team_id=self.team.pk, filename="orders.csv")
        entry = SupersededUpload(upload=legacy, superseded_at=SYNC_STARTED_AT - timedelta(minutes=1))
        source = self._source(self._inputs(CURRENT_ID), entry)
        DataWarehouseTable.objects.create(
            team=self.team,
            name="orders",
            format="CSVWithNames",
            url_pattern=legacy.url_pattern,
            columns={},
            external_data_source=source if deleted else None,
        )

        released = release_superseded_uploads(str(source.pk), self.team.pk, SYNC_STARTED_AT)

        assert released == ([legacy] if deleted else [])
        assert self._removed() == ([f"{BUCKET}/managed/team_{self.team.pk}/orders.csv"] if deleted else [])

    def test_deleting_a_source_deletes_its_files_inside_the_team_folder(self) -> None:
        legacy = LegacyUpload(team_id=self.team.pk, filename="orders.csv")
        source = self._source(
            self._inputs(CURRENT_ID),
            SupersededUpload(upload=self._upload(OLD_ID), superseded_at=SYNC_STARTED_AT),
            SupersededUpload(upload=legacy, superseded_at=SYNC_STARTED_AT),
        )
        source.deleted = True
        source.save()

        delete_source_uploads(source)

        assert self._removed() == [
            f"{BUCKET}/file_uploads/team_{self.team.pk}/{CURRENT_ID}/orders.csv",
            f"{BUCKET}/file_uploads/team_{self.team.pk}/{OLD_ID}/orders.csv",
            f"{BUCKET}/managed/team_{self.team.pk}/orders.csv",
        ]

    @parameterized.expand(
        [
            ("traversal_upload_id", {"upload_id": f"../team_999/{CURRENT_ID}", "filename": "orders.csv"}),
            ("traversal_filename", {"upload_id": CURRENT_ID, "filename": "../../team_999/x/orders.csv"}),
            ("absolute_filename", {"upload_id": CURRENT_ID, "filename": "/etc/passwd"}),
            ("missing", {}),
        ]
    )
    def test_crafted_stored_inputs_never_delete_anything(self, _name: str, job_inputs: dict[str, str]) -> None:
        source = self._source(job_inputs)
        source.connection_metadata = {
            "file_upload": {
                "superseded": [
                    {**job_inputs, "superseded_at": SYNC_STARTED_AT.isoformat()},
                    {"legacy_filename": "../team_999/orders.csv", "superseded_at": SYNC_STARTED_AT.isoformat()},
                ]
            }
        }
        source.save()

        release_superseded_uploads(str(source.pk), self.team.pk, SYNC_STARTED_AT)
        source.deleted = True
        source.save()
        delete_source_uploads(source)

        self.s3.rm.assert_not_called()

    def test_a_storage_failure_is_swallowed(self) -> None:
        self.s3.rm.side_effect = OSError("storage is down")
        source = self._source(self._inputs(CURRENT_ID))
        source.deleted = True
        source.save()

        assert delete_source_uploads(source) == []

    def test_the_upload_the_source_reads_again_is_kept(self) -> None:
        # A replacement pointed the source back at a file it had superseded.
        entry = SupersededUpload(upload=self._upload(OLD_ID), superseded_at=SYNC_STARTED_AT - timedelta(minutes=1))
        source = self._source(self._inputs(OLD_ID), entry)

        assert release_superseded_uploads(str(source.pk), self.team.pk, SYNC_STARTED_AT) == []
        self.s3.rm.assert_not_called()
        source.refresh_from_db()
        assert superseded_uploads(source) == []

    def test_an_upload_storage_fails_to_delete_stays_recorded_for_the_next_sync(self) -> None:
        self.s3.rm.side_effect = OSError("storage is down")
        entry = SupersededUpload(upload=self._upload(OLD_ID), superseded_at=SYNC_STARTED_AT - timedelta(minutes=1))
        source = self._source(self._inputs(CURRENT_ID), entry)

        assert release_superseded_uploads(str(source.pk), self.team.pk, SYNC_STARTED_AT) == []
        source.refresh_from_db()
        assert superseded_uploads(source) == [entry]

        self.s3.rm.side_effect = None
        assert release_superseded_uploads(str(source.pk), self.team.pk, SYNC_STARTED_AT) == [entry.upload]
        source.refresh_from_db()
        assert superseded_uploads(source) == []
