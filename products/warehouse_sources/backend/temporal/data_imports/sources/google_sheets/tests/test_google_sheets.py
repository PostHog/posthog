from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from django.test import override_settings

import gspread
import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets import (
    _OAUTH_PERMISSION_DENIED_MESSAGE,
    _PERMISSION_DENIED_MESSAGE,
    _REQUEST_TIMEOUT_SECONDS,
    _get_worksheet,
    _retry_on_transient_api_error,
    _service_account_credentials,
    get_schema_incremental_fields,
    get_schemas,
    google_sheets_client,
    google_sheets_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.source import GoogleSheetsSource


def _api_error(
    status_code: int, message: str = "transient", status: str = "UNAVAILABLE"
) -> gspread.exceptions.APIError:
    mock_response = mock.MagicMock()
    mock_response.json.return_value = {"error": {"code": status_code, "message": message, "status": status}}
    return gspread.exceptions.APIError(mock_response)


def test_get_worksheet_backoff():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_spreadsheet = mock.MagicMock()
        mock_get_worksheet_by_id = mock.MagicMock()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "error": {
                "code": 429,
                "message": "Rate limit exceeded",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        mock_get_worksheet_by_id.side_effect = gspread.exceptions.APIError(mock_response)

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.return_value = mock_spreadsheet
        mock_spreadsheet.get_worksheet_by_id = mock_get_worksheet_by_id

        with pytest.raises(gspread.exceptions.APIError):
            _get_worksheet("url", 1, None, 1)

        assert mock_get_worksheet_by_id.call_count == 10


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_get_worksheet_retries_transient_api_errors(status_code):
    """Transient API errors (quota 429s and 5xx server errors like
    "[500]: Internal error encountered.") should be retried with backoff, not
    re-raised on the first occurrence."""
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_spreadsheet = mock.MagicMock()
        mock_get_worksheet_by_id = mock.MagicMock()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "error": {
                "code": status_code,
                "message": "Internal error encountered.",
                "status": "INTERNAL",
            }
        }

        mock_get_worksheet_by_id.side_effect = gspread.exceptions.APIError(mock_response)

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.return_value = mock_spreadsheet
        mock_spreadsheet.get_worksheet_by_id = mock_get_worksheet_by_id

        # Use a unique worksheet id per status code to avoid the module-level TTLCache
        with pytest.raises(gspread.exceptions.APIError):
            _get_worksheet("transient-url", status_code, None, 1)

        assert mock_get_worksheet_by_id.call_count == 10


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_get_schemas_retries_transient_api_errors(status_code):
    """Schema discovery (`open_by_url`/`worksheets`) hits the Sheets API just like
    `_get_worksheet`, so a transient quota 429 or 5xx server error (e.g.
    "[500]: Internal error encountered.") must be retried with backoff rather than
    failing the whole sync on the first occurrence."""
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "error": {"code": status_code, "message": "Internal error encountered.", "status": "INTERNAL"}
        }

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.side_effect = gspread.exceptions.APIError(mock_response)

        config = GoogleSheetsSourceConfig.from_dict({"spreadsheet_url": "https://docs.google.com/spreadsheets/d/fake"})

        with pytest.raises(gspread.exceptions.APIError):
            get_schemas(config, 1)

        assert instance.open_by_url.call_count == 10


def test_get_schemas_does_not_retry_non_transient_api_error():
    """A non-transient API error (e.g. 400) raised during schema discovery should be
    raised immediately without burning through the retry budget."""
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "error": {"code": 400, "message": "Bad request", "status": "INVALID_ARGUMENT"}
        }

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.side_effect = gspread.exceptions.APIError(mock_response)

        config = GoogleSheetsSourceConfig.from_dict({"spreadsheet_url": "https://docs.google.com/spreadsheets/d/fake"})

        with pytest.raises(gspread.exceptions.APIError):
            get_schemas(config, 1)

        assert instance.open_by_url.call_count == 1


