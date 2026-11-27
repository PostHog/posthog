from typing import Any

import pytest

from products.warehouse_sources.sources.amazon_s3.source import AmazonS3Source
from products.warehouse_sources.sources.sdk import SourceFieldSelectConfig
from products.warehouse_sources.sources.sdk.testing import INVALID_CONFIG_ERROR, open_store

VALUES: dict[str, Any] = {
    "url_pattern": "https://customer-data.s3.eu-west-1.amazonaws.com/exports/",
    "access_key_id": "AKIAEXAMPLE",
    "secret_access_key": "secret",
}

CSV_FORMATS = ["infer", "csv", "csv_no_header"]
NON_CSV_FORMATS = ["jsonl", "parquet", "delta"]


def test_reads_from_its_own_endpoint() -> None:
    source = AmazonS3Source()
    config = source.object_store_config(source.parse_config(VALUES))

    store = open_store(config)

    assert config.location_url == "https://customer-data.s3.eu-west-1.amazonaws.com/exports/"
    assert getattr(store.fs, "endpoint_url", None) is None
    assert store.delta_uri("sales") == "s3://customer-data/exports/sales"
    assert {"AWS_REGION": "eu-west-1"}.items() <= store.delta_storage_options.items()
    assert "AWS_ENDPOINT_URL" not in store.delta_storage_options


@pytest.mark.parametrize(
    "overrides",
    [
        {"url_pattern": "https://customer-data.s3.us-east-1.amazonaws.com.evil.example.com/a.csv"},
        {"url_pattern": "https://evil.example.com/customer-data/a.csv"},
        {"url_pattern": "https://s3.us-east-1.amazonaws.com/Not_A_Bucket/a.csv"},
    ],
)
def test_settings_that_could_retarget_the_request_are_rejected(overrides: dict[str, str]) -> None:
    source = AmazonS3Source()

    valid, message = source.validate_credentials(source.parse_config({**VALUES, **overrides}), team_id=1)

    assert not valid
    assert message is not None and message.startswith(INVALID_CONFIG_ERROR)


@pytest.mark.parametrize("file_format", CSV_FORMATS + NON_CSV_FORMATS)
def test_the_csv_quote_option_shows_only_under_csv_formats(file_format: str) -> None:
    fields = AmazonS3Source().get_source_config.fields

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
    source = AmazonS3Source()

    options = source.discovery_options(source.parse_config({**VALUES, "file_format": file_format}))

    assert options.file_format == expected_format
    assert options.allow_double_quotes is expected_allow_double_quotes


@pytest.mark.parametrize(
    "url, expected",
    [
        ("s3://customer-data", "customer-data/"),
        ("s3://customer-data/exports", "customer-data/exports/"),
        ("s3://customer-data/exports/", "customer-data/exports/"),
        ("https://customer-data.s3.amazonaws.com/exports/2026/orders.csv", None),
        ("https://s3.eu-west-1.amazonaws.com/customer-data/exports/**/*.parquet", None),
    ],
)
def test_the_table_root_reads_only_the_url(url: str, expected: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_bucket: str) -> str:
        raise AssertionError("the table root must not look up the bucket region")

    monkeypatch.setattr("products.warehouse_sources.sources.amazon_s3.source.lookup_s3_bucket_region", refuse)
    source = AmazonS3Source()

    assert source.table_root(source.parse_config({**VALUES, "url_pattern": url})) == expected
