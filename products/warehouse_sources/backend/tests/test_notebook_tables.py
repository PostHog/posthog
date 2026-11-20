import json
import base64
from urllib.parse import urlparse

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.notebook_warehouse_tables import NotebookTableError, get_notebook_table_writer

from products.access_control.backend.models.access_control import AccessControl
from products.warehouse_sources.backend.file_uploads import MAX_UPLOAD_SIZE_BYTES
from products.warehouse_sources.backend.logic.notebook_tables import (
    _object_url,
    build_notebook_table_s3_key,
    build_notebook_table_staging_s3_key,
    save_notebook_table,
    validate_notebook_table_name,
)
from products.warehouse_sources.backend.models.table import DataWarehouseTable

COLUMNS = {"score": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "valid": True}}


@override_settings(USE_LOCAL_SETUP=True, OBJECT_STORAGE_ENDPOINT="http://objectstorage:19000")
class TestPresignNotebookTableUpload(SimpleTestCase):
    @parameterized.expand(
        [("docker_kernel", True, "host.docker.internal:19000"), ("no_debug", False, "objectstorage:19000")]
    )
    def test_signs_a_size_limited_post_for_the_host_the_kernel_dials(self, _name: str, debug: bool, host: str) -> None:
        with override_settings(DEBUG=debug):
            upload = get_notebook_table_writer().presign_notebook_table_upload(1, "scores", "run-1")

        self.assertEqual(urlparse(upload.url).netloc, host)
        conditions = json.loads(base64.b64decode(upload.fields["policy"]))["conditions"]
        self.assertIn({"key": "notebook_tables/team_1/scores/staging/run-1.parquet"}, conditions)
        self.assertIn(["content-length-range", 1, MAX_UPLOAD_SIZE_BYTES], conditions)


class TestValidateNotebookTableName(BaseTest):
    def test_save_requires_its_initiating_user_to_exist(self):
        with self.assertRaisesRegex(NotebookTableError, "user who started this run"):
            validate_notebook_table_name(self.team.id, "scores", -1)

    @parameterized.expand(
        [
            ("written_by_a_notebook", "scores", "scores", True, None),
            ("fresh_name", "fresh_scores", "scores", False, None),
            ("bad_characters", "my-scores", "scores", False, "starts with a letter"),
            ("posthog_table", "events", "scores", False, "already exists"),
            ("another_table", "scores", "scores", False, "a notebook didn't create it"),
            ("renamed_table_still_reads_the_object", "scores", "archived_scores", True, "renamed table"),
        ]
    )
    def test_name_rules(
        self, _name: str, table_name: str, existing_name: str, notebook_owned: bool, error: str | None
    ) -> None:
        DataWarehouseTable.objects.create(
            team_id=self.team.id,
            name=existing_name,
            format="Parquet",
            url_pattern=(
                _object_url(build_notebook_table_s3_key(self.team.id, "scores", "run-1"))
                if notebook_owned
                else "https://bucket.example.com/upload.parquet"
            ),
        )
        if error is None:
            validate_notebook_table_name(self.team.id, table_name, self.user.id)
        else:
            with self.assertRaisesRegex(NotebookTableError, error):
                validate_notebook_table_name(self.team.id, table_name, self.user.id)

    @parameterized.expand([("replace", True), ("create", False)])
    def test_refuses_a_user_without_warehouse_edit_access(self, _name: str, table_exists: bool) -> None:
        table = DataWarehouseTable.objects.create(
            team_id=self.team.id,
            name="scores",
            format="Parquet",
            url_pattern=_object_url(build_notebook_table_s3_key(self.team.id, "scores", "run-1")),
        )
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])
        AccessControl.objects.create(
            team=self.team,
            # Resource-level warehouse rules live on the warehouse_objects umbrella.
            resource="warehouse_table" if table_exists else "warehouse_objects",
            resource_id=str(table.id) if table_exists else None,
            organization_member=self.organization_membership,
            access_level="viewer",
        )
        cache.clear()

        with self.assertRaisesRegex(NotebookTableError, "permission"):
            validate_notebook_table_name(self.team.id, "scores" if table_exists else "fresh_scores", self.user.id)