def test_get_worksheet_does_not_retry_non_transient_api_error():
    """A non-transient API error (e.g. 400) should be raised immediately without
    burning through the retry budget."""
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_spreadsheet = mock.MagicMock()
        mock_get_worksheet_by_id = mock.MagicMock()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "error": {"code": 400, "message": "Bad request", "status": "INVALID_ARGUMENT"}
        }

        mock_get_worksheet_by_id.side_effect = gspread.exceptions.APIError(mock_response)

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.return_value = mock_spreadsheet
        mock_spreadsheet.get_worksheet_by_id = mock_get_worksheet_by_id

        with pytest.raises(gspread.exceptions.APIError):
            _get_worksheet("non-transient-url", 400, None, 1)

        assert mock_get_worksheet_by_id.call_count == 1


def test_get_worksheet_caching():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
    ):
        _get_worksheet("url", 1, None, 1)
        _get_worksheet("url", 1, None, 1)
        _get_worksheet("url", 1, None, 1)

        # It should only have 1 call, the others should be returning the cached value
        assert mock_google_sheets_client.call_count == 1

        _get_worksheet("url", 2, None, 1)
        _get_worksheet("url", 2, None, 1)
        _get_worksheet("url", 2, None, 1)

        # It should now have 2 calls, we've changed one of the arguments, but the second/third calls should be cached
        assert mock_google_sheets_client.call_count == 2


# The re-raised message must match the auth path: a service-account source gets the "share with the
# service account" message; an OAuth source (integration_id set) must NOT — sharing with the service
# account wouldn't help it. Unique url/id per case avoids the module-level TTLCache.
@pytest.mark.parametrize(
    "call_site,expected",
    [
        pytest.param(
            lambda: get_schemas(
                GoogleSheetsSourceConfig.from_dict({"spreadsheet_url": "https://docs.google.com/spreadsheets/d/fake"}),
                1,
            ),
            "Please share the spreadsheet with the PostHog service account",
            id="get_schemas_service_account",
        ),
        pytest.param(
            lambda: _get_worksheet("permission-error-url", 999, None, 1),
            "Please share the spreadsheet with the PostHog service account",
            id="_get_worksheet_service_account",
        ),
        pytest.param(
            lambda: _get_worksheet("permission-error-url-oauth", 998, 55, 2),
            "connected Google account can't access this spreadsheet",
            id="_get_worksheet_oauth",
        ),
    ],
)
def test_reraises_permission_error_with_message(call_site, expected):
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
    ) as mock_google_sheets_client:
        instance = mock_google_sheets_client.return_value
        instance.open_by_url.side_effect = PermissionError()

        with pytest.raises(PermissionError) as exc_info:
            call_site()

        assert expected in str(exc_info.value)


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_retry_on_transient_api_error_retries_then_exhausts(status_code):
    """The shared retry helper must retry transient API errors (quota 429s and 5xx
    server errors like "[503]: The service is currently unavailable.") with backoff."""
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"
    ):
        fn = mock.MagicMock(side_effect=_api_error(status_code))

        with pytest.raises(gspread.exceptions.APIError):
            _retry_on_transient_api_error(fn)

        assert fn.call_count == 10


def _api_error_with_status(
    status_code: int, body: dict[str, Any] | None, text: str = ""
) -> gspread.exceptions.APIError:
    """Build an APIError whose HTTP status and body can differ. When `body` is None the
    JSON body is unparseable, mirroring a transient 5xx returned by a gateway/proxy with a
    non-JSON payload — gspread then falls back to `code == -1`."""
    mock_response = mock.MagicMock()
    mock_response.status_code = status_code
    if body is None:
        mock_response.json.side_effect = ValueError("no json")
        mock_response.text = text
    else:
        mock_response.json.return_value = body
    return gspread.exceptions.APIError(mock_response)


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_retry_on_transient_api_error_retries_5xx_with_non_json_body(status_code):
    """A transient 5xx/429 can arrive with a non-JSON body (e.g. a gateway/proxy error
    page), in which case gspread sets `code` to -1. The retry decision must fall back to
    the HTTP status so the genuinely transient error is still retried rather than failing
    the sync on the first attempt."""
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"
    ):
        error = _api_error_with_status(status_code, body=None, text="upstream connect error")
        assert error.code == -1  # gspread couldn't parse a code out of the body
        fn = mock.MagicMock(side_effect=error)

        with pytest.raises(gspread.exceptions.APIError):
            _retry_on_transient_api_error(fn)

        assert fn.call_count == 10


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_retry_on_transient_api_error_retries_when_code_is_string(status_code):
    """Some error envelopes carry the code as a string, so `e.code` is e.g. "500" and a
    direct membership test against the integer set misses it. The retry decision must still
    recognise the transient status via the HTTP status code."""
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"
    ):
        body = {"error": {"code": str(status_code), "message": "Internal error encountered.", "status": "INTERNAL"}}
        error = _api_error_with_status(status_code, body=body)
        fn = mock.MagicMock(side_effect=error)

        with pytest.raises(gspread.exceptions.APIError):
            _retry_on_transient_api_error(fn)

        assert fn.call_count == 10


