import pytest
from unittest import mock

import requests
from google.auth.exceptions import RefreshError

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleanalytics import (
    GoogleAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.settings import (
    GOOGLE_ANALYTICS_REPORT_SCHEMAS,
    CustomReportError,
    parse_custom_reports,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source import (
    GoogleAnalyticsSource,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def _config(property_id: str = "123456789", custom_reports: str | None = None) -> GoogleAnalyticsSourceConfig:
    return GoogleAnalyticsSourceConfig(
        property_id=property_id, google_analytics_integration_id=1, custom_reports=custom_reports
    )


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


def test_get_schemas_includes_user_defined_custom_reports():
    # A configured custom report shows up alongside the built-ins, default-on (the user
    # explicitly asked for it) and incremental like every other report.
    custom = '[{"name": "paid_campaigns", "dimensions": ["sessionCampaignName"], "metrics": ["sessions"]}]'
    schemas = GoogleAnalyticsSource().get_schemas(_config(custom_reports=custom), team_id=1)

    by_name = {s.name: s for s in schemas}
    assert set(GOOGLE_ANALYTICS_REPORT_SCHEMAS.keys()) <= by_name.keys()
    assert "paid_campaigns" in by_name
    assert by_name["paid_campaigns"].should_sync_default is True
    assert by_name["paid_campaigns"].supports_incremental is True


def test_parse_custom_reports_prepends_date_and_derives_primary_key():
    # `date` always leads the dimensions (day-grained) and the primary key is date + all
    # dimensions, matching the built-in convention that incremental/merge sync relies on.
    reports = parse_custom_reports(
        '[{"name": "campaign_grain", "dimensions": ["date", "sessionCampaignName"], "metrics": ["sessions"]}]'
    )
    schema = reports["campaign_grain"]
    assert schema["dimensions"] == ["date", "sessionCampaignName"]
    assert schema["primary_key"] == ["date", "sessionCampaignName"]
    assert schema["metrics"] == ["sessions"]


def test_parse_custom_reports_empty_input_returns_no_reports():
    assert parse_custom_reports(None) == {}
    assert parse_custom_reports("   ") == {}


@pytest.mark.parametrize(
    "custom_reports,expected_substring",
    [
        ("not json", "valid JSON"),
        ('{"name": "x"}', "JSON array"),
        ('[{"dimensions": ["a"], "metrics": ["sessions"]}]', "non-empty 'name'"),
        ('[{"name": "website_overview", "dimensions": [], "metrics": ["sessions"]}]', "built-in report name"),
        (
            '[{"name": "dup", "metrics": ["sessions"]}, {"name": "dup", "metrics": ["sessions"]}]',
            "Duplicate custom report name",
        ),
        ('[{"name": "no_metrics", "dimensions": ["country"], "metrics": []}]', "at least one metric"),
        ('[{"name": "bad_dim", "dimensions": ["not a dim!"], "metrics": ["sessions"]}]', "not a valid GA4"),
        (
            '[{"name": "too_many_dims", "dimensions": ["a","b","c","d","e","f","g","h","i"], "metrics": ["s"]}]',
            "at most 9 dimensions",
        ),
        (
            '[{"name": "too_many_metrics", "dimensions": ["a"], '
            '"metrics": ["m1","m2","m3","m4","m5","m6","m7","m8","m9","m10","m11"]}]',
            "at most 10 metrics",
        ),
    ],
)
def test_parse_custom_reports_rejects_invalid(custom_reports, expected_substring):
    with pytest.raises(CustomReportError) as exc:
        parse_custom_reports(custom_reports)
    assert expected_substring in str(exc.value)


def test_validate_credentials_rejects_invalid_custom_reports():
    # A malformed custom-report config is surfaced at setup, before any GA4 call, so the
    # user fixes their JSON instead of hitting an opaque runReport failure mid-sync.
    ok, message = GoogleAnalyticsSource().validate_credentials(
        _config(custom_reports='[{"name": "x", "dimensions": ["country"], "metrics": []}]'), team_id=1
    )
    assert ok is False
    assert "at least one metric" in (message or "")


def test_all_schemas_have_date_dimension_and_in_primary_key():
    # Every report is day-grained: `date` must be requested and lead the primary key
    # so merge-mode dedupe and incremental syncs behave.
    for name, schema in GOOGLE_ANALYTICS_REPORT_SCHEMAS.items():
        assert schema["dimensions"][0] == "date", name
        assert schema["primary_key"] == schema["dimensions"], name


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


def test_validate_credentials_handles_missing_integration():
    # A deleted/disconnected OAuth row makes `google_analytics_session` raise the typed
    # `Integration.DoesNotExist`; surface a reconnect message instead of the raw ORM error.
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_session",
        side_effect=Integration.DoesNotExist(),
    ):
        ok, message = GoogleAnalyticsSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "no longer exists" in (message or "")
    assert "matching query" not in (message or "")


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


def test_non_retryable_errors_matches_revoked_refresh_token():
    # `_run_report` refreshes credentials via `session.post()` before any HTTP status is
    # available, so a revoked/expired refresh token surfaces as a bare `RefreshError` whose
    # `str()` is the raw (message, response_dict) tuple repr, e.g.:
    # ('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})
    observed_error = str(RefreshError("invalid_grant: Bad Request", {"error": "invalid_grant"}))
    non_retryable_errors = GoogleAnalyticsSource().get_non_retryable_errors()
    assert error_message_matches(observed_error, non_retryable_errors)


def test_retryable_errors_cover_exhausted_quota_retries():
    error_msg = "Data API quota for property '123456789' still exhausted after 5 retries (retryable)"
    patterns = GoogleAnalyticsSource().get_retryable_errors()
    assert any(pattern in error_msg for pattern in patterns)


def test_retryable_errors_cover_connection_reset():
    # `session.post()` in `_run_report` can raise this transport-level `requests.ConnectionError`
    # directly, outside its own retry loop (which only handles `RefreshError` and HTTP-level
    # failures) — must stay classified as retryable so it doesn't page as a bug.
    error_msg = "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"
    patterns = GoogleAnalyticsSource().get_retryable_errors()
    assert error_message_matches(error_msg, patterns)
