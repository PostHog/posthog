from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.models.util import (
    BUCKET_WILDCARD_ERROR_MESSAGE,
    get_view_or_table_by_name,
    reconstruct_ordered_columns,
    s3_url_pattern_has_bucket_wildcard,
    validate_warehouse_table_url_pattern,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestReconstructOrderedColumns(SimpleTestCase):
    @parameterized.expand(
        [
            # (name, columns, column_order, expected_order)
            # Legacy rows have no recorded order: fall back to the stored jsonb key order.
            ("legacy_null", {"b": 1, "a": 2}, None, ["b", "a"]),
            ("legacy_empty", {"b": 1, "a": 2}, [], ["b", "a"]),
            # Recorded order is honored even when the jsonb key order differs.
            ("exact", {"a": 1, "z": 2, "m": 3}, ["z", "m", "a"], ["z", "m", "a"]),
            # A recorded name no longer present in columns (dropped column) is skipped.
            ("removed_skipped", {"a": 1, "m": 3}, ["z", "m", "a"], ["m", "a"]),
            # A column absent from the recorded order (newly discovered) is appended after the rest.
            ("appended_at_end", {"z": 1, "a": 2, "new": 3}, ["z", "a"], ["z", "a", "new"]),
            # Duplicate recorded names do not duplicate the column.
            ("dedup_recorded", {"a": 1, "b": 2}, ["a", "a", "b"], ["a", "b"]),
        ]
    )
    def test_reconstruct_ordered_columns(self, _name, columns, column_order, expected_order):
        result = reconstruct_ordered_columns(columns, column_order)
        assert [name for name, _value in result] == expected_order
        # values stay paired with their names
        assert dict(result) == columns


class TestS3BucketWildcard(SimpleTestCase):
    @parameterized.expand(
        [
            # Path-style: bucket is the first path segment, so a glob there is the misconfiguration.
            ("path_style_wildcard_bucket", "https://s3.us-east-1.amazonaws.com/my-*-bucket/data/*.csv", True),
            ("path_style_brace_bucket", "https://s3.amazonaws.com/{a,b}/data.csv", True),
            # Path-style but the glob is in the key, not the bucket: legitimate.
            ("path_style_wildcard_key", "https://s3.us-east-1.amazonaws.com/real-bucket/data/*.csv", False),
            # Virtual-hosted style: bucket lives in the hostname, so the path glob is a valid key match.
            ("virtual_hosted_wildcard_key", "https://my-bucket.s3.us-east-1.amazonaws.com/data/*.csv", False),
            ("virtual_hosted_dotted_bucket", "https://my.bucket.s3.amazonaws.com/data/*.parquet", False),
            # No glob anywhere.
            ("no_wildcard", "https://s3.amazonaws.com/real-bucket/data.csv", False),
            ("empty", "", False),
        ]
    )
    def test_s3_url_pattern_has_bucket_wildcard(self, _name, url_pattern, expected):
        assert s3_url_pattern_has_bucket_wildcard(url_pattern) is expected

    def test_validator_rejects_bucket_wildcard_before_dns(self):
        # Runs before hostname resolution, so a bucket typo fails fast with a fixable message.
        is_valid, message = validate_warehouse_table_url_pattern(
            "https://s3.us-east-1.amazonaws.com/my-*-bucket/data/*.csv"
        )
        assert is_valid is False
        assert message == BUCKET_WILDCARD_ERROR_MESSAGE


class TestGetViewOrTableByName(BaseTest):
    def _create_warehouse_table(self, *, name, url_pattern, source=None, credential=None) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            external_data_source=source,
            credential=credential,
            url_pattern=url_pattern,
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

    def test_ignores_tables_of_deleted_sources(self):
        # A table orphaned by a soft-deleted source must not shadow the live table re-created under
        # the same name — this is the path that feeds joins and series table resolution.
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")

        deleted_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="old",
            connection_id="old",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        self._create_warehouse_table(
            name="pull_requests", url_pattern="s3://orphan/*", source=deleted_source, credential=credential
        )
        deleted_source.deleted = True
        deleted_source.save()

        live_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="new",
            connection_id="new",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        live_table = self._create_warehouse_table(
            name="pull_requests", url_pattern="s3://live/*", source=live_source, credential=credential
        )

        resolved = get_view_or_table_by_name(self.team, "pull_requests")

        assert isinstance(resolved, DataWarehouseTable)
        assert resolved.pk == live_table.pk
        assert resolved.url_pattern == "s3://live/*"

    def test_keeps_self_managed_table_without_source(self):
        # Guards the deleted-source exclusion against the Django exclude()-with-NULL gotcha:
        # a self-managed table (no source) must still resolve.
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")
        table = self._create_warehouse_table(name="self_managed", url_pattern="s3://self/*", credential=credential)

        resolved = get_view_or_table_by_name(self.team, "self_managed")

        assert isinstance(resolved, DataWarehouseTable)
        assert resolved.pk == table.pk

    def test_resolves_duplicate_live_table_names_to_newest(self):
        # Two live tables share a name (e.g. a re-sync produced a duplicate): newest wins.
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")
        older = self._create_warehouse_table(name="pull_requests", url_pattern="s3://older/*", credential=credential)
        newer = self._create_warehouse_table(name="pull_requests", url_pattern="s3://newer/*", credential=credential)

        # Pin created_at explicitly (bypasses auto_now_add) so the tiebreak is deterministic.
        DataWarehouseTable.objects.filter(pk=older.pk).update(created_at="2024-01-01T00:00:00+00:00")
        DataWarehouseTable.objects.filter(pk=newer.pk).update(created_at="2024-06-01T00:00:00+00:00")

        resolved = get_view_or_table_by_name(self.team, "pull_requests")

        assert isinstance(resolved, DataWarehouseTable)
        assert resolved.pk == newer.pk
        assert resolved.url_pattern == "s3://newer/*"