def test_retry_on_transient_api_error_does_not_retry_4xx_with_non_json_body():
    """A non-transient 4xx with an unparseable body must still be raised immediately — the
    HTTP-status fallback should only retry the transient codes, not everything."""
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"
    ):
        error = _api_error_with_status(400, body=None, text="Bad Request")
        fn = mock.MagicMock(side_effect=error)

        with pytest.raises(gspread.exceptions.APIError):
            _retry_on_transient_api_error(fn)

        assert fn.call_count == 1


def test_retry_on_transient_api_error_does_not_retry_non_transient():
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"
    ):
        fn = mock.MagicMock(side_effect=_api_error(400, status="INVALID_ARGUMENT"))

        with pytest.raises(gspread.exceptions.APIError):
            _retry_on_transient_api_error(fn)

        assert fn.call_count == 1


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("Connection aborted."),
        requests.exceptions.ReadTimeout("Read timed out. (read timeout=120.0)"),
        requests.exceptions.ConnectTimeout("Connection timed out."),
        # A connection reset mid-download surfaces as ChunkedEncodingError, which is a sibling of
        # ConnectionError in the requests hierarchy (not a subclass), so it must be caught explicitly.
        requests.exceptions.ChunkedEncodingError(
            "('Connection broken: ConnectionResetError(104, 'Connection reset by peer')', "
            "ConnectionResetError(104, 'Connection reset by peer'))"
        ),
    ],
)
def test_retry_on_transient_api_error_retries_network_error_then_succeeds(error):
    """A dropped connection or read timeout is raised by `requests` before gspread wraps it in an
    APIError, so the status-code path never sees it. It's a transient blip and must be retried
    inline rather than failing the read on the first occurrence."""
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"
    ):
        fn = mock.MagicMock(side_effect=[error, error, "ok"])

        assert _retry_on_transient_api_error(fn) == "ok"
        assert fn.call_count == 3


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("Connection aborted."),
        requests.exceptions.ReadTimeout("Read timed out. (read timeout=120.0)"),
        requests.exceptions.ChunkedEncodingError("Connection broken: ConnectionResetError(104, ...)"),
    ],
)
def test_retry_on_transient_api_error_bubbles_network_error_after_max_retries(error):
    """A persistent network error exhausts the inline budget and re-raises so it stays retryable
    at the activity level (Temporal), rather than being swallowed."""
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"
    ):
        fn = mock.MagicMock(side_effect=error)

        with pytest.raises(type(error)):
            _retry_on_transient_api_error(fn)

        assert fn.call_count == 10


def test_google_sheets_source_retries_transient_error_on_data_reads():
    """A transient 5xx on the cell-reading calls (`get_all_values`/`get_all_records`)
    must be retried, not surfaced on the first occurrence. These reads issue their own
    Sheets API requests separate from worksheet acquisition, so they need the same
    backoff — otherwise a "[503]: The service is currently unavailable." blip fails the
    sync."""
    config = GoogleSheetsSourceConfig.from_dict({"spreadsheet_url": "https://docs.google.com/spreadsheets/d/fake"})

    mock_worksheet = mock.MagicMock()
    # First header read hits a transient 503, then succeeds on retry.
    mock_worksheet.get_all_values.side_effect = [_api_error(503), [["id"]]]
    # The data read also hits a transient 503 once before returning rows.
    mock_worksheet.get_all_records.side_effect = [_api_error(503), [{"id": 1}]]

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.get_schemas",
            return_value=[("sheet1", 123)],
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets._get_worksheet",
            return_value=mock_worksheet,
        ),
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        response = google_sheets_source(config, 1, "sheet1", db_incremental_field_last_value=None)
        list(cast(Iterable[Any], response.items()))

    assert mock_worksheet.get_all_values.call_count == 2
    assert mock_worksheet.get_all_records.call_count == 2


