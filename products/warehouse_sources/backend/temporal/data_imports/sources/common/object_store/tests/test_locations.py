from collections.abc import Callable

import pytest

from django.test import override_settings

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    AzureBlobConfig,
    ObjectStoreConfig,
    ObjectStoreProvider,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    BLOCKED_LOCATION_ERROR,
    INVALID_CONFIG_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.locations import (
    KeySelection,
    StorageUrl,
    parse_azure_url,
    parse_gcs_url,
    parse_r2_url,
    parse_s3_url,
    select_keys,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    validate_store_location,
)

R2_ACCOUNT = "0123456789abcdef0123456789abcdef"
Parser = Callable[[str], StorageUrl]


class TestParseUrl:
    @parameterized.expand(
        [
            (
                "s3_virtual_hosted",
                parse_s3_url,
                "https://acme-exports.s3.eu-central-1.amazonaws.com/raw/team_7/orders/**/*.parquet",
                StorageUrl(bucket="acme-exports", key="raw/team_7/orders/**/*.parquet", region="eu-central-1"),
            ),
            (
                "s3_virtual_hosted_dotted_bucket",
                parse_s3_url,
                "https://acme.exports.s3.us-west-2.amazonaws.com/a.csv",
                StorageUrl(bucket="acme.exports", key="a.csv", region="us-west-2"),
            ),
            (
                "s3_path_style",
                parse_s3_url,
                "https://s3.ap-southeast-2.amazonaws.com/acme-exports/daily/*.csv",
                StorageUrl(bucket="acme-exports", key="daily/*.csv", region="ap-southeast-2"),
            ),
            (
                "s3_bucket_root",
                parse_s3_url,
                "https://acme-exports.s3.us-east-1.amazonaws.com",
                StorageUrl(bucket="acme-exports", key="", region="us-east-1"),
            ),
            (
                "s3_question_mark_is_a_glob",
                parse_s3_url,
                "https://acme-exports.s3.us-east-1.amazonaws.com/part-?.csv",
                StorageUrl(bucket="acme-exports", key="part-?.csv", region="us-east-1"),
            ),
            (
                "s3_percent_encoded_key",
                parse_s3_url,
                "HTTPS://Acme-Exports.S3.us-east-1.amazonaws.com/my%20files/a.csv",
                StorageUrl(bucket="acme-exports", key="my files/a.csv", region="us-east-1"),
            ),
            (
                "gcs_https",
                parse_gcs_url,
                "https://storage.googleapis.com/acme_exports/orders/{2024..2026}/*.jsonl",
                StorageUrl(bucket="acme_exports", key="orders/{2024..2026}/*.jsonl"),
            ),
            (
                "gcs_gs_scheme",
                parse_gcs_url,
                "gs://acme_exports/orders/",
                StorageUrl(bucket="acme_exports", key="orders/"),
            ),
            (
                "r2",
                parse_r2_url,
                f"https://{R2_ACCOUNT}.r2.cloudflarestorage.com/acme-exports/orders/*.csv",
                StorageUrl(bucket="acme-exports", key="orders/*.csv", account=R2_ACCOUNT),
            ),
            (
                "azure",
                parse_azure_url,
                "https://acmestore.blob.core.windows.net/exports/orders/**",
                StorageUrl(bucket="exports", key="orders/**", account="acmestore"),
            ),
        ]
    )
    def test_accepts(self, _name: str, parse: Parser, url: str, expected: StorageUrl) -> None:
        assert parse(url) == expected

    @parameterized.expand(
        [
            ("s3_without_region_virtual_hosted", parse_s3_url, "https://acme.s3.amazonaws.com/a.csv", "region"),
            ("s3_without_region_path_style", parse_s3_url, "https://s3.amazonaws.com/acme/a.csv", "region"),
            ("s3_other_host", parse_s3_url, "https://acme.example.com/a.csv", "isn't an Amazon S3 URL"),
            (
                "s3_host_suffix",
                parse_s3_url,
                "https://acme.s3.us-east-1.amazonaws.com.example.com/a.csv",
                "isn't an Amazon S3 URL",
            ),
            ("s3_dashed_region", parse_s3_url, "https://acme.s3-us-east-1.amazonaws.com/a.csv", "isn't an Amazon S3"),
            ("s3_http", parse_s3_url, "http://acme.s3.us-east-1.amazonaws.com/a.csv", "https://"),
            ("s3_user_info", parse_s3_url, "https://x@acme.s3.us-east-1.amazonaws.com/a.csv", "user name"),
            ("s3_port", parse_s3_url, "https://acme.s3.us-east-1.amazonaws.com:444/a.csv", "port"),
            ("s3_backslash", parse_s3_url, "https://acme.s3.us-east-1.amazonaws.com\\@example.com/a", "user name"),
            ("s3_fragment", parse_s3_url, "https://acme.s3.us-east-1.amazonaws.com/a.csv#x", "'#'"),
            ("s3_parent_folder", parse_s3_url, "https://acme.s3.us-east-1.amazonaws.com/a/../b.csv", "'..'"),
            ("s3_encoded_parent_folder", parse_s3_url, "https://acme.s3.us-east-1.amazonaws.com/a/%2E%2E/b", "'..'"),
            ("s3_current_folder", parse_s3_url, "https://acme.s3.us-east-1.amazonaws.com/./b.csv", "'..'"),
            ("s3_empty_folder", parse_s3_url, "https://acme.s3.us-east-1.amazonaws.com/a//b.csv", "'//'"),
            ("s3_control_character", parse_s3_url, "https://acme.s3.us-east-1.amazonaws.com/a%0A.csv", "control"),
            ("s3_glob_in_bucket", parse_s3_url, "https://s3.us-east-1.amazonaws.com/acme-*/a.csv", "exact"),
            ("s3_encoded_bucket", parse_s3_url, "https://s3.us-east-1.amazonaws.com/acme%2Fx/a.csv", "exact"),
            ("s3_no_bucket", parse_s3_url, "https://s3.us-east-1.amazonaws.com/", "doesn't name a bucket"),
            ("s3_not_a_url", parse_s3_url, "acme-exports/a.csv", "full URL"),
            ("gcs_other_host", parse_gcs_url, "https://storage.cloud.google.com/acme/a.csv", "isn't a Google Cloud"),
            ("gcs_virtual_hosted", parse_gcs_url, "https://acme.storage.googleapis.com/a.csv", "isn't a Google Cloud"),
            ("gcs_s3_scheme", parse_gcs_url, "s3://acme/a.csv", "gs://"),
            ("r2_jurisdiction", parse_r2_url, f"https://{R2_ACCOUNT}.eu.r2.cloudflarestorage.com/a/b.csv", "R2 URL"),
            ("r2_short_account", parse_r2_url, "https://abc.r2.cloudflarestorage.com/a/b.csv", "R2 URL"),
            ("r2_other_host", parse_r2_url, f"https://{R2_ACCOUNT}.example.com/a/b.csv", "R2 URL"),
            ("azure_other_cloud", parse_azure_url, "https://acme.blob.core.chinacloudapi.cn/x/a.csv", "Azure Blob"),
            ("azure_dfs_host", parse_azure_url, "https://acme.dfs.core.windows.net/x/a.csv", "Azure Blob"),
        ]
    )
    def test_refuses(self, _name: str, parse: Parser, url: str, detail: str) -> None:
        with pytest.raises(ObjectStorageError) as error:
            parse(url)

        message = str(error.value)
        assert message.startswith(INVALID_CONFIG_ERROR)
        assert detail in message

    def test_a_url_without_a_region_gives_an_example(self) -> None:
        with pytest.raises(ObjectStorageError, match=r"such as https://[a-z-]+\.s3\.us-east-1\.amazonaws\.com/"):
            parse_s3_url("https://acme-exports.s3.amazonaws.com/a.csv")


