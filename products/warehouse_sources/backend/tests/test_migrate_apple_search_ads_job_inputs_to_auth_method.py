import importlib

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applesearchads import (
    AppleSearchAdsSourceConfig,
)

# The module name starts with a digit, so it cannot be imported with a normal import statement.
migration = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0172_migrate_apple_search_ads_job_inputs_to_auth_method"
)

_KEY_PAIR = {
    "client_id": "SEARCHADS.client",
    "apple_team_id": "SEARCHADS.team",
    "key_id": "key-1",
    "private_key": "-----BEGIN EC PRIVATE KEY-----\nabc\n-----END EC PRIVATE KEY-----",
}


def test_a_migrated_source_still_reaches_its_key_pair_and_its_ad_account():
    """A flat source parses either way, because the config parser falls back to a flat read. What
    the migration changes is the branch: left unset, `selection` lands on its generated default and
    the edit form opens on Sign in with Apple with the key fields hidden."""
    migrated = migration.nest_key_pair_under_auth_method(
        {**_KEY_PAIR, "ad_account_id": "123456789", "start_date": "2026-06-01", "org_id": "555"}
    )
    assert migrated is not None

    config = AppleSearchAdsSourceConfig.from_dict(migrated)

    assert config.auth_method.selection == "key_pair"
    assert config.auth_method.client_id == "SEARCHADS.client"
    assert config.auth_method.private_key == _KEY_PAIR["private_key"]
    assert config.auth_method.apple_ads_integration_id is None
    # Everything outside the credential must stay at the top level. Moving `ad_account_id` into
    # the branch would leave every existing sync without the id it scopes every request by.
    assert (config.ad_account_id, config.start_date, config.org_id) == ("123456789", "2026-06-01", "555")


def test_the_migration_nests_the_key_pair_without_breaking_old_workers():
    migrated = migration.nest_key_pair_under_auth_method({**_KEY_PAIR, "ad_account_id": "123456789"})

    assert migrated == {
        **_KEY_PAIR,
        "ad_account_id": "123456789",
        "auth_method": {"selection": "key_pair", **_KEY_PAIR},
    }


@pytest.mark.parametrize(
    "job_inputs",
    [
        {"auth_method": {"selection": "key_pair", **_KEY_PAIR}},
        {"auth_method": {"selection": "oauth", "apple_ads_integration_id": 77}},
    ],
)
def test_the_migration_leaves_an_already_migrated_source_alone(job_inputs):
    """The migration can be re-run by a retry, and a second pass must not wrap the branch in
    another one or overwrite a connected account's credential with empty strings."""
    assert migration.nest_key_pair_under_auth_method(job_inputs) is None


def test_reverse_restores_the_shape_the_previous_release_reads():
    """A rollback runs the previous release against these rows, and that code reads the four key
    pair fields from the top level."""
    flattened = migration.flatten_auth_method_to_key_pair(
        {**_KEY_PAIR, "auth_method": {"selection": "key_pair", **_KEY_PAIR}, "ad_account_id": "123456789"}
    )

    assert flattened == {**_KEY_PAIR, "ad_account_id": "123456789"}


def test_reverse_leaves_a_connected_account_alone():
    """Flattening a grant would write an `apple_ads_integration_id` the previous release has no
    field for, and drop the branch that the next roll-forward needs."""
    job_inputs = {"auth_method": {"selection": "oauth", "apple_ads_integration_id": 77}}

    assert migration.flatten_auth_method_to_key_pair(job_inputs) is None
