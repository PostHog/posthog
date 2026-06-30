import time
import random
from collections.abc import Callable
from typing import Any, Optional, TypeVar

from django.conf import settings

import gspread
from cachetools import Cache, TTLCache, cached
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# (connect, read) timeout for every Sheets API request, in seconds. gspread defaults to no
# timeout, so a stalled connection blocks the worker thread indefinitely. Because the sync
# activities are threaded, a blocked thread can't be interrupted cleanly — Temporal eventually
# hits the activity's `start_to_close_timeout` and raises a `CancelledError` into the thread mid
# socket-read, which surfaces as a noisy "Cancelled" error. A bounded timeout turns a stall into a
# fast, retryable `requests.Timeout` instead. The read timeout is the max gap between received
# bytes (not total download time), so it stays safe for large sheets that stream in steadily.
_REQUEST_TIMEOUT_SECONDS: tuple[float, float] = (30.0, 120.0)


def google_sheets_client() -> gspread.Client:
    credentials = service_account.Credentials.from_service_account_info(
        {
            "private_key": settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY,
            "private_key_id": settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY_ID,
            "token_uri": settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_TOKEN_URI,
            "client_email": settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL,
        },
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )
    # gspread skips wrapping any session you pass in with `AuthorizedSession`, so a plain
    # `requests.Session` would send unauthenticated requests and Google returns 403. Build the
    # `AuthorizedSession` ourselves and mount the tracked adapter to keep request metering.
    session = AuthorizedSession(credentials)
    adapter = make_tracked_adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    client = gspread.authorize(credentials, session=session)
    client.set_timeout(_REQUEST_TIMEOUT_SECONDS)
    return client


cache: Cache[Any, Any] = TTLCache(maxsize=500, ttl=120)  # 120 seconds
max_attempts = 10
jitter_in_seconds = 10
sleep_per_attempt_in_seconds = 30

# Transient Google Sheets API failures worth retrying: 429 (per-minute quota exhausted) plus the
# 5xx server-side errors Google returns intermittently (e.g. "[500]: Internal error encountered.").
# Google's API guidance is to retry these with backoff — they are not caused by our request and
# usually clear on the next attempt, so re-raising immediately turns a blip into a failed sync.
_RETRYABLE_API_ERROR_CODES = {429, 500, 502, 503, 504}

# gspread raises a bare `PermissionError` (with no message) when the Google Sheets
# API returns 403 — see gspread/client.py: `raise PermissionError from ex`.
# `str(PermissionError())` is an empty string, which means the non-retryable error
# matcher (substring match over `str(e)`) has nothing to match on. Re-raise with a
# stable, descriptive message so downstream matching can identify it.
_PERMISSION_DENIED_MESSAGE = "Spreadsheet access denied. Please share the spreadsheet with the PostHog service account."

# gspread converts the Sheets API 404 into `SpreadsheetNotFound` — see gspread/client.py
# `open_by_key`: `raise SpreadsheetNotFound(ex.response) from ex`. Its `str()` is just the bare
# response repr (`<Response [404]>`); the "Requested entity was not found" text lives only on the
# chained APIError cause. The non-retryable matcher does a substring match over `str(e)`, so it has
# nothing to match on and a deleted/moved/unshared sheet gets retried indefinitely. Re-raise with a
# stable, descriptive message (mirroring `_PERMISSION_DENIED_MESSAGE` above) so it stops retrying.
_SPREADSHEET_NOT_FOUND_MESSAGE = (
    "Spreadsheet not found. The Google Sheet could not be found — it may have been deleted or "
    "moved, or is no longer shared with the PostHog service account."
)

T = TypeVar("T")


def _is_retryable_api_error(e: gspread.exceptions.APIError) -> bool:
    """Decide whether a gspread APIError is a transient error worth retrying.

    We deliberately key off the HTTP status on the response rather than `e.code`.
    gspread derives `e.code` from the JSON error body (`error.code`), which is not a
    reliable signal for transient failures: when Google (or a gateway/proxy in front of
    it) returns a 5xx/429 with a non-JSON body, gspread falls back to `code = -1`, and
    some error envelopes carry the code as a string. In those cases the underlying request
    is still a transient 5xx/429 that should be retried, but a `code`-based check misses it
    and fails the sync on the first attempt. `response.status_code` is always the real HTTP
    status, so prefer it and fall back to `e.code` only when it is unavailable."""

    status_code = getattr(getattr(e, "response", None), "status_code", None)
    if isinstance(status_code, int):
        return status_code in _RETRYABLE_API_ERROR_CODES

    try:
        return int(e.code) in _RETRYABLE_API_ERROR_CODES
    except (TypeError, ValueError):
        return False


def _retry_on_transient_api_error(execute: Callable[[], T]) -> T:
    """Run `execute` with linear backoff, retrying transient Google Sheets API
    errors. Google Sheets has a 300 request quota per minute, and also returns
    transient 5xx server errors (see `_RETRYABLE_API_ERROR_CODES`). We retry both
    and add a +- 10s jitter to the sleep per attempt so that multiple jobs blocked
    by quota limits dont all retry at the same time.

    This wraps every gspread call that hits the API — worksheet acquisition *and* the
    cell-reading calls (`get_all_values`/`get_all_records`). The reads issue their own
    requests, so a transient 5xx there must be retried too rather than failing the sync."""

    attempts = 1

    while True:
        try:
            return execute()
        except gspread.exceptions.APIError as e:
            if not _is_retryable_api_error(e) or attempts >= max_attempts:
                raise

            jitter = random.uniform(-jitter_in_seconds, jitter_in_seconds)
            sleep_with_jitter = sleep_per_attempt_in_seconds + jitter

            time.sleep(sleep_with_jitter * attempts)
            attempts = attempts + 1