class TestSelectKeys:
    @parameterized.expand(
        [
            ("bucket_root", "", KeySelection(prefix="", listing_prefix="", pattern=None)),
            ("folder", "raw/orders/", KeySelection(prefix="raw/orders", listing_prefix="", pattern=None)),
            ("folder_or_file", "raw/orders", KeySelection(prefix="raw", listing_prefix="orders", pattern=None)),
            ("file_at_the_root", "orders.csv", KeySelection(prefix="", listing_prefix="orders.csv", pattern=None)),
            (
                "glob_after_folders",
                "raw/team_7/orders/**/*.parquet",
                KeySelection(prefix="raw/team_7/orders", listing_prefix="", pattern="**/*.parquet"),
            ),
            (
                "glob_inside_a_folder_name",
                "raw/orders-*/a.csv",
                KeySelection(prefix="raw", listing_prefix="", pattern="orders-*/a.csv"),
            ),
            ("glob_at_the_root", "*.csv", KeySelection(prefix="", listing_prefix="", pattern="*.csv")),
            (
                "glob_that_ends_at_a_folder",
                "raw/*/",
                KeySelection(prefix="raw", listing_prefix="", pattern="*/**"),
            ),
        ]
    )
    def test_select_keys(self, _name: str, key: str, expected: KeySelection) -> None:
        assert select_keys(key) == expected

    def test_a_glob_posthog_cant_read_is_an_invalid_config(self) -> None:
        with pytest.raises(ObjectStorageError, match=INVALID_CONFIG_ERROR):
            select_keys("raw/part-{1..2.csv")


