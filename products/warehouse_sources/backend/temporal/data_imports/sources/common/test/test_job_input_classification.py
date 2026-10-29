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
            connection={"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_fake"}},
            selectors={"stripe_account_id": "acct_fake"},
            settings={"balance_history_all_customers": {"enabled": False}},
            runtime={},
        ),
    ),
    (
        "oauth_option_of_auth_method_is_a_reference",
        ExternalDataSourceType.STRIPE,
        {
            "auth_method": {"selection": "oauth", "stripe_integration_id": 12},
            "stripe_account_id": "acct_fake",
        },
        SplitJobInputs(
            connection={},
            references={"auth_method": {"selection": "oauth", "stripe_integration_id": 12}},
            selectors={"stripe_account_id": "acct_fake"},
            settings={},
            runtime={},
        ),
    ),
    (
        "oauth_option_with_a_stray_typed_in_key_stays_a_connection_field",
        ExternalDataSourceType.STRIPE,
        {"auth_method": {"selection": "oauth", "stripe_integration_id": 12, "stripe_secret_key": "sk_test_fake"}},
        SplitJobInputs(
            connection={
                "auth_method": {"selection": "oauth", "stripe_integration_id": 12, "stripe_secret_key": "sk_test_fake"}
            },
            settings={},
            runtime={},
        ),
    ),
    (
        "serialized_oauth_option_with_empty_inactive_keys_is_a_reference",
        ExternalDataSourceType.STRIPE,
        {"auth_method": {"selection": "oauth", "stripe_integration_id": 12, "stripe_secret_key": None}},
        SplitJobInputs(
            connection={},
            references={"auth_method": {"selection": "oauth", "stripe_integration_id": 12, "stripe_secret_key": None}},
            settings={},
            runtime={},
        ),
    ),
    (
        "oauth_option_with_an_empty_string_inactive_key_is_a_reference",
        ExternalDataSourceType.STRIPE,
        {"auth_method": {"selection": "oauth", "stripe_integration_id": 12, "stripe_secret_key": ""}},
        SplitJobInputs(
            connection={},
            references={"auth_method": {"selection": "oauth", "stripe_integration_id": 12, "stripe_secret_key": ""}},
            settings={},
            runtime={},
        ),
    ),
    (
        "auth_method_without_a_selection_is_a_connection_field",
        ExternalDataSourceType.STRIPE,
        {"auth_method": {"stripe_integration_id": 12}},
        SplitJobInputs(connection={"auth_method": {"stripe_integration_id": 12}}, settings={}, runtime={}),
    ),
    (
        "auth_method_that_is_not_a_mapping_is_a_connection_field",
        ExternalDataSourceType.STRIPE,
        {"auth_method": "oauth"},
        SplitJobInputs(connection={"auth_method": "oauth"}, settings={}, runtime={}),
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
            connection={"hubspot_secret_key": "legacy-access-token"},
            references={"hubspot_integration_id": 42},
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
            connection={},
            references={"auth_method": {"selection": "oauth", "github_integration_id": 7}},
            settings={"repositories": ["posthog/posthog"], "repository": "posthog/posthog"},
            runtime={},
        ),
    ),
    (
        "token_option_of_auth_method_is_a_connection_field",
        ExternalDataSourceType.GITHUB,
        {
            "auth_method": {"selection": "pat", "personal_access_token": "ghp_fake"},
            "repositories": ["posthog/posthog"],
        },
        SplitJobInputs(
            connection={"auth_method": {"selection": "pat", "personal_access_token": "ghp_fake"}},
            settings={"repositories": ["posthog/posthog"]},
            runtime={},
        ),
    ),
    (
        "oauth_only_source_has_a_reference_and_selectors",
        ExternalDataSourceType.GOOGLEADS,
        {
            "google_ads_integration_id": 3,
            "customer_id": "123-456-7890",
            "is_mcc_account": {"enabled": True, "mcc_client_id": "987-654-3210"},
            "start_date": "2024-01-01",
        },
        SplitJobInputs(
            connection={},
            references={"google_ads_integration_id": 3},
            selectors={
                "customer_id": "123-456-7890",
                "is_mcc_account": {"enabled": True, "mcc_client_id": "987-654-3210"},
            },
            settings={"start_date": "2024-01-01"},
            runtime={},
        ),
    ),
    (
        "plain_field_marked_as_selector",
        ExternalDataSourceType.GOOGLEANALYTICS,
        {"google_analytics_integration_id": 5, "property_id": "123456789", "history_days": "30"},
        SplitJobInputs(
            connection={},
            references={"google_analytics_integration_id": 5},
            selectors={"property_id": "123456789"},
            settings={"history_days": "30"},
            runtime={},
        ),
    ),
    (
        "credential_account_select_stays_a_connection_field",
        ExternalDataSourceType.APPLESEARCHADS,
        {
            "auth_method": {"selection": "key_pair", "client_id": "c", "key_id": "k", "private_key": "fake"},
            "ad_account_id": "1234",
            "org_id": "99",
        },
        SplitJobInputs(
            connection={
                "auth_method": {"selection": "key_pair", "client_id": "c", "key_id": "k", "private_key": "fake"},
                "ad_account_id": "1234",
                "org_id": "99",
            },
            settings={},
            runtime={},
        ),
    ),
    (
        "aliased_select_option_decides_by_stored_value",
        ExternalDataSourceType.BIGQUERY,
        {"auth_type": {"selection": "service_account", "google_cloud_service_account_integration_id": 8}},
        SplitJobInputs(
            connection={},
            references={
                "auth_type": {"selection": "service_account", "google_cloud_service_account_integration_id": 8}
            },
            settings={},
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
    "parts",
    [
        {"connection": {"host": "a"}, "settings": {"host": "b"}},
        {"connection": {"host": "a"}, "runtime": {"host": "b"}},
        {"settings": {"schema": "a"}, "runtime": {"schema": "b"}},
        {"connection": {"account_id": "a"}, "references": {"account_id": "b"}},
        {"connection": {"account_id": "a"}, "selectors": {"account_id": "b"}},
        {"references": {"account_id": "a"}, "selectors": {"account_id": "b"}},
        {"selectors": {"account_id": "a"}, "settings": {"account_id": "b"}},
    ],
)
def test_split_job_inputs_rejects_a_key_in_two_parts(parts: dict[str, dict[str, Any]]) -> None:
    with pytest.raises(ValueError, match="more than one part"):
        SplitJobInputs(**{"connection": {}, "settings": {}, "runtime": {}, **parts})
