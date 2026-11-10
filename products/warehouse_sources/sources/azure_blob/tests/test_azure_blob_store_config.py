from typing import Any

import pytest

from products.warehouse_sources.sources.azure_blob.source import AzureBlobSource
from products.warehouse_sources.sources.sdk import SelfManagedCredential, SourceFieldSelectConfig, UnmappableTableError
from products.warehouse_sources.sources.sdk.testing import (
    INVALID_CONFIG_ERROR,
    open_store,
    parse_self_managed_url,
    source_base,
)

AZURE_KEY = "c2VjcmV0LWtleQ=="
VALUES: dict[str, Any] = {
    "url_pattern": "https://customerstore.blob.core.windows.net/customer-data/exports/",
    "account_key": AZURE_KEY,
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
    source = AzureBlobSource()
    config = source.object_store_config(source.parse_config(VALUES))

    store = open_store(config)

    assert config.location_url == "https://customerstore.blob.core.windows.net/customer-data/exports/"
    assert getattr(store.fs, "endpoint_url", None) is None
    assert store.delta_uri("sales") == "az://customer-data/exports/sales"
    assert {
        "azure_storage_account_name": "customerstore",
        "azure_storage_account_key": AZURE_KEY,
    }.items() <= store.delta_storage_options.items()
    assert "AWS_ENDPOINT_URL" not in store.delta_storage_options


@pytest.mark.parametrize(
    "overrides",
    [
        {"url_pattern": "https://store.evil.example.com/data/a.csv"},
        {"url_pattern": "https://customerstore.blob.core.windows.net/$root/a.csv"},
        {"url_pattern": "https://customerstore.blob.core.windows.net/data/a/../b/x.csv"},
        {"account_key": f"{AZURE_KEY};BlobEndpoint=https://evil.example.com"},
        {"account_key": " "},
    ],
)
def test_settings_that_could_retarget_the_request_are_rejected(overrides: dict[str, str]) -> None:
    source = AzureBlobSource()

    valid, message = source.validate_credentials(source.parse_config({**VALUES, **overrides}), team_id=1)

    assert not valid
    assert message is not None and message.startswith(INVALID_CONFIG_ERROR)


@pytest.mark.parametrize("file_format", CSV_FORMATS + NON_CSV_FORMATS)
def test_the_csv_quote_option_shows_only_under_csv_formats(file_format: str) -> None:
    fields = AzureBlobSource().get_source_config.fields

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
    source = AzureBlobSource()

    options = source.discovery_options(source.parse_config({**VALUES, "file_format": file_format}))

    assert options.file_format == expected_format
    assert options.allow_double_quotes is expected_allow_double_quotes


@pytest.mark.usefixtures("resolvable_hosts")
def test_a_self_managed_table_takes_the_account_from_the_url_and_the_key_from_the_secret() -> None:
    location = parse_self_managed_url("https://examplestore.blob.core.windows.net/exports/a.csv")

    job_inputs = AzureBlobSource().job_inputs_for_self_managed(location, _credential(access_key="ExampleStore"))

    assert (job_inputs["url_pattern"], job_inputs["account_key"]) == (
        "https://examplestore.blob.core.windows.net/exports/",
        "c2VjcmV0",
    )


@pytest.mark.usefixtures("resolvable_hosts")
@pytest.mark.parametrize(
    "credential",
    [
        _credential(access_key="otherstore"),
        _credential(access_key="examplestore", access_secret="a;EndpointSuffix=example.com"),
    ],
    ids=["key_for_another_account", "key_that_is_not_base64"],
)
def test_a_self_managed_table_the_source_would_refuse_is_refused(credential: SelfManagedCredential) -> None:
    location = parse_self_managed_url("https://examplestore.blob.core.windows.net/exports/a.csv")

    with pytest.raises(UnmappableTableError):
        AzureBlobSource().job_inputs_for_self_managed(location, credential)