def test_google_sheets_source_reads_blank_cells_as_null():
    config = GoogleSheetsSourceConfig.from_dict({"spreadsheet_url": "https://docs.google.com/spreadsheets/d/fake"})

    mock_worksheet = mock.MagicMock()
    mock_worksheet.get_all_values.return_value = [["id", "NumericColumnWithBlanks"]]
    mock_worksheet.get_all_records.return_value = [
        {"id": 1, "NumericColumnWithBlanks": 1.5},
        {"id": 2, "NumericColumnWithBlanks": None},
    ]

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.get_schemas",
            return_value=[("sheet1", 123)],
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets._get_worksheet",
            return_value=mock_worksheet,
        ),
    ):
        response = google_sheets_source(config, 1, "sheet1", db_incremental_field_last_value=None)
        list(cast(Iterable[Any], response.items()))

    mock_worksheet.get_all_records.assert_called_once_with(default_blank=None)


# Each permission-denied message must map to exactly one non-retryable key (otherwise a 403 retries
# forever), and the two must not collide — an OAuth failure must never surface the service-account
# advice, and vice versa.
@pytest.mark.parametrize(
    "raised_message,expected_advice,wrong_advice",
    [
        (_PERMISSION_DENIED_MESSAGE, "service account", "Reconnect the account"),
        (_OAUTH_PERMISSION_DENIED_MESSAGE, "Reconnect the account", "service account"),
    ],
)
def test_permission_denied_maps_to_auth_appropriate_message(raised_message, expected_advice, wrong_advice):
    non_retryable_errors = GoogleSheetsSource().get_non_retryable_errors()

    matched = [message for key, message in non_retryable_errors.items() if key in raised_message]

    assert len(matched) == 1
    message = matched[0]
    assert message is not None
    assert expected_advice in message
    assert wrong_advice not in message


@pytest.mark.parametrize(
    "error",
    [
        # gspread's bare 403 PermissionError, re-raised with a stable message.
        pytest.param(PermissionError(_PERMISSION_DENIED_MESSAGE), id="permission_denied"),
        # Values-read 404s stay a raw APIError (not SpreadsheetNotFound), so str() is
        # "APIError: [404]: Requested entity was not found." — a deleted/moved/unshared sheet hit mid-read.
        pytest.param(_api_error(404, "Requested entity was not found.", "NOT_FOUND"), id="entity_not_found_404"),
    ],
)
def test_error_string_matches_a_non_retryable_key(error):
    """The framework classifies non-retryable errors by substring-matching `str(exc)` against the
    source's keys. Each error the source surfaces for a permanent failure must match a key, otherwise
    a deterministic 403/404 gets retried forever."""
    non_retryable_errors = GoogleSheetsSource().get_non_retryable_errors()

    assert any(key in str(error) for key in non_retryable_errors)


@pytest.mark.parametrize(
    "call_site",
    [
        pytest.param(
            lambda: get_schemas(
                GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake"), 1
            ),
            id="get_schemas",
        ),
        # Use a unique url/id to avoid the module-level TTLCache returning a prior result
        pytest.param(lambda: _get_worksheet("not-found-url", 998, None, 1), id="_get_worksheet"),
    ],
)
def test_reraises_spreadsheet_not_found_with_non_retryable_message(call_site):
    """gspread converts the Sheets API 404 (deleted/moved/unshared sheet) into
    `SpreadsheetNotFound`, whose `str()` is only `<Response [404]>` — so the non-retryable matcher
    (substring over `str(e)`) never fires and a permanent failure is retried forever. We must
    re-raise it with a stable message that matches one of the source's non-retryable keys."""
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
    ) as mock_google_sheets_client:
        instance = mock_google_sheets_client.return_value
        instance.open_by_url.side_effect = gspread.exceptions.SpreadsheetNotFound(mock.MagicMock())

        with pytest.raises(gspread.exceptions.SpreadsheetNotFound) as exc_info:
            call_site()

    error_msg = str(exc_info.value)
    non_retryable_errors = GoogleSheetsSource().get_non_retryable_errors()
    assert any(key in error_msg for key in non_retryable_errors), (
        f"Re-raised SpreadsheetNotFound {error_msg!r} did not match any non-retryable pattern"
    )


