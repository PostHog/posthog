import ipaddress

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.models.util import (
    get_view_or_table_by_name,
    reconstruct_ordered_columns,
    validate_warehouse_table_url_pattern,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

PUBLIC_IP = {ipaddress.ip_address("93.184.216.34")}


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


@override_settings(
    DATAWAREHOUSE_BUCKET_DOMAIN="warehouse-files.posthog.example",
    DATAWAREHOUSE_BUCKET="ph-warehouse",
    BUCKET_PATH="ph-warehouse",
    OBJECT_STORAGE_BUCKET="ph-objects",
    SESSION_RECORDING_V2_S3_BUCKET="ph-replay",
)
class TestValidateWarehouseTableUrlPattern(SimpleTestCase):
    @parameterized.expand(
        [
            # One bucket answers to several names. Each of these reaches PostHog's own storage, so a
            # check on any single form leaves the rest open.
            ("virtual_hosted_global", "https://ph-warehouse.s3.amazonaws.com/file_uploads/team_2/x.csv"),
            ("virtual_hosted_regional", "https://ph-warehouse.s3.us-east-1.amazonaws.com/file_uploads/x.csv"),
            ("virtual_hosted_dashed_region", "https://ph-warehouse.s3-us-west-2.amazonaws.com/x.csv"),
            ("virtual_hosted_dualstack", "https://ph-warehouse.s3.dualstack.us-east-1.amazonaws.com/x.csv"),
            ("path_style_global", "https://s3.amazonaws.com/ph-warehouse/x.csv"),
            ("path_style_regional", "https://s3.us-east-1.amazonaws.com/ph-warehouse/file_uploads/team_*/*/*.csv"),
            ("gcs_virtual_hosted", "https://ph-warehouse.storage.googleapis.com/x.csv"),
            ("gcs_path_style", "https://storage.googleapis.com/ph-warehouse/x.csv"),
            ("configured_bucket_domain", "https://warehouse-files.posthog.example/file_uploads/team_2/x.csv"),
            # Buckets other than the warehouse one are just as reachable from the ClickHouse node.
            ("object_storage_bucket", "https://s3.us-east-1.amazonaws.com/ph-objects/exports/x.csv"),
            ("session_replay_bucket", "https://ph-replay.s3.eu-central-1.amazonaws.com/x.json"),
        ]
    )
    def test_rejects_urls_that_address_posthog_storage(self, _name: str, url_pattern: str) -> None:
        is_valid, error_message = validate_warehouse_table_url_pattern(url_pattern)

        assert not is_valid
        assert "internal storage" in error_message

    @parameterized.expand(
        [
            ("brace_expansion", "https://s3.us-east-1.amazonaws.com/{ph-warehouse,acme}/x.csv"),
            ("wildcard", "https://s3.us-east-1.amazonaws.com/ph-*/x.csv"),
        ]
    )
    def test_rejects_a_glob_in_the_bucket_position(self, _name: str, url_pattern: str) -> None:
        is_valid, error_message = validate_warehouse_table_url_pattern(url_pattern)

        assert not is_valid
        assert "bucket name" in error_message

    @parameterized.expand(
        [
            ("customer_virtual_hosted", "https://acme-exports.s3.us-east-1.amazonaws.com/warehouse/*.parquet"),
            ("customer_path_style", "https://s3.us-east-1.amazonaws.com/acme-exports/warehouse/*.parquet"),
            # A PostHog bucket name used as a key prefix in someone else's bucket is theirs, not ours.
            ("our_bucket_name_as_a_key_prefix", "https://acme-exports.s3.amazonaws.com/ph-warehouse/*.csv"),
            ("non_storage_host", "https://files.acme.example/exports/*.csv"),
            # Percent-encoding is fine in the object key, only the bucket segment of a path-style
            # URL rejects it.
            ("percent_encoding_in_the_key", "https://s3.us-east-1.amazonaws.com/acme-exports/my%20file.csv"),
        ]
    )
    def test_allows_a_customers_own_bucket(self, _name: str, url_pattern: str) -> None:
        with (
            patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            patch("posthog.security.url_validation.resolve_host_ips", return_value=PUBLIC_IP),
        ):
            is_valid, error_message = validate_warehouse_table_url_pattern(url_pattern)

        assert is_valid, error_message

    @parameterized.expand(
        [
            (
                "path_style_encoded_slash_in_bucket_position",
                "https://s3.us-east-1.amazonaws.com/ph-warehouse%2Ffile_uploads/team_2/x.csv",
            ),
            ("path_style_encoded_char_in_bucket_position", "https://s3.us-east-1.amazonaws.com/acme%2dexports/x.csv"),
        ]
    )
    def test_rejects_percent_encoding_in_the_bucket_position(self, _name: str, url_pattern: str) -> None:
        # A request client that decodes %2F before splitting the path could resolve a different
        # bucket than this parser sees, so any percent-encoding there is rejected outright rather
        # than trusted to agree with whatever library ClickHouse uses.
        is_valid, error_message = validate_warehouse_table_url_pattern(url_pattern)

        assert not is_valid
        assert "percent-encoded" in error_message

    @parameterized.expand(
        [
            ("dot_segment_as_bucket", "https://s3.us-east-1.amazonaws.com/./ph-warehouse/x.csv"),
            ("dot_dot_segment_as_bucket", "https://s3.us-east-1.amazonaws.com/../ph-warehouse/x.csv"),
            # bucket resolves to "attacker" here, but a client that normalizes ".." before
            # connecting would resolve "ph-warehouse" instead - the exact case the percent-encoding
            # check above exists for, just via a different parser-vs-client disagreement.
            ("dot_dot_segment_later_in_the_path", "https://s3.us-east-1.amazonaws.com/attacker/../ph-warehouse/x.csv"),
        ]
    )
    def test_rejects_dot_segments_in_the_path(self, _name: str, url_pattern: str) -> None:
        is_valid, error_message = validate_warehouse_table_url_pattern(url_pattern)

        assert not is_valid
        assert "'.' or '..'" in error_message

    def test_allows_a_dot_within_a_path_segment(self) -> None:
        # Only a segment that IS exactly "." or ".." is rejected - a normal filename containing a
        # dot must not be caught by the same check.
        with (
            patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            patch("posthog.security.url_validation.resolve_host_ips", return_value=PUBLIC_IP),
        ):
            is_valid, error_message = validate_warehouse_table_url_pattern(
                "https://s3.us-east-1.amazonaws.com/acme-exports/reports/q1.2026/data.csv"
            )

        assert is_valid, error_message

    # Each of these is a hostname the old bespoke IP/DNS check did not reliably reject: it had no
    # domain-suffix or authority-parsing checks at all, and metadata.google.internal was only
    # caught if DNS actually resolved it in whatever environment the check ran in. All four are
    # checked by posthog.security.url_validation before DNS resolution, so none need
    # resolve_host_ips mocked - only is_dev_mode, to exercise the real check instead of the
    # local-dev bypass.
    @parameterized.expand(
        [
            ("metadata_domain", "https://metadata.google.internal/computeMetadata/v1/"),
            ("internal_tld_suffix", "https://data.corp/team_1/x.csv"),
            ("kubernetes_service_suffix", "https://minio.storage.svc.cluster.local/team_1/x.csv"),
            # \ before @ is parsed as part of the authority by urlparse but as a path separator by
            # the client that actually connects, so the host each of them sees can disagree.
            ("authority_bypass_backslash", "https://acme-exports.s3.amazonaws.com\\@169.254.169.254/x.csv"),
            ("authority_bypass_encoded_backslash", "https://acme-exports.s3.amazonaws.com%5c@169.254.169.254/x.csv"),
        ]
    )
    def test_rejects_ssrf_targets_gained_from_the_shared_url_validator(self, _name: str, url_pattern: str) -> None:
        with patch("posthog.security.url_validation.is_dev_mode", return_value=False):
            is_valid, error_message = validate_warehouse_table_url_pattern(url_pattern)

        assert not is_valid, error_message

    def test_rejects_a_private_ip_literal(self) -> None:
        # The old bespoke check's core case: a raw internal IP, blocked without any DNS lookup.
        with patch("posthog.security.url_validation.is_dev_mode", return_value=False):
            is_valid, error_message = validate_warehouse_table_url_pattern("https://10.0.0.5/team_1/x.csv")

        assert not is_valid, error_message

    def test_rejects_a_hostname_that_resolves_to_a_private_ip(self) -> None:
        # Same case, but through DNS - catches a hostname pointed at an internal address rather
        # than one supplied as a literal.
        with (
            patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            patch(
                "posthog.security.url_validation.resolve_host_ips",
                return_value={ipaddress.ip_address("10.0.0.5")},
            ),
        ):
            is_valid, error_message = validate_warehouse_table_url_pattern("https://internal-alias.example/x.csv")

        assert not is_valid, error_message


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
