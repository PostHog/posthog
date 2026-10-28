from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import patch

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from fsspec.implementations.local import LocalFileSystem

from products.warehouse_sources.backend.facade.source_config import SourceFieldSelectConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_s3.source import AmazonS3Source
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_blob.source import AzureBlobSource
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare_r2.source import CloudflareR2Source
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store import filesystem
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    BLOCKED_LOCATION_ERROR,
    INVALID_CONFIG_ERROR,
    TOO_MANY_FILES_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import (
    AzureObjectStore,
    open_store,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    ObjectStorageSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_cloud_storage.source import (
    GoogleCloudStorageSource,
)

MODIFIED_AT = datetime(2024, 5, 1, 12, 0, tzinfo=UTC)
R2_ACCOUNT_ID = "0123456789abcdef0123456789abcdef"
AZURE_KEY = "c2VjcmV0LWtleQ=="

S3_KEYS = {"access_key_id": "AKIAEXAMPLE", "secret_access_key": "secret"}
PROVIDERS: dict[str, tuple[ObjectStorageSource[Any], dict[str, Any]]] = {
    "s3": (
        AmazonS3Source(),
        {"url_pattern": "https://customer-data.s3.eu-west-1.amazonaws.com/exports/", **S3_KEYS},
    ),
    "gcs": (GoogleCloudStorageSource(), {"url_pattern": "gs://customer_data/exports/", **S3_KEYS}),
    "r2": (
        CloudflareR2Source(),
        {"url_pattern": f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/customer-data/exports/", **S3_KEYS},
    ),
    "azure": (
        AzureBlobSource(),
        {"url_pattern": "https://customerstore.blob.core.windows.net/customer-data/exports/", "account_key": AZURE_KEY},
    ),
}


def _store_config(provider: str, **overrides: Any) -> Any:
    source, values = PROVIDERS[provider]
    return source.object_store_config(source.parse_config({**values, **overrides}))


@pytest.mark.parametrize(
    "provider, location_url, endpoint_url, delta_uri, delta_options",
    [
        (
            "s3",
            "https://customer-data.s3.eu-west-1.amazonaws.com/exports/",
            None,
            "s3://customer-data/exports/sales",
            {"AWS_REGION": "eu-west-1"},
        ),
        (
            "gcs",
            "https://storage.googleapis.com/customer_data/exports/",
            "https://storage.googleapis.com",
            "s3://customer_data/exports/sales",
            {"AWS_REGION": "auto", "AWS_ENDPOINT_URL": "https://storage.googleapis.com"},
        ),
        (
            "r2",
            f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/customer-data/exports/",
            f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            "s3://customer-data/exports/sales",
            {"AWS_REGION": "auto", "AWS_ENDPOINT_URL": f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"},
        ),
        (
            "azure",
            "https://customerstore.blob.core.windows.net/customer-data/exports/",
            None,
            "az://customer-data/exports/sales",
            {"azure_storage_account_name": "customerstore", "azure_storage_account_key": AZURE_KEY},
        ),
    ],
)
def test_each_provider_reads_from_its_own_endpoint(
    provider: str, location_url: str, endpoint_url: str | None, delta_uri: str, delta_options: dict[str, str]
) -> None:
    config = _store_config(provider)

    store = open_store(config)

    assert config.location_url == location_url
    assert getattr(store.fs, "endpoint_url", None) == endpoint_url
    assert store.delta_uri("sales") == delta_uri
    assert delta_options.items() <= store.delta_storage_options.items()
    assert ("AWS_ENDPOINT_URL" in store.delta_storage_options) is (endpoint_url is not None)


@pytest.mark.parametrize(
    "provider, overrides",
    [
        ("s3", {"url_pattern": "https://customer-data.s3.us-east-1.amazonaws.com.evil.example.com/a.csv"}),
        ("s3", {"url_pattern": "https://evil.example.com/customer-data/a.csv"}),
        ("s3", {"url_pattern": "https://s3.us-east-1.amazonaws.com/Not_A_Bucket/a.csv"}),
        ("gcs", {"url_pattern": "https://storage.googleapis.com.evil.example.com/data/a.csv"}),
        ("gcs", {"url_pattern": "https://user@storage.googleapis.com/data/a.csv"}),
        ("gcs", {"url_pattern": "https://storage.googleapis.com:8443/data/a.csv"}),
        ("r2", {"url_pattern": f"https://{R2_ACCOUNT_ID}.evil.example.com/data/a.csv"}),
        ("r2", {"url_pattern": f"https://{R2_ACCOUNT_ID[:-1]}.r2.cloudflarestorage.com/data/a.csv"}),
        ("r2", {"url_pattern": f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/data_with_underscore/a.csv"}),
        ("azure", {"url_pattern": "https://store.evil.example.com/data/a.csv"}),
        ("azure", {"url_pattern": "https://customerstore.blob.core.windows.net/$root/a.csv"}),
        ("azure", {"url_pattern": "https://customerstore.blob.core.windows.net/data/a/../b/x.csv"}),
        ("azure", {"account_key": f"{AZURE_KEY};BlobEndpoint=https://evil.example.com"}),
        ("azure", {"account_key": " "}),
    ],
)
def test_provider_settings_that_could_retarget_the_request_are_rejected(
    provider: str, overrides: dict[str, str]
) -> None:
    source, values = PROVIDERS[provider]

    valid, message = source.validate_credentials(source.parse_config({**values, **overrides}), team_id=1)

    assert not valid
    assert message is not None and message.startswith(INVALID_CONFIG_ERROR)


@pytest.mark.parametrize(
    "bucket, valid",
    [
        ("a" * 63, True),
        ("a" * 64, False),
        # GCS allows a dotted name up to 222 characters, with each part at most 63.
        (f"{'a' * 32}.{'b' * 32}", True),
        (".".join(["a" * 63] * 3) + "." + "b" * 30, True),
        (".".join(["a" * 63] * 3) + "." + "b" * 31, False),
        (f"{'a' * 64}.example", False),
    ],
)
def test_gcs_bucket_name_length(bucket: str, valid: bool) -> None:
    url_pattern = f"https://storage.googleapis.com/{bucket}/exports/"
    if valid:
        assert _store_config("gcs", url_pattern=url_pattern).bucket == bucket
    else:
        with pytest.raises(ObjectStorageError, match=INVALID_CONFIG_ERROR):
            _store_config("gcs", url_pattern=url_pattern)


@pytest.mark.parametrize("provider", list(PROVIDERS))
def test_a_blocked_location_is_never_opened(provider: str) -> None:
    source, values = PROVIDERS[provider]

    with (
        patch(
            "products.warehouse_sources.backend.models.util.is_url_allowed", return_value=(False, "internal host")
        ) as is_url_allowed,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base.open_store"
        ) as opened,
    ):
        valid, message = source.validate_credentials(source.parse_config(values), team_id=1)

    assert not valid
    assert message is not None and message.startswith(BLOCKED_LOCATION_ERROR)
    assert is_url_allowed.call_args.args[0] == _store_config(provider).location_url
    opened.assert_not_called()


CSV_FORMATS = ["infer", "csv", "csv_no_header"]
NON_CSV_FORMATS = ["jsonl", "parquet", "delta"]


@pytest.mark.parametrize("provider", list(PROVIDERS))
@pytest.mark.parametrize("file_format", CSV_FORMATS + NON_CSV_FORMATS)
def test_the_csv_quote_option_shows_only_under_csv_formats(provider: str, file_format: str) -> None:
    source, _ = PROVIDERS[provider]
    fields = source.get_source_config.fields

    [select] = [f for f in fields if isinstance(f, SourceFieldSelectConfig) and f.name == "file_format"]
    [option] = [o for o in select.options if o.value == file_format]

    assert [f.name for f in option.fields or []] == (["csv_allow_double_quotes"] if file_format in CSV_FORMATS else [])
    assert "csv_allow_double_quotes" not in {f.name for f in fields}


@pytest.mark.parametrize("provider", list(PROVIDERS))
@pytest.mark.parametrize(
    "file_format, expected_format, expected_allow_double_quotes",
    [
        *[({"selection": f, "csv_allow_double_quotes": "false"}, f, False) for f in CSV_FORMATS],
        *[({"selection": f, "csv_allow_double_quotes": "true"}, f, True) for f in CSV_FORMATS],
        *[({"selection": f}, f, True) for f in CSV_FORMATS + NON_CSV_FORMATS],
        ("parquet", "parquet", True),
        ({}, "infer", True),
    ],
)
def test_discovery_options_read_the_csv_quote_option_from_the_file_format(
    provider: str, file_format: Any, expected_format: str, expected_allow_double_quotes: bool
) -> None:
    source, values = PROVIDERS[provider]

    options = source.discovery_options(source.parse_config({**values, "file_format": file_format}))

    assert options.file_format == expected_format
    assert options.allow_double_quotes is expected_allow_double_quotes


class _FakeContainerClient:
    def __init__(self, blobs: list[Any] | None = None, error: Exception | None = None) -> None:
        self.blobs = blobs or []
        self.error = error
        self.yielded = 0

    def list_blobs(self, name_starts_with: str | None = None, **_kwargs: Any) -> Any:
        if self.error is not None:
            raise self.error
        for blob in self.blobs:
            if blob.name.startswith(name_starts_with or ""):
                self.yielded += 1
                yield blob


def _blob(name: str, is_folder: bool = False) -> Any:
    metadata = {"hdi_isfolder": "true"} if is_folder else None
    return SimpleNamespace(name=name, size=0 if is_folder else 5, last_modified=MODIFIED_AT, metadata=metadata)


def _azure_store(client: _FakeContainerClient) -> AzureObjectStore:
    return AzureObjectStore(
        fs=LocalFileSystem(),
        root="customer-data/exports",
        delta_uri_prefix="az://",
        delta_storage_options={},
        container_client=client,
        prefix="exports",
    )


class TestAzureListing:
    @pytest.mark.parametrize(
        "relative_prefix, max_objects, expected, expected_yielded",
        [
            # The cap stops the pager, so the blobs after the second file are never fetched.
            ("", 2, ["a.csv", "orders/b.csv"], 3),
            ("orders", 10, ["orders/b.csv", "orders/c.csv"], 2),
            ("orders/b.csv", 10, ["orders/b.csv"], 1),
            ("missing", 10, [], 0),
        ],
    )
    def test_list_objects(
        self, relative_prefix: str, max_objects: int, expected: list[str], expected_yielded: int
    ) -> None:
        client = _FakeContainerClient(
            [
                _blob("exports/a.csv"),
                _blob("exports/orders", is_folder=True),
                _blob("exports/orders/b.csv"),
                _blob("exports/orders/c.csv"),
                _blob("exports/z.csv"),
                _blob("exports-archive/old.csv"),
            ]
        )

        listed = _azure_store(client).list_objects(relative_prefix, max_objects)

        assert [(stored.path, stored.size, stored.modified_at) for stored in listed] == [
            (path, 5, MODIFIED_AT) for path in expected
        ]
        assert client.yielded == expected_yielded

    def test_a_prefix_of_folder_blobs_fails_instead_of_walking_every_blob(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(filesystem, "MAX_LISTED_KEYS", 3)
        client = _FakeContainerClient([_blob(f"exports/{name}", is_folder=True) for name in "abcd"])

        with pytest.raises(ObjectStorageError, match=TOO_MANY_FILES_ERROR):
            _azure_store(client).list_objects("", 10)
        assert client.yielded == 4

    @pytest.mark.parametrize(
        "error, expected",
        [
            (ResourceNotFoundError("ContainerNotFound"), FileNotFoundError),
            (
                HttpResponseError(
                    "AuthenticationFailed", response=cast(Any, SimpleNamespace(status_code=403, reason="x"))
                ),
                PermissionError,
            ),
        ],
    )
    def test_rejected_requests_become_the_errors_the_source_translates(
        self, error: Exception, expected: type[Exception]
    ) -> None:
        with pytest.raises(expected):
            _azure_store(_FakeContainerClient(error=error)).list_objects("", 10)