def test_get_schema_incremental_fields_skips_unparseable_range():
    """Google rejects the unbounded "1:2" row range with a 400 'Unable to parse range' for some
    worksheets (e.g. empty sheets). That deterministic error must not break schema discovery — the
    worksheet should just report no incremental fields so the rest of the spreadsheet still syncs."""
    config = GoogleSheetsSourceConfig.from_dict({"spreadsheet_url": "https://docs.google.com/spreadsheets/d/fake"})

    mock_worksheet = mock.MagicMock()
    mock_worksheet.get_all_values.side_effect = _api_error(
        400, "Unable to parse range: 'csm_followups'!1:2", "INVALID_ARGUMENT"
    )

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.get_schemas",
            return_value=[("csm_followups", 123)],
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets._get_worksheet",
            return_value=mock_worksheet,
        ),
    ):
        assert get_schema_incremental_fields(config, 1, "csm_followups") == []


def test_get_schema_incremental_fields_reraises_other_api_errors():
    """Only the deterministic 'Unable to parse range' 400 is swallowed. Transient 5xx errors are
    retried with backoff and, once retries are exhausted, must still propagate so Temporal can retry
    the activity rather than schema discovery silently reporting no incremental fields."""
    config = GoogleSheetsSourceConfig.from_dict({"spreadsheet_url": "https://docs.google.com/spreadsheets/d/fake"})

    mock_worksheet = mock.MagicMock()
    mock_worksheet.get_all_values.side_effect = _api_error(500, "Internal error encountered.", "INTERNAL")

    with (
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.time"),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.get_schemas",
            return_value=[("sheet1", 123)],
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets._get_worksheet",
            return_value=mock_worksheet,
        ),
        pytest.raises(gspread.exceptions.APIError),
    ):
        get_schema_incremental_fields(config, 1, "sheet1")

    assert mock_worksheet.get_all_values.call_count == 10


# Missing service-account env vars must surface an actionable, non-retryable error — not the cryptic
# "None could not be converted to bytes" the crypto layer raises on a None private key.
@override_settings(GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY=None, GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL=None)
def test_service_account_not_configured_raises_actionable_non_retryable_error():
    with pytest.raises(ValueError) as exc_info:
        _service_account_credentials()

    message = str(exc_info.value)
    assert "not configured" in message
    assert "could not be converted to bytes" not in message
    non_retryable_errors = GoogleSheetsSource().get_non_retryable_errors()
    assert any(key in message for key in non_retryable_errors)


@override_settings(
    GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY="dummy", GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL="sa@example.com"
)
def test_google_sheets_client_sets_request_timeout():
    """Every gspread client must be built with a bounded (connect, read) timeout. gspread defaults
    to no timeout, so a stalled Sheets API read blocks the threaded sync activity until Temporal's
    start_to_close_timeout cancels the thread mid-read — which surfaces as a noisy CancelledError
    rather than a fast, retryable timeout."""
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.service_account"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.AuthorizedSession"
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.make_tracked_adapter"
        ),
    ):
        client = google_sheets_client(None, 1)

    assert client.http_client.timeout == _REQUEST_TIMEOUT_SECONDS
    assert client.http_client.timeout is not None


_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets"
_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.source"


# Cross-tenant guard: a cached worksheet carries the requesting team's OAuth session, so the cache
# must key on auth identity. Reverting the key to (url, worksheet_id) would let one team read through
# another team's credentials — the leak this auth split closes.
def test_get_worksheet_cache_keyed_by_auth_identity():
    with mock.patch(f"{_MODULE}.google_sheets_client") as mock_client:
        # Same URL + worksheet id, different (integration_id, team_id) → must not share a cache entry.
        _get_worksheet("auth-identity-url", 4242, None, 1)
        _get_worksheet("auth-identity-url", 4242, None, 1)  # cached: same identity
        _get_worksheet("auth-identity-url", 4242, 99, 2)  # different identity: rebuilds

        assert mock_client.call_count == 2
        mock_client.assert_any_call(None, 1)
        mock_client.assert_any_call(99, 2)