class TestUrlLocationChecks:
    @parameterized.expand(
        [
            ("virtual_hosted", "https://posthog-owned.s3.us-east-1.amazonaws.com/a.csv"),
            ("path_style", "https://s3.us-east-1.amazonaws.com/posthog-owned/a.csv"),
        ]
    )
    def test_a_posthog_owned_bucket_is_blocked_in_either_url_form(self, _name: str, url: str) -> None:
        config = ObjectStoreConfig.from_url(
            ObjectStoreProvider.S3, parse_s3_url(url), access_key_id="AKIAEXAMPLE", secret_access_key="secret"
        )

        with override_settings(DATAWAREHOUSE_BUCKET="posthog-owned"):
            with pytest.raises(ObjectStorageError, match=BLOCKED_LOCATION_ERROR):
                validate_store_location(config)

    @parameterized.expand(
        [
            (
                "s3",
                ObjectStoreConfig.from_url(
                    ObjectStoreProvider.S3,
                    parse_s3_url("https://s3.eu-west-1.amazonaws.com/acme-exports/raw/orders/*.csv"),
                    access_key_id="AKIAEXAMPLE",
                    secret_access_key="secret",
                ),
                "https://acme-exports.s3.eu-west-1.amazonaws.com/raw/orders/",
            ),
            (
                "r2",
                ObjectStoreConfig.from_url(
                    ObjectStoreProvider.R2,
                    parse_r2_url(f"https://{R2_ACCOUNT}.r2.cloudflarestorage.com/acme-exports/raw/a.csv"),
                    access_key_id="AKIAEXAMPLE",
                    secret_access_key="secret",
                ),
                f"https://{R2_ACCOUNT}.r2.cloudflarestorage.com/acme-exports/raw/",
            ),
            (
                "azure",
                AzureBlobConfig.from_url(
                    parse_azure_url("https://acmestore.blob.core.windows.net/exports/raw/**"),
                    account_key="c2VjcmV0LWtleQ==",
                ),
                "https://acmestore.blob.core.windows.net/exports/raw/",
            ),
        ]
    )
    def test_the_checked_location_is_rebuilt_from_the_parsed_parts(
        self, _name: str, config: ObjectStoreConfig | AzureBlobConfig, expected: str
    ) -> None:
        assert config.location_url == expected