@cached(cache)
def _get_worksheet(spreadsheet_url: str, worksheet_id: int) -> gspread.Worksheet:
    def execute() -> gspread.Worksheet:
        client = google_sheets_client()
        try:
            spreadsheet = client.open_by_url(spreadsheet_url)
        except PermissionError as e:
            raise PermissionError(_PERMISSION_DENIED_MESSAGE) from e
        except gspread.exceptions.SpreadsheetNotFound as e:
            raise gspread.exceptions.SpreadsheetNotFound(_SPREADSHEET_NOT_FOUND_MESSAGE) from e
        return spreadsheet.get_worksheet_by_id(worksheet_id)

    return _retry_on_transient_api_error(execute)


def get_schemas(config: GoogleSheetsSourceConfig) -> list[tuple[str, int]]:
    """Returns a tuple of worksheets in the form of (title, id)"""

    # `open_by_url` and `worksheets()` hit the Sheets API and so are subject to the same
    # transient quota (429) and 5xx server errors as `_get_worksheet` — retry them with backoff
    # rather than letting a transient blip fail the whole sync during schema discovery.
    def execute():
        client = google_sheets_client()
        try:
            spreadsheet = client.open_by_url(config.spreadsheet_url)
        except PermissionError as e:
            raise PermissionError(_PERMISSION_DENIED_MESSAGE) from e
        except gspread.exceptions.SpreadsheetNotFound as e:
            raise gspread.exceptions.SpreadsheetNotFound(_SPREADSHEET_NOT_FOUND_MESSAGE) from e
        return spreadsheet.worksheets()

    worksheets = _retry_on_transient_api_error(execute)

    return [(NamingConvention.normalize_identifier(worksheet.title), worksheet.id) for worksheet in worksheets]


def get_schema_incremental_fields(config: GoogleSheetsSourceConfig, worksheet_name: str) -> list[IncrementalField]:
    worksheets = get_schemas(config)
    selected_worksheet = [id for name, id in worksheets if name == worksheet_name]
    if len(selected_worksheet) == 0:
        raise Exception(f'Worksheet titled "{worksheet_name}" can\'t be found')

    worksheet_id = selected_worksheet[0]

    worksheet = _get_worksheet(config.spreadsheet_url, worksheet_id)

    try:
        rows = _retry_on_transient_api_error(lambda: worksheet.get_all_values("1:2"))  # Get the first two rows
    except gspread.exceptions.APIError as e:
        # Google rejects the unbounded "1:2" row range with a 400 "Unable to parse range" for
        # some worksheets (e.g. empty sheets, or sheets resized to have no columns). This is
        # deterministic, so retrying never helps. We're only probing the first rows to detect an
        # incremental "id" column here, so a worksheet we can't read simply has no detectable
        # incremental field — return [] rather than letting one odd sheet break schema discovery
        # for the entire spreadsheet. Other API errors (e.g. transient 5xx) still propagate so
        # they can be retried.
        if e.code == 400 and "Unable to parse range" in str(e):
            return []
        raise

    if len(rows) > 1 and "id" in rows[0]:
        index_of_id = rows[0].index("id")
        value_of_id_col = rows[1][index_of_id]
        if isinstance(value_of_id_col, int | float):
            return [
                {
                    "label": "id",
                    "field": "id",
                    "type": IncrementalFieldType.Numeric,
                    "field_type": IncrementalFieldType.Numeric,
                }
            ]

    return []


def google_sheets_source(
    config: GoogleSheetsSourceConfig,
    worksheet_name: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    worksheets = get_schemas(config)
    selected_worksheet = [id for name, id in worksheets if name == worksheet_name]
    if len(selected_worksheet) == 0:
        raise Exception(f'Worksheet titled "{worksheet_name}" can\'t be found')

    worksheet_id = selected_worksheet[0]

    worksheet = _get_worksheet(config.spreadsheet_url, worksheet_id)

    headers = _retry_on_transient_api_error(lambda: worksheet.get_all_values("1:1"))  # Get the first row
    primary_keys = None
    if len(headers) > 0 and "id" in headers[0]:
        primary_keys = ["id"]

    # Note: this source intentionally remains a SimpleSource rather than a ResumableSource.
    # gspread's get_all_records() performs a single Sheets API call that returns every row at
    # once, with no pagination cursor, continuation token, or range handle exposed to the
    # caller. The loop below yields exactly one batch, so there is no intermediate checkpoint
    # where some rows have been emitted and others are still pending — the two states are
    # "nothing yielded yet" and "fully done". A ResumableSource would have no cursor to
    # persist and would still have to re-download the entire sheet on restart, so it adds no
    # value. Converting this to a ResumableSource would require first introducing client-side
    # range-based batching (e.g. A2:Z1001, A1002:Z2001, ...), which is a behavior change to
    # the sync itself and is out of scope for restart-safety alone.
    def get_rows():
        worksheet = _get_worksheet(config.spreadsheet_url, worksheet_id)

        # default_blank defaults to "", which turns empty cells into strings and breaks numeric
        # columns that legitimately have gaps. None lets blank cells import as null instead.
        values = _retry_on_transient_api_error(lambda: worksheet.get_all_records(default_blank=None))

        if should_use_incremental_field and db_incremental_field_last_value is not None:
            values = [value for value in values if value.get("id", 0) > db_incremental_field_last_value]

        yield table_from_py_list(values)

    return SourceResponse(name=worksheet_name, items=get_rows, primary_keys=primary_keys)