@override_settings(
    GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY="dummy", GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL="sa@example.com"
)
@pytest.mark.parametrize(
    "integration_id,team_id,expect_oauth",
    [
        (None, 1, False),  # legacy / service-account selection → shared service account
        (55, 3, True),  # OAuth → authenticate as the team's own connected Google account
    ],
)
# `integration_id` presence — not the stored `selection` — picks the auth path: legacy configs
# (which predate the selector and hydrate with no integration) stay on the service account; OAuth
# sources authenticate as their own Google identity, scoped by team_id.
def test_google_sheets_client_selects_auth_by_integration(integration_id, team_id, expect_oauth):
    with (
        mock.patch(f"{_MODULE}.service_account") as mock_service_account,
        mock.patch(f"{_MODULE}.OAuthCredentials") as mock_oauth_credentials,
        mock.patch(f"{_MODULE}.Integration") as mock_integration,
        mock.patch(f"{_MODULE}.close_old_connections"),
        mock.patch(f"{_MODULE}.AuthorizedSession"),
        mock.patch(f"{_MODULE}.make_tracked_adapter"),
    ):
        google_sheets_client(integration_id, team_id)

    if expect_oauth:
        # Tenant isolation boundary: the integration is fetched scoped by BOTH id and team_id.
        mock_integration.objects.get.assert_called_once_with(id=integration_id, team_id=team_id)
        assert mock_oauth_credentials.called
        assert not mock_service_account.Credentials.from_service_account_info.called
    else:
        assert mock_service_account.Credentials.from_service_account_info.called
        assert not mock_oauth_credentials.called
        assert not mock_integration.objects.get.called


# A missing connected account must yield a friendly validation failure, not an exception — else
# source create/update 500s instead of telling the user to reconnect.
def test_validate_credentials_missing_oauth_integration_fails_gracefully():
    config = GoogleSheetsSourceConfig.from_dict(
        {
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/fake",
            "auth_method": {"google_sheets_integration_id": 1},
        }
    )

    # OAuthMixin.get_oauth_integration raises ValueError when the integration is gone (flag is on here).
    with (
        mock.patch(f"{_SOURCE_MODULE}._oauth_enabled_for_team", return_value=True),
        mock.patch.object(
            GoogleSheetsSource, "get_oauth_integration", side_effect=ValueError("Integration not found: 1")
        ),
    ):
        ok, error = GoogleSheetsSource().validate_credentials(config, team_id=1)

    assert ok is False
    assert error is not None and "reconnect" in error.lower()


# Backend gate: an OAuth config must be rejected when the team isn't in the flag rollout. The frontend
# hides the option, but API/MCP callers bypass the UI, so the gate has to live in the backend too.
def test_validate_credentials_blocks_oauth_when_flag_off():
    config = GoogleSheetsSourceConfig.from_dict(
        {
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/fake",
            "auth_method": {"google_sheets_integration_id": 1},
        }
    )

    with mock.patch(f"{_SOURCE_MODULE}._oauth_enabled_for_team", return_value=False):
        ok, error = GoogleSheetsSource().validate_credentials(config, team_id=1)

    assert ok is False
    assert error is not None and "isn't available" in error


@pytest.mark.parametrize(
    "api_message,expected_fragment",
    [
        # The reported case: an uploaded .xlsx the Sheets API refuses to open.
        (
            "This operation is not supported for this document. The document must not be an Office file.",
            "Save as Google Sheets",
        ),
        # Any other 400 from the Sheets API falls back to a clean, actionable message.
        ("Some other bad request", "shared with our service account"),
    ],
)
def test_validate_credentials_maps_api_error_to_friendly_message(api_message, expected_fragment):
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.source.google_sheets_client"
    ) as mock_client:
        mock_client.return_value.open_by_url.side_effect = _api_error(
            400, message=api_message, status="INVALID_ARGUMENT"
        )
        config = GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")
        is_valid, error_message = GoogleSheetsSource().validate_credentials(config, team_id=1)

    assert is_valid is False
    assert expected_fragment in (error_message or "")
    # The raw gspread "APIError: [400]: ..." dump must not reach the user.
    assert "APIError" not in (error_message or "")
