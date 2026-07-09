from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import gspread
import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets import (
    _PERMISSION_DENIED_MESSAGE,
    _REQUEST_TIMEOUT_SECONDS,
    _get_worksheet,
    _retry_on_transient_api_error,
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
            _get_worksheet("url", 1)

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
            _get_worksheet("transient-url", status_code)

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

        config = GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")

        with pytest.raises(gspread.exceptions.APIError):
            get_schemas(config)

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

        config = GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")

        with pytest.raises(gspread.exceptions.APIError):
            get_schemas(config)

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
            _get_worksheet("non-transient-url", 400)

        assert mock_get_worksheet_by_id.call_count == 1


def test_get_worksheet_caching():
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
    ):
        _get_worksheet("url", 1)
        _get_worksheet("url", 1)
        _get_worksheet("url", 1)

        # It should only have 1 call, the others should be returning the cached value
        assert mock_google_sheets_client.call_count == 1

        _get_worksheet("url", 2)
        _get_worksheet("url", 2)
        _get_worksheet("url", 2)

        # It should now have 2 calls, we've changed one of the arguments, but the second/third calls should be cached
        assert mock_google_sheets_client.call_count == 2


@pytest.mark.parametrize(
    "call_site",
    [
        pytest.param(
            lambda: get_schemas(
                GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")
            ),
            id="get_schemas",
        ),
        # Use a unique url/id to avoid the module-level TTLCache returning a prior result
        pytest.param(lambda: _get_worksheet("permission-error-url", 999), id="_get_worksheet"),
    ],
)
def test_reraises_permission_error_with_message(call_site):
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
    ) as mock_google_sheets_client:
        instance = mock_google_sheets_client.return_value
        instance.open_by_url.side_effect = PermissionError()

        with pytest.raises(PermissionError) as exc_info:
            call_site()

        assert "Spreadsheet access denied" in str(exc_info.value)


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
    config = GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")

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
        response = google_sheets_source(config, "sheet1", db_incremental_field_last_value=None)
        list(cast(Iterable[Any], response.items()))

    assert mock_worksheet.get_all_values.call_count == 2
    assert mock_worksheet.get_all_records.call_count == 2


def test_google_sheets_source_reads_blank_cells_as_null():
    config = GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")

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
        response = google_sheets_source(config, "sheet1", db_incremental_field_last_value=None)
        list(cast(Iterable[Any], response.items()))

    mock_worksheet.get_all_records.assert_called_once_with(default_blank=None)


def test_permission_error_is_non_retryable():
    """The message we re-raise from gspread's bare PermissionError must be a
    substring match for one of the source's non-retryable error keys, otherwise
    we'd retry a 403 forever."""
    source = GoogleSheetsSource()
    non_retryable_errors = source.get_non_retryable_errors()

    raised = PermissionError(_PERMISSION_DENIED_MESSAGE)
    error_msg = str(raised)

    assert any(key in error_msg for key in non_retryable_errors)


@pytest.mark.parametrize(
    "call_site",
    [
        pytest.param(
            lambda: get_schemas(
                GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")
            ),
            id="get_schemas",
        ),
        # Use a unique url/id to avoid the module-level TTLCache returning a prior result
        pytest.param(lambda: _get_worksheet("not-found-url", 998), id="_get_worksheet"),
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
    config = GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")

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
        assert get_schema_incremental_fields(config, "csm_followups") == []


def test_get_schema_incremental_fields_reraises_other_api_errors():
    """Only the deterministic 'Unable to parse range' 400 is swallowed. Transient 5xx errors are
    retried with backoff and, once retries are exhausted, must still propagate so Temporal can retry
    the activity rather than schema discovery silently reporting no incremental fields."""
    config = GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")

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
        get_schema_incremental_fields(config, "sheet1")

    assert mock_worksheet.get_all_values.call_count == 10


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
        client = google_sheets_client()

    assert client.http_client.timeout == _REQUEST_TIMEOUT_SECONDS
    assert client.http_client.timeout is not None


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
