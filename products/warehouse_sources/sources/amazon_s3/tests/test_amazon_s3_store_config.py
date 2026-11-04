from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from unittest.mock import patch

from products.warehouse_sources.sources.amazon_s3.source import AmazonS3Source
from products.warehouse_sources.sources.sdk import (
    ROLE_NOT_FOUND_ERROR,
    AwsAuthError,
    ObjectStoreConfig,
    RoleCredentials,
    SelfManagedCredential,
    SourceFieldSelectConfig,
    UnmappableTableError,
)
from products.warehouse_sources.sources.sdk.testing import (
    INVALID_CONFIG_ERROR,
    open_store,
    parse_self_managed_url,
    source_base,
)

VALUES: dict[str, Any] = {
    "url_pattern": "https://customer-data.s3.eu-west-1.amazonaws.com/exports/",
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
    source = AmazonS3Source()
    config = source.object_store_config(source.parse_config(VALUES), team_id=1)

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


@pytest.mark.usefixtures("resolvable_hosts")
def test_a_self_managed_table_maps_to_its_bucket_and_credential() -> None:
    location = parse_self_managed_url("https://exports.s3.eu-west-1.amazonaws.com/a.csv")

    job_inputs = AmazonS3Source().job_inputs_for_self_managed(location, _credential(), team_id=1)

    assert job_inputs["url_pattern"] == "https://s3.eu-west-1.amazonaws.com/exports/"
    assert (job_inputs["access_key_id"], job_inputs["secret_access_key"]) == ("AKIAEXAMPLE", "c2VjcmV0")


@pytest.mark.usefixtures("resolvable_hosts")
@pytest.mark.parametrize(
    "url, credential",
    [
        ("https://exports.s3.amazonaws.com/a.csv", _credential()),
        ("https://s3.us-east-1.amazonaws.com/ab/a.csv", _credential()),
        ("https://exports.s3.us-east-1.amazonaws.com/a.csv", _credential(access_secret=" ")),
    ],
    ids=["without_region", "bucket_name_too_short", "empty_secret"],
)
def test_a_self_managed_table_the_source_would_refuse_is_refused(url: str, credential: SelfManagedCredential) -> None:
    with pytest.raises(UnmappableTableError):
        AmazonS3Source().job_inputs_for_self_managed(parse_self_managed_url(url), credential, team_id=1)


ROLE_CONFIG = {"url_pattern": VALUES["url_pattern"], "aws_auth": {"selection": "role", "aws_integration_id": "7"}}


def test_a_role_builds_a_store_without_keys() -> None:
    source = AmazonS3Source()
    role_credentials = RoleCredentials.create_from_metadata(
        {
            "access_key": "ASIAROLE",
            "secret_key": "secret-ROLE",
            "token": "token-ROLE",
            "expiry_time": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
        refresh_using=lambda: {},
        method="sts-assume-role",
    )

    with patch(
        "products.warehouse_sources.sources.amazon_s3.source.resolve_aws_credentials", return_value=role_credentials
    ) as resolve:
        store_config = cast(ObjectStoreConfig, source.object_store_config(source.parse_config(ROLE_CONFIG), team_id=1))

    auth, team_id, _session_actions = resolve.call_args.args
    assert (auth.selection, auth.aws_integration_id, team_id) == ("role", 7, 1)
    assert store_config.role_credentials is role_credentials
    assert (store_config.access_key_id, store_config.secret_access_key) == ("", "")


def test_a_role_that_cannot_be_resolved_fails_the_check_with_its_message() -> None:
    source = AmazonS3Source()

    with patch(
        "products.warehouse_sources.sources.amazon_s3.source.resolve_aws_credentials",
        side_effect=AwsAuthError(ROLE_NOT_FOUND_ERROR),
    ):
        valid, message = source.validate_credentials(source.parse_config(ROLE_CONFIG), team_id=1)

    assert not valid
    assert message is not None and ROLE_NOT_FOUND_ERROR in message
