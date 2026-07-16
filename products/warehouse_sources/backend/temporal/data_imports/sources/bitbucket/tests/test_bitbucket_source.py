import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.bitbucket import (
    BitbucketAuth,
    BitbucketResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.source import BitbucketSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    BitbucketAuthMethodConfig,
    BitbucketSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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


def _source_inputs(
    schema_name: str = "pull_requests",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: object = None,
    incremental_field: str | None = None,
) -> mock.Mock:
    inputs = mock.Mock()
    inputs.schema_name = schema_name
    inputs.team_id = 1
    inputs.should_use_incremental_field = should_use_incremental_field
    inputs.db_incremental_field_last_value = db_incremental_field_last_value
    inputs.incremental_field = incremental_field
    return inputs


def test_source_type():
    assert BitbucketSource().source_type == ExternalDataSourceType.BITBUCKET


@pytest.mark.parametrize(
    "endpoint,supports_incremental",
    [
        ("repositories", True),
        ("pull_requests", True),
        ("commits", True),
        ("pipelines", True),
        # No verified server filter or stable cursor for these — offering an
        # incremental toggle would silently behave like a full refresh
        ("deployments", False),
        ("workspace_members", False),
    ],
)
def test_get_schemas_incremental_support(endpoint, supports_incremental):
    schemas = {s.name: s for s in BitbucketSource().get_schemas(_config(), team_id=1)}
    assert schemas[endpoint].supports_incremental is supports_incremental
    assert schemas[endpoint].supports_append is supports_incremental
    assert bool(schemas[endpoint].incremental_fields) is supports_incremental


def test_get_schemas_filters_by_names():
    schemas = BitbucketSource().get_schemas(_config(), team_id=1, names=["commits", "pipelines"])
    assert sorted(s.name for s in schemas) == ["commits", "pipelines"]


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


def test_get_resumable_source_manager_binds_resume_config():
    manager = BitbucketSource().get_resumable_source_manager(_source_inputs())
    assert isinstance(manager, ResumableSourceManager)
    assert manager._data_class is BitbucketResumeConfig


@pytest.mark.parametrize(
    "should_use_incremental,last_value,expected_last_value",
    [
        (True, "2024-06-01", "2024-06-01"),
        # A stale watermark must not leak into a full-refresh run
        (False, "2024-06-01", None),
    ],
)
def test_source_for_pipeline_plumbs_arguments(should_use_incremental, last_value, expected_last_value):
    inputs = _source_inputs(
        schema_name="commits",
        should_use_incremental_field=should_use_incremental,
        db_incremental_field_last_value=last_value,
        incremental_field="date",
    )
    manager = mock.Mock()

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.source.bitbucket_source"
    ) as transport:
        BitbucketSource().source_for_pipeline(_config(), manager, inputs)

    transport.assert_called_once_with(
        auth=BitbucketAuth(email="a@b.c", api_token="tok"),
        workspace="my-workspace",
        endpoint="commits",
        logger=inputs.logger,
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental,
        db_incremental_field_last_value=expected_last_value,
        incremental_field="date",
    )


def test_non_retryable_errors_cover_auth_failures():
    errors = BitbucketSource().get_non_retryable_errors()
    assert any("401 Client Error" in key for key in errors)
    assert any("403 Client Error" in key for key in errors)