class TestSaveNotebookTable(BaseTest):
    def _save(self, run_id: str, s3: MagicMock, columns: dict | Exception = COLUMNS) -> str:
        s3.head_object.return_value = {"ContentLength": 128, "ETag": '"example"'}
        with (
            patch("products.warehouse_sources.backend.logic.notebook_tables._s3_client", return_value=s3),
            patch.object(
                DataWarehouseTable,
                "get_columns",
                side_effect=columns if isinstance(columns, Exception) else None,
                return_value=columns,
            ),
            patch("products.warehouse_sources.backend.logic.notebook_tables.validate_data_warehouse_table_columns"),
        ):
            return save_notebook_table(self.team.id, "scores", self.user.id, run_id)

    def test_publishes_the_staged_object_and_reuses_the_table(self):
        s3 = MagicMock()

        first_id = self._save("run-1", s3)
        second_id = self._save("run-2", s3, columns={"label": COLUMNS["score"]})

        self.assertEqual(first_id, second_id)
        table = DataWarehouseTable.objects.get(id=first_id)
        self.assertEqual(table.url_pattern, _object_url(build_notebook_table_s3_key(self.team.id, "scores", "run-2")))
        self.assertEqual(list(table.columns or {}), ["label"])
        with self.assertRaisesRegex(NotebookTableError, "newer run"):
            self._save("run-1", s3)
        self.assertEqual(self._save("run-2", s3), second_id)
        self.assertEqual(s3.copy_object.call_count, 2)

    def test_a_table_renamed_after_dispatch_keeps_its_object(self):
        s3 = MagicMock()
        table_id = self._save("run-1", s3)
        DataWarehouseTable.objects.filter(id=table_id).update(name="archived_scores")

        with (
            patch("products.warehouse_sources.backend.logic.notebook_tables.validate_notebook_table_name"),
            self.assertRaisesRegex(NotebookTableError, "Another table"),
        ):
            self._save("run-2", s3)

        self.assertEqual(s3.copy_object.call_count, 1)
        self.assertEqual(DataWarehouseTable.objects.filter(team_id=self.team.id).count(), 1)

    def test_failed_publication_leaves_the_previous_data_and_schema_live(self):
        s3 = MagicMock()
        table_id = self._save("run-1", s3)
        original = DataWarehouseTable.objects.get(id=table_id)
        with (
            patch.object(DataWarehouseTable, "save", side_effect=RuntimeError("write failed")),
            self.assertRaises(RuntimeError),
        ):
            self._save("run-2", s3, columns={"other": COLUMNS["score"]})
        current = DataWarehouseTable.objects.get(id=table_id)
        self.assertEqual((current.url_pattern, current.columns), (original.url_pattern, original.columns))
        unpublished_key = build_notebook_table_s3_key(self.team.id, "scores", "run-2")
        self.assertNotEqual(_object_url(unpublished_key), current.url_pattern)
        s3.delete_object.assert_any_call(Bucket=settings.DATAWAREHOUSE_BUCKET, Key=unpublished_key)

    def test_unreadable_upload_never_replaces_the_live_object(self):
        s3 = MagicMock()
        table_id = self._save("run-1", s3)

        with self.assertRaises(NotebookTableError):
            self._save("run-2", s3, columns=Exception("bad column"))

        self.assertEqual(s3.copy_object.call_count, 2)
        s3.delete_object.assert_called_with(
            Bucket=settings.DATAWAREHOUSE_BUCKET,
            Key=build_notebook_table_staging_s3_key(self.team.id, "scores", "run-2"),
        )
        self.assertEqual(list(DataWarehouseTable.objects.get(id=table_id).columns or {}), ["score"])
