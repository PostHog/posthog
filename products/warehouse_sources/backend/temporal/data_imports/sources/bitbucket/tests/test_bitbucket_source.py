import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.bitbucket import BitbucketAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.source import BitbucketSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bitbucket import (
    BitbucketAuthMethodConfig,
    BitbucketSourceConfig,
)


def _config(
    selection: str = "api_token",
    email: str | None = "a@b.c",
    api_token: str | None = "tok",
    access_token: str | None = None,
) -> BitbucketSourceConfig:
    return BitbucketSourceConfig(
        workspace="my-workspace",
        auth_method=BitbucketAuthMethodConfig(
            selection=selection,  # type: ignore[arg-type]
            email=email,
            api_token=api_token,
            access_token=access_token,
        ),
    )


@pytest.mark.parametrize(
    "config,expected_auth",
    [
        (_config(), BitbucketAuth(email="a@b.c", api_token="tok")),
        (
            _config(selection="access_token", email=None, api_token=None, access_token="at"),
            BitbucketAuth(access_token="at"),
        ),
    ],
)
def test_get_auth_builds_the_right_credential(config, expected_auth):
    assert BitbucketSource()._get_auth(config) == expected_auth


@pytest.mark.parametrize(
    "config,expected_fragment",
    [
        # Missing credentials surface the curated message, not the raw internal error
        (_config(email=None), "email or API token is missing"),
        (_config(api_token=None), "email or API token is missing"),
        (_config(selection="access_token", access_token=None), "No Bitbucket access token"),
    ],
)
def test_validate_credentials_maps_missing_config_to_friendly_error(config, expected_fragment):
    valid, message = BitbucketSource().validate_credentials(config, team_id=1)
    assert valid is False
    assert expected_fragment in (message or "")


def test_validate_credentials_delegates_to_transport():
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.source.validate_bitbucket_credentials",
        return_value=(True, None),
    ) as validate:
        assert BitbucketSource().validate_credentials(_config(), team_id=1) == (True, None)

    validate.assert_called_once_with(BitbucketAuth(email="a@b.c", api_token="tok"), "my-workspace")
