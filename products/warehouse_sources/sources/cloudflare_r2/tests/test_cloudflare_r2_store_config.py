from typing import Any

import pytest

from products.warehouse_sources.sources.cloudflare_r2.source import CloudflareR2Source
from products.warehouse_sources.sources.sdk import SelfManagedCredential, SourceFieldSelectConfig
from products.warehouse_sources.sources.sdk.testing import (
    INVALID_CONFIG_ERROR,
    open_store,
    parse_self_managed_url,
    source_base,
)

R2_ACCOUNT_ID = "0123456789abcdef0123456789abcdef"
VALUES: dict[str, Any] = {
    "url_pattern": f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/customer-data/exports/",
    "access_key_id": "AKIAEXAMPLE",
    "secret_access_key": "secret",
}

CSV_FORMATS = ["infer", "csv", "csv_no_header"]
NON_CSV_FORMATS = ["jsonl", "parquet", "delta"]


@pytest.fixture
def resolvable_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    # The location check resolves the host, and the example hosts here don't exist.
    monkeypatch.setattr(source_base, "validate_warehouse_table_url_pattern", lambda _url: (True, ""))


def _credential(access_key: str = "AKIAEXAMPLE", access_secret: str = "c2VjcmV0") -> SelfManagedCredential:
    return SelfManagedCredential(access_key=access_key, access_secret=access_secret)


def test_reads_from_its_own_endpoint() -> None:
    source = CloudflareR2Source()
    config = source.object_store_config(source.parse_config(VALUES))

    store = open_store(config)

    assert config.location_url == f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/customer-data/exports/"
    assert getattr(store.fs, "endpoint_url", None) == f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    assert store.delta_uri("sales") == "s3://customer-data/exports/sales"
    assert {
        "AWS_REGION": "auto",
        "AWS_ENDPOINT_URL": f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    }.items() <= store.delta_storage_options.items()


@pytest.mark.parametrize(
    "overrides",
    [
        {"url_pattern": f"https://{R2_ACCOUNT_ID}.evil.example.com/data/a.csv"},
        {"url_pattern": f"https://{R2_ACCOUNT_ID[:-1]}.r2.cloudflarestorage.com/data/a.csv"},
        {"url_pattern": f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/data_with_underscore/a.csv"},
    ],
)
def test_settings_that_could_retarget_the_request_are_rejected(overrides: dict[str, str]) -> None:
    source = CloudflareR2Source()

    valid, message = source.validate_credentials(source.parse_config({**VALUES, **overrides}), team_id=1)

    assert not valid
    assert message is not None and message.startswith(INVALID_CONFIG_ERROR)


@pytest.mark.parametrize("file_format", CSV_FORMATS + NON_CSV_FORMATS)
def test_the_csv_quote_option_shows_only_under_csv_formats(file_format: str) -> None:
    fields = CloudflareR2Source().get_source_config.fields

    [select] = [f for f in fields if isinstance(f, SourceFieldSelectConfig) and f.name == "file_format"]
    [option] = [o for o in select.options if o.value == file_format]

    assert [f.name for f in option.fields or []] == (["csv_allow_double_quotes"] if file_format in CSV_FORMATS else [])
    assert "csv_allow_double_quotes" not in {f.name for f in fields}


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
    file_format: Any, expected_format: str, expected_allow_double_quotes: bool
) -> None:
    source = CloudflareR2Source()

    options = source.discovery_options(source.parse_config({**VALUES, "file_format": file_format}))

    assert options.file_format == expected_format
    assert options.allow_double_quotes is expected_allow_double_quotes


@pytest.mark.usefixtures("resolvable_hosts")
def test_a_self_managed_table_maps_to_its_bucket_and_credential() -> None:
    location = parse_self_managed_url(f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/exports/a.csv")

    job_inputs = CloudflareR2Source().job_inputs_for_self_managed(location, _credential())

    assert job_inputs["url_pattern"] == f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/exports/"
    assert (job_inputs["access_key_id"], job_inputs["secret_access_key"]) == ("AKIAEXAMPLE", "c2VjcmV0")
