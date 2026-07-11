import pytest
from unittest import mock

import requests
from google.auth.exceptions import RefreshError

from posthog.schema import ReleaseStatus, SourceFieldOauthConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GoogleAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.google_analytics import (
    GoogleAnalyticsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.settings import (
    GOOGLE_ANALYTICS_REPORT_SCHEMAS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source import (
    GoogleAnalyticsSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


def _config(property_id: str = "123456789") -> GoogleAnalyticsSourceConfig:
    return GoogleAnalyticsSourceConfig(property_id=property_id, google_analytics_integration_id=1)


def test_source_type():
    assert GoogleAnalyticsSource().source_type == ExternalDataSourceType.GOOGLEANALYTICS


def test_get_source_config_fields():
    cfg = GoogleAnalyticsSource().get_source_config

    field_names = {field.name for field in cfg.fields}
    assert field_names == {"google_analytics_integration_id", "property_id"}
    assert cfg.label == "Google Analytics"
    assert cfg.featureFlag == "dwh-google-analytics"
    assert cfg.releaseStatus == ReleaseStatus.ALPHA
    assert not cfg.unreleasedSource


def test_get_source_config_oauth_field_declares_required_scope():
    cfg = GoogleAnalyticsSource().get_source_config
    oauth_field = next(field for field in cfg.fields if field.name == "google_analytics_integration_id")
    assert isinstance(oauth_field, SourceFieldOauthConfig)
    assert oauth_field.kind == "google-analytics"
    assert oauth_field.requiredScopes == "https://www.googleapis.com/auth/analytics.readonly"


def test_get_schemas_returns_all_schemas_with_date_incremental():
    schemas = GoogleAnalyticsSource().get_schemas(_config(), team_id=1)

    assert {s.name for s in schemas} == set(GOOGLE_ANALYTICS_REPORT_SCHEMAS.keys())
    for schema in schemas:
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert schema.incremental_fields == [
            {
                "label": "date",
                "field": "date",
                "type": IncrementalFieldType.Date,
                "field_type": IncrementalFieldType.Date,
            }
        ]


def test_get_schemas_default_sync_set():
    schemas = GoogleAnalyticsSource().get_schemas(_config(), team_id=1)
    by_default_on = {s.name for s in schemas if s.should_sync_default}
    # Everything except `events` syncs by default; `events` is keyed on date+eventName,
    # so its volume scales with distinct event names and stays opt-in.
    assert by_default_on == {
        "website_overview",
        "daily_active_users",
        "weekly_active_users",
        "four_weekly_active_users",
        "devices",
        "locations",
        "pages",
        "traffic_sources",
        "user_acquisition",
    }


def test_get_schemas_filters_by_names():
    schemas = GoogleAnalyticsSource().get_schemas(_config(), team_id=1, names=["website_overview", "events"])
    assert {s.name for s in schemas} == {"website_overview", "events"}


def test_all_schemas_have_date_dimension_and_in_primary_key():
    # Every report is day-grained: `date` must be requested and lead the primary key
    # so merge-mode dedupe and incremental syncs behave.
    for name, schema in GOOGLE_ANALYTICS_REPORT_SCHEMAS.items():
        assert schema["dimensions"][0] == "date", name
        assert schema["primary_key"] == schema["dimensions"], name


def test_get_resumable_source_manager_uses_resume_config():
    inputs = mock.MagicMock()
    manager = GoogleAnalyticsSource().get_resumable_source_manager(inputs)
    assert manager._data_class is GoogleAnalyticsResumeConfig


def test_source_for_pipeline_plumbs_arguments():
    inputs = mock.MagicMock()
    inputs.schema_name = "website_overview"
    inputs.team_id = 7
    inputs.should_use_incremental_field = True
    inputs.db_incremental_field_last_value = "2026-04-01"
    manager = mock.MagicMock()

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_source"
    ) as mock_source:
        GoogleAnalyticsSource().source_for_pipeline(_config(), manager, inputs)

    mock_source.assert_called_once_with(
        config=mock.ANY,
        resource_name="website_overview",
        team_id=7,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-04-01",
    )


def test_source_for_pipeline_drops_last_value_when_not_incremental():
    inputs = mock.MagicMock()
    inputs.schema_name = "website_overview"
    inputs.team_id = 7
    inputs.should_use_incremental_field = False
    inputs.db_incremental_field_last_value = "2026-04-01"

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_source"
    ) as mock_source:
        GoogleAnalyticsSource().source_for_pipeline(_config(), mock.MagicMock(), inputs)

    assert mock_source.call_args[1]["db_incremental_field_last_value"] is None


@pytest.mark.parametrize("bad_property_id", ["not-a-number", "properties/abc", "12 34", ""])
def test_validate_credentials_rejects_non_numeric_property_id(bad_property_id):
    ok, message = GoogleAnalyticsSource().validate_credentials(_config(bad_property_id), team_id=1)

    assert ok is False
    assert "not a valid GA4 property ID" in (message or "")


@pytest.mark.parametrize(
    "wrong_id,expected_substring",
    [
        ("G-ABC123XYZ", "Measurement ID"),
        ("g-abc123xyz", "Measurement ID"),
        ("UA-12345678-1", "Universal Analytics"),
    ],
)
def test_validate_credentials_names_common_wrong_ids(wrong_id, expected_substring):
    ok, message = GoogleAnalyticsSource().validate_credentials(_config(wrong_id), team_id=1)

    assert ok is False
    assert expected_substring in (message or "")


def _http_error(status_code: int) -> requests.HTTPError:
    response = mock.MagicMock()
    response.status_code = status_code
    return requests.HTTPError(response=response)


@pytest.mark.parametrize(
    "status_code,expected_substring",
    [
        (401, "rejected the credentials"),
        (403, "rejected the credentials"),
        (404, "was not found"),
        (500, "Failed to read Google Analytics property metadata"),
    ],
)
def test_validate_credentials_maps_http_errors(status_code, expected_substring):
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.get_property_metadata",
            side_effect=_http_error(status_code),
        ),
    ):
        ok, message = GoogleAnalyticsSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert expected_substring in (message or "")


def test_validate_credentials_maps_token_refresh_error():
    # google-auth raises RefreshError with (message, response_dict); its default repr is the tuple,
    # which used to leak verbatim to users. Guard the mapping to a clean reconnect prompt.
    refresh_error = RefreshError("invalid_scope: Bad Request", {"error": "invalid_scope"})
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.get_property_metadata",
            side_effect=refresh_error,
        ),
    ):
        ok, message = GoogleAnalyticsSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "reconnect your Google" in (message or "")
    assert "invalid_scope" not in (message or "")


def test_validate_credentials_handles_session_failure():
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_session",
        side_effect=Exception("no integration"),
    ):
        ok, message = GoogleAnalyticsSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "Could not load Google Analytics credentials" in (message or "")


def test_validate_credentials_succeeds_when_metadata_readable():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.get_property_metadata",
            return_value={"dimensions": [], "metrics": []},
        ),
    ):
        ok, message = GoogleAnalyticsSource().validate_credentials(_config(), team_id=1)

    assert ok is True
    assert message is None


def test_non_retryable_errors_cover_auth_failures():
    errors = GoogleAnalyticsSource().get_non_retryable_errors()
    assert "401 Client Error" in errors
    assert "403 Client Error" in errors
    assert "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in errors
