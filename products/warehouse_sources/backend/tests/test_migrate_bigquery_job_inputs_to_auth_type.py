import importlib

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigquery import (
    BigQuerySourceConfig,
)

# The module name starts with a digit, so it cannot be imported with a normal import statement.
migration = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0165_migrate_bigquery_job_inputs_to_auth_type"
)

_KEY_FILE = {
    "project_id": "my-project",
    "private_key": "private-key",
    "private_key_id": "private-key-id",
    "client_email": "client-email",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def test_migrated_job_inputs_parse_as_a_key_file_source():
    """Every BigQuery source predates `auth_type`, so the reshape this migration performs is the
    only thing that keeps them parsing once the new config class requires it."""
    migrated = migration.nest_key_file_under_auth_type(
        {"key_file": dict(_KEY_FILE), "dataset_id": "my_dataset", "temporary-dataset": {"enabled": False}}
    )
    assert migrated is not None

    config = BigQuerySourceConfig.from_dict(migrated)

    assert config.auth_type.selection == "key_file"
    assert config.auth_type.key_file is not None
    assert config.auth_type.key_file.project_id == "my-project"
    # Everything outside the credential must survive untouched.
    assert config.dataset_id == "my_dataset"


@pytest.mark.parametrize(
    "job_inputs,expected_key_file",
    [
        ({"key_file": dict(_KEY_FILE)}, _KEY_FILE),
        # A source whose upload never landed still needs an `auth_type`, or it stops parsing and
        # reports a config error instead of the missing credentials it actually has.
        ({}, {}),
        ({"key_file": None}, {}),
    ],
)
def test_migration_nests_whatever_key_file_the_source_holds(job_inputs, expected_key_file):
    migrated = migration.nest_key_file_under_auth_type(job_inputs)

    assert migrated == {"auth_type": {"selection": "key_file", "key_file": expected_key_file}}


def test_migration_leaves_an_already_migrated_source_alone():
    """The migration can be re-run by a retry, and it must not wrap `auth_type` in a second one."""
    assert migration.nest_key_file_under_auth_type({"auth_type": {"selection": "service_account"}}) is None


@pytest.mark.parametrize(
    "auth_type,expected",
    [
        ({"selection": "key_file", "key_file": _KEY_FILE}, {"key_file": _KEY_FILE}),
        (
            {"selection": "service_account", "google_cloud_service_account_integration_id": 7},
            {"google_cloud_service_account_integration_id": 7},
        ),
    ],
)
def test_reverse_restores_the_shape_the_previous_release_reads(auth_type, expected):
    """A rollback runs the previous release against these rows, and that code reads `key_file` from
    the top level."""
    flattened = migration.flatten_auth_type_to_key_file({"auth_type": auth_type, "dataset_id": "my_dataset"})

    assert flattened == {**expected, "dataset_id": "my_dataset"}
