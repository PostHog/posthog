"""Checkout.com Reports API support.

Checkout.com exposes no list-all endpoint for bulk payment data; it ships as
generated report files (CSV) retrieved via the Reports API. Two kinds of table
come from here:

- ``reports``: one row per generated report (the ``GET /reports`` listing).
- ``{type}_report`` (e.g. ``financial_actions_report``): the parsed CSV rows of
  every report file of that type, discovered dynamically from the account's
  reports. Column sets vary per account because report templates are
  configurable, so rows keep the file's own (normalized) headers plus injected
  ``report_*`` / ``file_*`` metadata columns.
"""

import re
import csv
import codecs
import contextlib
from collections.abc import Iterable, Iterator
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests
import structlog
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com import (
    CheckoutComResumeConfig,
    _error_details,
    _format_timestamp,
    _hosts,
    _make_auth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# The reports listing defaults to (and caps at) 100 results per page.
REPORTS_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 120
# Report files can be large for high-volume merchants; give downloads more room.
REPORT_FILE_TIMEOUT_SECONDS = 600
# Yield parsed CSV rows in chunks rather than one list per file.
REPORT_CHUNK_SIZE = 5000
# Individual rows whose width the file's own header cannot explain (e.g. an unquoted
# embedded delimiter) are skipped with a warning, but only up to this share of a
# file's data rows. Past it the file's layout is not being parsed correctly, and
# silently under-loading financial data is worse than failing the sync.
MAX_SKIPPED_ROW_RATIO = 0.1
# Guard against a pagination loop (a next link that never advances) and bound how much
# a single listing walks. 1000 pages is ~100k reports, centuries of daily reports; a
# sync that hits it fails loudly rather than syncing a partial listing (see
# CheckoutComReportsListingError).
MAX_LIST_PAGES = 1000
# Schema discovery runs inline on API requests, so it reads fewer pages; report types
# repeat constantly, so the most recent pages carry every active type.
MAX_DISCOVERY_PAGES = 10

REPORTS_METADATA_ENDPOINT = "reports"
REPORT_TABLE_SUFFIX = "_report"

# Checkout.com regenerates the FinancialActions report over an overlapping date range every
# day, and every generated file carries its own `file_id`. Keyed on file position, an action
# that appears in ten daily files is retained ten times over. These report types carry a
# business key in their own columns, so they are keyed on that instead. Report types that do
# not overlap (settlement, balance breakdowns) keep the file-position key: their column sets
# are account-configurable and carry no key we can rely on.
BUSINESS_KEYED_REPORT_TABLES: dict[str, tuple[str, ...]] = {
    "financial_actions_report": ("action_id", "breakdown_type"),
    "financial_actions_by_payout_report": ("action_id", "breakdown_type"),
}
# The column a business key is meaningless without. `breakdown_type` only refines it, for the
# accounts whose template breaks an action into several rows, and the writer already drops key
# columns the data doesn't carry — so a missing `breakdown_type` degrades to keying on the
# action alone, which is correct for a template that emits one row per action.
BUSINESS_KEY_IDENTITY_COLUMN = "action_id"

logger: FilteringBoundLogger = structlog.get_logger(__name__)


class CheckoutComReportKeyError(Exception):
    """A report file lacks the columns its table is keyed on.

    Raised rather than falling back to another key: writing rows the merge cannot match
    would silently accumulate a duplicate per re-generated file, which is the failure this
    key exists to prevent.
    """


class CheckoutComReportsListingError(Exception):
    """The reports listing could not be walked to completion.

    Raised before any rows are yielded: yielding a partial listing would advance the
    incremental watermark past the reports that were never listed, permanently
    excluding them from later syncs.
    """


class CheckoutComReportParseError(Exception):
    """A listed report file's data rows could not be parsed.

    Raised rather than warning-and-continuing: a file that yields no rows (or drops
    more than MAX_SKIPPED_ROW_RATIO of them) under-loads the table while the sync
    still reports success, which silently loses recoverable financial history.
    """


def report_type_table_name(report_type: str) -> Optional[str]:
    """Stable table name for an API report type, e.g. ``FinancialActions`` -> ``financial_actions_report``.

    Schema names are persisted, and sync-time routing matches a stored name against the
    types the listing returns, so this mapping must stay deterministic. Returns ``None``
    when the type carries no usable characters.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", report_type or "")
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", spaced).strip("_").lower()
    if not cleaned:
        return None
    return f"{cleaned}{REPORT_TABLE_SUFFIX}"


def _normalize_header(header: str) -> str:
    """``Response Code`` becomes the stable column ``response_code``."""
    return re.sub(r"[^0-9a-zA-Z]+", "_", header).strip("_").lower()


def _make_api_session(client_secret: str) -> requests.Session:
    # allow_redirects=False so the bearer token never rides a redirect to another host;
    # the file download endpoint redirects to signed storage URLs, which are fetched
    # with a separate credential-free session (see _open_report_file). capture=False
    # because report bodies carry transaction identifiers, amounts and card metadata
    # the name-based scrubbers can't recognise.
    return make_tracked_session(redact_values=(client_secret,), allow_redirects=False, capture=False)


def _make_file_session(signed_url: str) -> requests.Session:
    # The signed URL's query string carries replayable download credentials (e.g.
    # X-Amz-Signature, X-Amz-Security-Token), and the shared URL scrubber doesn't know
    # the storage provider's parameter names, so every raw query component is redacted
    # by value. Raw (undecoded) segments are used so the literals match the logged URL.
    raw_query = urlparse(signed_url).query
    redact_values = tuple(
        {raw_query, *(segment.partition("=")[2] for segment in raw_query.split("&") if "=" in segment)} - {""}
    )
    return make_tracked_session(allow_redirects=True, capture=False, redact_values=redact_values)


def _next_pagination_token(payload: dict[str, Any]) -> Optional[str]:
    """Pull ``pagination_token`` out of ``_links.next``.

    Only the token is kept; the next page is rebuilt against our own host, so a
    tampered response can't point the authenticated request at another server.
    """
    links = payload.get("_links")
    if not isinstance(links, dict):
        return None
    next_link = links.get("next")
    if not isinstance(next_link, dict):
        return None
    href = next_link.get("href")
    if not isinstance(href, str) or not href:
        return None
    values = parse_qs(urlparse(href).query).get("pagination_token")
    return values[0] if values else None


def _list_reports(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    logger: FilteringBoundLogger,
    created_after: Optional[str] = None,
    max_pages: int = MAX_LIST_PAGES,
    raise_when_capped: bool = False,
) -> Iterator[dict[str, Any]]:
    params: dict[str, Any] = {"limit": REPORTS_PAGE_SIZE}
    if created_after is not None:
        # `created_after` is inclusive ("created on or after"), so boundary reports can
        # reappear; callers dedupe via primary keys or a completed-report checkpoint.
        params["created_after"] = created_after

    pagination_token: Optional[str] = None
    for _ in range(max_pages):
        page_params = dict(params)
        if pagination_token:
            page_params["pagination_token"] = pagination_token
        response = session.get(f"{api_base}/reports", params=page_params, auth=auth, timeout=REQUEST_TIMEOUT_SECONDS)
        if not response.ok:
            logger.error(
                f"Checkout.com API error: status={response.status_code}, "
                f"url={api_base}/reports, body={_error_details(response)}"
            )
            response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            return
        for report in data:
            if isinstance(report, dict):
                yield report
        next_token = _next_pagination_token(payload)
        if not next_token or next_token == pagination_token:
            return
        pagination_token = next_token
    if raise_when_capped:
        # Continuing with a partial listing would advance the watermark past the
        # unlisted reports and permanently skip them.
        raise CheckoutComReportsListingError(
            f"Checkout.com returned more than {max_pages} pages of reports; refusing to sync a partial listing"
        )
    logger.warning("Checkout.com reports listing hit the page cap; not all reports were listed", max_pages=max_pages)


def _collect_reports_ascending(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    logger: FilteringBoundLogger,
    created_after: Optional[str],
) -> list[dict[str, Any]]:
    """List reports and sort them oldest-first.

    The listing's order is not documented, and `sort_mode="asc"` promises the pipeline
    an ascending incremental watermark, so ordering is enforced here. Report objects are
    small (the file contents are fetched separately), so buffering the listing is cheap.
    """
    reports = list(
        _list_reports(
            session,
            auth,
            api_base,
            logger,
            created_after=created_after,
            max_pages=MAX_LIST_PAGES,
            raise_when_capped=True,
        )
    )
    reports.sort(key=lambda report: (str(report.get("created_on") or ""), str(report.get("id") or "")))
    return reports


def _strip_links(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_links(item) for key, item in value.items() if key != "_links"}
    if isinstance(value, list):
        return [_strip_links(item) for item in value]
    return value


@contextlib.contextmanager
def _open_report_file(
    api_session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    report_id: str,
    file_id: str,
) -> Iterator[requests.Response]:
    """Open a streaming response for one report file.

    ``GET /reports/{id}/files/{file_id}`` redirects to a signed storage URL. The
    redirect is followed manually with a credential-free session so the bearer token
    is only ever sent to the Checkout.com API host; the session is built per URL so
    its redaction set covers that URL's signing parameters (see _make_file_session).
    """
    response = api_session.get(
        f"{api_base}/reports/{report_id}/files/{file_id}",
        auth=auth,
        stream=True,
        timeout=REPORT_FILE_TIMEOUT_SECONDS,
    )
    try:
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if not location or not location.startswith("https://"):
                raise ValueError(f"Checkout.com file download for {file_id} redirected without an https location")
            download = _make_file_session(location).get(location, stream=True, timeout=REPORT_FILE_TIMEOUT_SECONDS)
        else:
            download = response
        try:
            if not download.ok:
                download.raise_for_status()
            yield download
        finally:
            if download is not response:
                download.close()
    finally:
        response.close()


def _parse_report_file_rows(
    lines: Iterable[str],
    metadata: dict[str, Any],
    logger: FilteringBoundLogger,
    required_column: str = "",
) -> Iterator[dict[str, Any]]:
    # `lines` is any iterator of physical CSV lines (a live response stream or a
    # StringIO), so a large report is parsed row-by-row without buffering the file.
    reader = csv.reader(lines)
    headers: Optional[list[str]] = None
    row_index = 0
    data_row_count = 0
    skipped_row_count = 0
    for row in reader:
        if headers is None:
            headers = [_normalize_header(header) for header in row]
            # A trailing delimiter on the header line reads as one unnamed final
            # column; drop unnamed trailing cells so the header width means "named
            # columns" when data-row widths are checked against it.
            while headers and not headers[-1]:
                headers.pop()
            if required_column and required_column not in headers:
                raise CheckoutComReportKeyError(
                    f"Checkout.com report file {metadata.get('file_id')} has no "
                    f"{required_column!r} column, so its rows cannot be deduplicated"
                )
            continue
        if not any(cell.strip() for cell in row):
            continue
        data_row_count += 1
        # The file's own header row describes its data rows, but some report
        # generators make the widths disagree without changing what a row means: a
        # trailing delimiter adds an empty overflow cell to every row, and ragged
        # writers omit trailing empty fields. Normalize both to the header's width;
        # treating these layout variants as malformed once dropped whole report files
        # to zero rows.
        if len(row) > len(headers) and not any(cell.strip() for cell in row[len(headers) :]):
            row = row[: len(headers)]
        elif len(row) < len(headers):
            row = [*row, *[""] * (len(headers) - len(row))]
        # Extra cells that carry values (e.g. an unquoted embedded delimiter) cannot
        # be assigned to columns without corrupting the data; skip the malformed line
        # visibly instead.
        if len(row) != len(headers):
            skipped_row_count += 1
            logger.warning(
                "Checkout.com report row length mismatch; skipping row",
                expected=len(headers),
                got=len(row),
                report_id=metadata.get("report_id"),
                file_id=metadata.get("file_id"),
            )
            continue
        parsed: dict[str, Any] = dict(zip(headers, row))
        # The injected metadata columns carry the dedupe key and incremental watermark,
        # so they always win over a same-named column in the CSV itself.
        parsed.update(metadata)
        parsed["file_row_index"] = row_index
        row_index += 1
        yield parsed
    if data_row_count == 0:
        # Header-only (or empty) files occur by design when a report covers a period
        # with no activity; raising on them would wedge the sync permanently.
        return
    if row_index == 0:
        raise CheckoutComReportParseError(
            f"Checkout.com report file {metadata.get('file_id')} has {data_row_count} "
            "data rows but none parsed; refusing to load a listed report file as empty"
        )
    if skipped_row_count / data_row_count > MAX_SKIPPED_ROW_RATIO:
        raise CheckoutComReportParseError(
            f"Checkout.com report file {metadata.get('file_id')} skipped {skipped_row_count} "
            f"of {data_row_count} data rows (threshold {MAX_SKIPPED_ROW_RATIO:.0%}); "
            "refusing to load a partially parsed report file"
        )


def _report_metadata_rows(reports: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    # `_links` hrefs carry pagination and signed-download URLs; they're transport
    # details, not data, so keep them out of the warehouse.
    rows = [_strip_links(report) for report in reports]
    if rows:
        yield rows


def _report_file_rows(
    reports: list[dict[str, Any]],
    api_session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CheckoutComResumeConfig],
    completed_report_id: Optional[str],
    required_column: str = "",
) -> Iterator[list[dict[str, Any]]]:
    for report in reports:
        report_id = str(report.get("id") or "")
        if not report_id or report_id == completed_report_id:
            continue
        created_on = str(report.get("created_on") or "")
        raw_account = report.get("account")
        account: dict[str, Any] = raw_account if isinstance(raw_account, dict) else {}
        chunk: list[dict[str, Any]] = []
        # Read order decides which copy of a restated row survives: the writer keeps the last
        # occurrence of a key per batch, and reports arrive oldest-first, so the newest report
        # wins. Sorting files by id makes the tie-break within one report deterministic too.
        files = sorted(
            (file for file in (report.get("files") or []) if isinstance(file, dict)),
            key=lambda file: str(file.get("id") or ""),
        )
        for file in files:
            file_id = str(file.get("id") or "")
            file_format = str(file.get("format") or "")
            if not file_id:
                continue
            if file_format.upper() != "CSV":
                logger.warning(
                    "Checkout.com report file is not CSV; skipping file",
                    report_id=report_id,
                    file_id=file_id,
                    format=file_format,
                )
                continue
            metadata = {
                "report_id": report_id,
                "report_created_on": created_on,
                "report_from": report.get("from"),
                "report_to": report.get("to"),
                "report_entity_id": account.get("entity_id"),
                "file_id": file_id,
            }
            with _open_report_file(api_session, auth, api_base, report_id, file_id) as download:
                # Decode compression on the fly and read physical lines off the socket so
                # quoted multi-line CSV fields survive (unlike `iter_lines`, which strips
                # the terminators csv needs).
                download.raw.decode_content = True
                lines = codecs.getreader("utf-8")(download.raw)
                for parsed in _parse_report_file_rows(lines, metadata, logger, required_column):
                    chunk.append(parsed)
                    if len(chunk) >= REPORT_CHUNK_SIZE:
                        yield chunk
                        chunk = []
        if chunk:
            yield chunk
        # Checkpoint after the report's files are fully yielded, so a crash re-yields the
        # in-progress report (merge dedupes on file_id + file_row_index) rather than
        # skipping it. `created_on` is stored verbatim because it goes straight back into
        # the API's own `created_after` filter on resume.
        resumable_source_manager.save_state(CheckoutComResumeConfig(report_created_on=created_on, report_id=report_id))


def discover_report_types(environment: str, client_id: str, client_secret: str) -> dict[str, str]:
    """Map table name -> report type for the report types visible to these credentials.

    Used by ``get_schemas``, which runs inline on API requests, so the listing is
    bounded to the most recent pages. Raises on any API failure; ``get_schemas``
    decides which failures degrade to the static schema catalog.
    """
    hosts = _hosts(environment)
    auth = _make_auth(environment, client_id, client_secret)
    session = _make_api_session(client_secret)
    discovered: dict[str, str] = {}
    for report in _list_reports(session, auth, hosts["api"], logger, max_pages=MAX_DISCOVERY_PAGES):
        report_type = str(report.get("type") or "")
        table_name = report_type_table_name(report_type)
        if table_name is not None and table_name != REPORTS_METADATA_ENDPOINT and table_name not in discovered:
            discovered[table_name] = report_type
    return discovered


def _get_rows(
    environment: str,
    client_id: str,
    client_secret: str,
    schema_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CheckoutComResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    hosts = _hosts(environment)
    auth = _make_auth(environment, client_id, client_secret)
    api_session = _make_api_session(client_secret)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    created_after: Optional[str] = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        created_after = _format_timestamp(db_incremental_field_last_value)
    completed_report_id: Optional[str] = None
    if resume is not None and resume.report_created_on:
        # The checkpoint is always at or past the incremental watermark, so it wins.
        created_after = resume.report_created_on
        completed_report_id = resume.report_id

    reports = _collect_reports_ascending(api_session, auth, hosts["api"], logger, created_after)

    if schema_name == REPORTS_METADATA_ENDPOINT:
        yield from _report_metadata_rows(reports)
        return

    matching = [report for report in reports if report_type_table_name(str(report.get("type") or "")) == schema_name]
    yield from _report_file_rows(
        matching,
        api_session,
        auth,
        hosts["api"],
        logger,
        resumable_source_manager,
        completed_report_id,
        BUSINESS_KEY_IDENTITY_COLUMN if schema_name in BUSINESS_KEYED_REPORT_TABLES else "",
    )


def checkout_com_reports_source(
    environment: str,
    client_id: str,
    client_secret: str,
    schema_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CheckoutComResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if schema_name != REPORTS_METADATA_ENDPOINT and not schema_name.endswith(REPORT_TABLE_SUFFIX):
        raise ValueError(f"Unknown Checkout.com schema: {schema_name}")

    partition_keys: Optional[list[str]]
    if schema_name == REPORTS_METADATA_ENDPOINT:
        primary_keys = ["id"]
        partition_keys = ["created_on"]
    elif schema_name in BUSINESS_KEYED_REPORT_TABLES:
        primary_keys = list(BUSINESS_KEYED_REPORT_TABLES[schema_name])
        # The merge matches on primary key *and* partition, so partitioning these tables on
        # report creation time would put a restatement in a different partition from the row
        # it restates and insert a second copy instead of updating it. They stay unpartitioned
        # so a key matches wherever it was first written.
        partition_keys = None
    else:
        # Report templates are account-configurable, so CSV columns carry no reliable
        # natural key; a file's contents are immutable once generated, so the position
        # within the file is a stable synthetic key.
        primary_keys = ["file_id", "file_row_index"]
        partition_keys = ["report_created_on"]

    return SourceResponse(
        name=schema_name,
        items=lambda: _get_rows(
            environment=environment,
            client_id=client_id,
            client_secret=client_secret,
            schema_name=schema_name,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=primary_keys,
        partition_count=1 if partition_keys else None,
        partition_size=1 if partition_keys else None,
        partition_mode="datetime" if partition_keys else None,
        partition_format="month" if partition_keys else None,
        partition_keys=partition_keys,
        # Reports are sorted oldest-first before yielding, so the watermark only moves forward.
        sort_mode="asc",
    )
