from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    SplitJobInputs,
    merge_job_inputs,
    split_job_inputs,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SSH_TUNNEL = {
    "enabled": True,
    "host": "bastion.example.com",
    "port": 22,
    "auth": {"selection": "password", "username": "tunnel", "password": "tunnel-secret"},
}

CASES: list[tuple[str, ExternalDataSourceType, dict[str, Any], SplitJobInputs]] = [
    (
        "sql_source_with_ssh_tunnel_and_cdc",
        ExternalDataSourceType.POSTGRES,
        {
            "host": "db.example.com",
            "port": "5432",
            "database": "app",
            "user": "reader",
            "password": "db-secret",
            "schema": "public",
            "ssh_tunnel": SSH_TUNNEL,
            "cdc_enabled": True,
            "cdc_slot_name": "posthog_slot",
            "cdc_consistent_point": "0/16B6C50",
        },
        SplitJobInputs(
            connection={
                "host": "db.example.com",
                "port": "5432",
                "database": "app",
                "user": "reader",
                "password": "db-secret",
                "ssh_tunnel": SSH_TUNNEL,
            },
            settings={"schema": "public"},
            runtime={"cdc_enabled": True, "cdc_slot_name": "posthog_slot", "cdc_consistent_point": "0/16B6C50"},
        ),
    ),
    (
        "api_key_source_with_nested_auth_select",
        ExternalDataSourceType.STRIPE,
        {
            "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_fake"},
            "stripe_account_id": "acct_fake",
            "balance_history_all_customers": {"enabled": False},
        },
        SplitJobInputs(
            connection={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_fake"},
                "stripe_account_id": "acct_fake",
            },
            settings={"balance_history_all_customers": {"enabled": False}},
            runtime={},
        ),
    ),
    (
        "oauth_pointer_source_with_legacy_token",
        ExternalDataSourceType.HUBSPOT,
        {
            "hubspot_integration_id": 42,
            "hubspot_secret_key": "legacy-access-token",
            "custom_properties": {"enabled": True, "contacts": "plan,tier"},
        },
        SplitJobInputs(
            connection={"hubspot_integration_id": 42, "hubspot_secret_key": "legacy-access-token"},
            settings={"custom_properties": {"enabled": True, "contacts": "plan,tier"}},
            runtime={},
        ),
    ),
    (
        "oauth_account_select_settings",
        ExternalDataSourceType.GITHUB,
        {
            "auth_method": {"selection": "oauth", "github_integration_id": 7},
            "repositories": ["posthog/posthog"],
            "repository": "posthog/posthog",
        },
        SplitJobInputs(
            connection={"auth_method": {"selection": "oauth", "github_integration_id": 7}},
            settings={"repositories": ["posthog/posthog"], "repository": "posthog/posthog"},
            runtime={},
        ),
    ),
    (
        "file_upload_object_keys",
        ExternalDataSourceType.FILEUPLOAD,
        {"upload_id": "0b9c", "filename": "orders.csv", "file_format": "csv", "schema_name": "orders"},
        SplitJobInputs(
            connection={},
            settings={},
            runtime={"upload_id": "0b9c", "filename": "orders.csv", "file_format": "csv", "schema_name": "orders"},
        ),
    ),
    (
        "object_store_shared_fields",
        ExternalDataSourceType.AMAZONS3,
        {
            "url_pattern": "s3://bucket/exports/*.csv",
            "access_key_id": "AKIAFAKE",
            "secret_access_key": "fake-secret",
            "file_format": {"selection": "csv", "csv_allow_double_quotes": "true"},
            "combine_files": {"enabled": False},
        },
        SplitJobInputs(
            connection={
                "url_pattern": "s3://bucket/exports/*.csv",
                "access_key_id": "AKIAFAKE",
                "secret_access_key": "fake-secret",
            },
            settings={
                "file_format": {"selection": "csv", "csv_allow_double_quotes": "true"},
                "combine_files": {"enabled": False},
            },
            runtime={},
        ),
    ),
    (
        "unknown_and_legacy_flat_keys_default_to_connection",
        ExternalDataSourceType.BIGQUERY,
        {
            "dataset_id": "analytics",
            "using_temporary_dataset": True,
            "pre_migration_job_inputs": {"private_key": "fake"},
        },
        SplitJobInputs(
            connection={"using_temporary_dataset": True, "pre_migration_job_inputs": {"private_key": "fake"}},
            settings={"dataset_id": "analytics"},
            runtime={},
        ),
    ),
    (
        "aliased_field_under_its_stored_name",
        ExternalDataSourceType.BIGQUERY,
        {
            "dataset_id": "analytics",
            "temporary_dataset": {"enabled": True, "temporary_dataset_id": "staging"},
        },
        SplitJobInputs(
            connection={},
            settings={
                "dataset_id": "analytics",
                "temporary_dataset": {"enabled": True, "temporary_dataset_id": "staging"},
            },
            runtime={},
        ),
    ),
    (
        "empty_inputs",
        ExternalDataSourceType.POSTGRES,
        {},
        SplitJobInputs(connection={}, settings={}, runtime={}),
    ),
]


@pytest.mark.parametrize(
    "source_type,job_inputs,expected", [case[1:] for case in CASES], ids=[case[0] for case in CASES]
)
def test_split_job_inputs(
    source_type: ExternalDataSourceType, job_inputs: dict[str, Any], expected: SplitJobInputs
) -> None:
    split = split_job_inputs(source_type, job_inputs)

    assert split == expected
    assert merge_job_inputs(split) == job_inputs


def test_split_job_inputs_accepts_none() -> None:
    assert split_job_inputs(ExternalDataSourceType.POSTGRES, None) == SplitJobInputs(
        connection={}, settings={}, runtime={}
    )


@pytest.mark.parametrize(
    "connection,settings,runtime",
    [
        ({"host": "a"}, {"host": "b"}, {}),
        ({"host": "a"}, {}, {"host": "b"}),
        ({}, {"schema": "a"}, {"schema": "b"}),
    ],
)
def test_split_job_inputs_rejects_a_key_in_two_parts(
    connection: dict[str, Any], settings: dict[str, Any], runtime: dict[str, Any]
) -> None:
    with pytest.raises(ValueError, match="more than one part"):
        SplitJobInputs(connection=connection, settings=settings, runtime=runtime)
