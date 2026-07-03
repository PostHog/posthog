import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldOauthConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InstagramSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.instagram import InstagramResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.settings import INSTAGRAM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source import InstagramSource
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


def _config() -> InstagramSourceConfig:
    return InstagramSourceConfig(instagram_integration_id=1)


def test_source_type():
    assert InstagramSource().source_type == ExternalDataSourceType.INSTAGRAM


def test_get_source_config_fields():
    cfg = InstagramSource().get_source_config

    assert [field.name for field in cfg.fields] == ["instagram_integration_id"]
    assert cfg.label == "Instagram"
    assert cfg.featureFlag == "dwh-instagram"
    assert cfg.releaseStatus == ReleaseStatus.ALPHA
    assert not cfg.unreleasedSource


def test_get_source_config_oauth_field_declares_required_scopes():
    cfg = InstagramSource().get_source_config
    oauth_field = cfg.fields[0]
    assert isinstance(oauth_field, SourceFieldOauthConfig)
    assert oauth_field.kind == "instagram"
    assert oauth_field.requiredScopes == (
        "instagram_basic,instagram_manage_insights,pages_show_list,pages_read_engagement"
    )


def test_get_schemas_returns_all_endpoints():
    schemas = InstagramSource().get_schemas(_config(), team_id=1)
    assert {s.name for s in schemas} == set(INSTAGRAM_ENDPOINTS.keys())


@pytest.mark.parametrize(
    "name,supports_incremental,incremental_field,field_type",
    [
        ("users", False, None, None),
        ("media", True, "timestamp", IncrementalFieldType.DateTime),
        ("stories", False, None, None),
        ("user_insights", True, "date", IncrementalFieldType.Date),
    ],
)
def test_get_schemas_incremental_flags(name, supports_incremental, incremental_field, field_type):
    schemas = {s.name: s for s in InstagramSource().get_schemas(_config(), team_id=1)}
    schema = schemas[name]

    assert schema.supports_incremental is supports_incremental
    assert schema.supports_append is supports_incremental
    if supports_incremental:
        assert schema.incremental_fields == [
            {
                "label": incremental_field,
                "field": incremental_field,
                "type": field_type,
                "field_type": field_type,
            }
        ]
    else:
        assert schema.incremental_fields == []


def test_get_schemas_default_sync_set():
    schemas = InstagramSource().get_schemas(_config(), team_id=1)
    by_default_on = {s.name for s in schemas if s.should_sync_default}
    assert by_default_on == {"users", "media", "user_insights"}


def test_get_schemas_filters_by_names():
    schemas = InstagramSource().get_schemas(_config(), team_id=1, names=["media", "stories"])
    assert {s.name for s in schemas} == {"media", "stories"}


def test_get_resumable_source_manager_uses_resume_config():
    inputs = mock.MagicMock()
    manager = InstagramSource().get_resumable_source_manager(inputs)
    assert manager._data_class is InstagramResumeConfig


def test_source_for_pipeline_plumbs_arguments():
    inputs = mock.MagicMock()
    inputs.schema_name = "media"
    inputs.team_id = 7
    inputs.should_use_incremental_field = True
    inputs.db_incremental_field_last_value = "2026-04-01"
    manager = mock.MagicMock()

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source.instagram_source"
    ) as mock_source:
        InstagramSource().source_for_pipeline(_config(), manager, inputs)

    mock_source.assert_called_once_with(
        config=mock.ANY,
        resource_name="media",
        team_id=7,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-04-01",
    )


def test_source_for_pipeline_forwards_last_value_when_not_incremental():
    inputs = mock.MagicMock()
    inputs.schema_name = "media"
    inputs.team_id = 7
    inputs.should_use_incremental_field = False
    inputs.db_incremental_field_last_value = "2026-04-01"

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source.instagram_source"
    ) as mock_source:
        InstagramSource().source_for_pipeline(_config(), mock.MagicMock(), inputs)

    # `instagram_source` applies the `should_use_incremental_field` guard itself, so the
    # call site forwards the raw value rather than pre-filtering it.
    assert mock_source.call_args[1]["db_incremental_field_last_value"] == "2026-04-01"
    assert mock_source.call_args[1]["should_use_incremental_field"] is False


def test_validate_credentials_handles_token_failure():
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source.get_access_token",
        side_effect=Exception("Failed to refresh token"),
    ):
        ok, message = InstagramSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "Could not load Instagram credentials" in (message or "")


def test_validate_credentials_handles_account_listing_failure():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source.get_access_token",
            return_value="token",
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source.discover_instagram_accounts",
            side_effect=Exception("boom"),
        ),
    ):
        ok, message = InstagramSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "Failed to list Instagram accounts" in (message or "")


def test_validate_credentials_rejects_when_no_linked_accounts():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source.get_access_token",
            return_value="token",
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source.discover_instagram_accounts",
            return_value=[],
        ),
    ):
        ok, message = InstagramSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "No Instagram professional account" in (message or "")


def test_validate_credentials_succeeds_with_linked_account():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source.get_access_token",
            return_value="token",
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source.discover_instagram_accounts",
            return_value=[{"id": "1", "username": "posthog", "page_name": "PostHog"}],
        ),
    ):
        ok, message = InstagramSource().validate_credentials(_config(), team_id=1)

    assert ok is True
    assert message is None


def test_non_retryable_errors_cover_auth_failures():
    errors = InstagramSource().get_non_retryable_errors()
    assert "Failed to refresh token for Instagram integration. Please re-authorize the integration." in errors
    assert any("access token is invalid" in key for key in errors)
    assert any("No Instagram professional account" in key for key in errors)
