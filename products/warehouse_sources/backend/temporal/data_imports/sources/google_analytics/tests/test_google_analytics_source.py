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


def _config(property_id: str = "123456789", custom_reports: str | None = None) -> GoogleAnalyticsSourceConfig:
    return GoogleAnalyticsSourceConfig(
        property_id=property_id, google_analytics_integration_id=1, custom_reports=custom_reports
    )


def test_get_schemas_filters_by_names():
    schemas = GoogleAnalyticsSource().get_schemas(_config(), team_id=1, names=["website_overview", "events"])
    assert {s.name for s in schemas} == {"website_overview", "events"}


@pytest.mark.parametrize(
    "custom_reports,expected_substring",
    [
        ("not json", "valid JSON"),
        ('{"name": "x"}', "JSON array"),
        ('[{"dimensions": ["a"], "metrics": ["sessions"]}]', "non-empty 'name'"),
        ('[{"name": "website_overview", "dimensions": [], "metrics": ["sessions"]}]', "already a built-in report"),
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


def test_parse_custom_reports_invalid_json_hides_parser_detail():
    # The raw JSONDecodeError text (e.g. "Expecting value: line 1 column 1 (char 0)") is debug
    # noise for the user pasting a report, so the message stays actionable without echoing any
    # of it back. Asserting the exact message (rather than just the absence of "column"/"char")
    # also catches other JSONDecodeError wording, like "Expecting value", being reintroduced.
    with pytest.raises(CustomReportError) as exc:
        parse_custom_reports("not json")
    message = str(exc.value)
    assert message == "Custom reports must be valid JSON. Provide a JSON array of report objects, then try again."
    assert "column" not in message
    assert "char" not in message
    assert "Expecting value" not in message


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


def _http_error(status_code: int, body: str = "") -> requests.HTTPError:
    response = mock.MagicMock()
    response.status_code = status_code
    response.text = body
    return requests.HTTPError(response=response)


@pytest.mark.parametrize(
    "status_code,body,expected_substring",
    [
        (401, "", "rejected the credentials"),
        (403, '{"error": {"status": "PERMISSION_DENIED"}}', "can't read this Google Analytics property"),
        (
            403,
            '{"error": {"details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]}}',
            "allow Google Analytics access",
        ),
        (404, "", "was not found"),
        (429, "", "couldn't reach Google Analytics"),
        (500, "", "couldn't reach Google Analytics"),
    ],
)
def test_validate_credentials_maps_http_errors(status_code, body, expected_substring):
    # None of these are bugs worth paging error tracking for: the mapped ones are user/upstream
    # errors with their own message, and 429/5xx are transient and self-resolving.
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.get_property_metadata",
            side_effect=_http_error(status_code, body),
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.capture_exception"
        ) as mock_capture,
    ):
        ok, message = GoogleAnalyticsSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert expected_substring in (message or "")
    mock_capture.assert_not_called()


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
    # The credential-load exception can carry an OAuth token or an HTML error body, so the
    # setup form gets a reconnect prompt and none of the raw text.
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_session",
        side_effect=Exception("token ya29.SECRET rejected"),
    ):
        ok, message = GoogleAnalyticsSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "Reconnect your Google account" in (message or "")
    assert "ya29.SECRET" not in (message or "")


def test_validate_credentials_hides_unexpected_metadata_failure_detail():
    # An unexpected metadata failure used to reach the setup form as `str(e)`, which for a
    # requests error is the full URL and response body.
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.google_analytics_session"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.source.get_property_metadata",
            side_effect=Exception("https://analyticsdata.googleapis.com/v1beta/properties/1?key=SECRET"),
        ),
    ):
        ok, message = GoogleAnalyticsSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "couldn't reach Google Analytics" in (message or "")
    assert "googleapis.com" not in (message or "")


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


def test_retryable_errors_cover_exhausted_quota_retries():
    error_msg = "Data API quota for property '123456789' still exhausted after 5 retries (retryable)"
    patterns = GoogleAnalyticsSource().get_retryable_errors()
    assert any(pattern in error_msg for pattern in patterns)


@pytest.mark.parametrize(
    "error_msg",
    [
        "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))",
        "HTTPSConnectionPool(host='analyticsdata.googleapis.com', port=443): Read timed out.",
        "HTTPSConnectionPool(host='analyticsdata.googleapis.com', port=443): Max retries exceeded with url: "
        "/v1beta/properties/123456789:runReport (Caused by NewConnectionError('<urllib3.connection.HTTPSConnection "
        "object at 0x7f00>: Failed to establish a new connection: [Errno -2] Name or service not known'))",
        "('Connection broken: IncompleteRead(5398 bytes read, 4842 more expected)', IncompleteRead(...))",
        "(\"Connection broken: InvalidChunkLength(got length b'', 0 bytes read)\", InvalidChunkLength(...))",
        "(\"Connection broken: ConnectionResetError(104, 'Connection reset by peer')\", ConnectionResetError(104))",
    ],
)
def test_retryable_errors_cover_connection_drops(error_msg):
    # `_run_report` backs off on these inline, so they reach the activity only once that budget is
    # spent. The next Temporal retry restarts from the last saved chunk, so they must stay
    # classified as retryable and not page as a bug. The third is the wrapper urllib3 puts around a
    # connect that never succeeded, once the shared adapter's own retries are exhausted, and the last
    # three are the truncated-body shapes `requests` raises as `ChunkedEncodingError`.
    patterns = GoogleAnalyticsSource().get_retryable_errors()
    assert error_message_matches(error_msg, patterns)
