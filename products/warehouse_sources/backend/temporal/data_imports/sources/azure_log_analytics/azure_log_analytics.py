import re
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import requests
import structlog
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics.settings import (
    API_HOST,
    DISCOVERY_LOOKBACK_DAYS,
    INGESTION_TIME_FIELD,
    ITEM_ID_FIELD,
    LOGIN_HOST,
    PAGE_SIZE,
    PRIMARY_KEYS,
    TABLE_NAME_RE,
    TIME_GENERATED_PRUNE,
    TIMESTAMP_FIELD,
    TOKEN_SCOPE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# A query runs for up to three minutes server-side before Log Analytics cancels it.
REQUEST_TIMEOUT_SECONDS = (30, 200)
MAX_RETRY_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 60.0
# One request with its retries and waits holds the worker for five minutes at most (the source
# contract), so a retry only starts when a full-length attempt still fits in the budget.
RETRY_BUDGET_SECONDS = 300.0
# A page that hits a result-size or execution limit is read again with half as many rows.
MIN_PAGE_SIZE = 100
# Permission probes run inside the source setup request, so they are short, never retried, and
# stop once the total passes this budget.
PROBE_REQUEST_TIMEOUT_SECONDS = (10, 30)
PROBE_BUDGET_SECONDS = 60.0
# Creation and the schema picker each probe inside the same 120 s setup request.
CREATION_PROBE_BUDGET_SECONDS = 30.0

_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# The cursor values are embedded in KQL, so they must keep the exact shape Log Analytics returns.
_DATETIME_LITERAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?Z$")
_ITEM_ID_LITERAL_RE = re.compile(r"^[A-Za-z0-9-]{0,128}$")
# The ingestion time as KQL renders it (100 ns precision), so the cursor matches rows exactly.
CURSOR_COLUMN = "__posthog_cursor"


class AzureLogAnalyticsRetryableError(Exception):
    """Throttled (429) or a gateway failure (5xx) that outlived the retry budget."""

    pass


class AzureLogAnalyticsPartialResultError(ValueError):
    """The query hit a service limit and returned only part of its rows."""

    pass


@frozen
class AzureLogAnalyticsResumeConfig:
    # Where the next page starts: after this ingestion time (exactly as KQL renders it, 100 ns
    # precision, which a Python datetime cannot hold) and this _ItemId. An empty item_id means
    # "at or after" the time, which starts a window or a watermark.
    ingested_at: str
    item_id: str = ""


@frozen
class WorkspaceCredentials:
    tenant_id: str
    client_id: str
    client_secret: str = field(repr=False)
    workspace_id: str

    def client(
        self,
        logger: FilteringBoundLogger,
        safe_point: Callable[[], None] | None = None,
        probe: bool = False,
    ) -> "AzureLogAnalyticsClient":
        return AzureLogAnalyticsClient(
            self.tenant_id,
            self.client_id,
            self.client_secret,
            self.workspace_id,
            logger,
            safe_point=safe_point,
            request_timeout=PROBE_REQUEST_TIMEOUT_SECONDS if probe else REQUEST_TIMEOUT_SECONDS,
            max_attempts=1 if probe else MAX_RETRY_ATTEMPTS,
        )


def validate_workspace_id(workspace_id: str) -> str:
    value = (workspace_id or "").strip()
    if not _GUID_RE.match(value):
        raise ValueError("Workspace ID must be the workspace GUID from the workspace's Overview page.")
    return value


def parse_table_names(raw: str | None) -> list[str]:
    """One table per line (commas also accepted), deduplicated in order."""
    names: list[str] = []
    for part in re.split(r"[\n,]", raw or ""):
        name = part.strip()
        if not name:
            continue
        if not TABLE_NAME_RE.match(name):
            raise ValueError(f"{name!r} is not a valid Log Analytics table name.")
        if name not in names:
            names.append(name)
    return names


def _error_description(response: requests.Response) -> str:
    # Log Analytics errors look like {"error": {"code": ..., "message": ..., "innererror": {...}}};
    # the inner error carries the KQL message that names the actual problem.
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, dict):
        messages = [str(error["message"])] if error.get("message") else []
        inner = error.get("innererror")
        while isinstance(inner, dict):
            if inner.get("message"):
                messages.append(str(inner["message"]))
            inner = inner.get("innererror")
        if messages:
            return " — " + " ".join(messages)
    if isinstance(body.get("error_description"), str):
        return f" — {body['error_description']}"
    return ""


def _backoff_seconds(response: requests.Response | None, attempt: int) -> float:
    raw = response.headers.get("Retry-After") if response is not None else None
    if raw is not None:
        try:
            return min(max(float(raw), 0.0), MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt, MAX_BACKOFF_SECONDS)


class AzureLogAnalyticsClient:
    """Client-credentials client for the Log Analytics query API.

    Transport retries are off (`Retry(total=0)`): every query is a POST, which the default retry
    never covers, so throttling and gateway errors are retried here, within `RETRY_BUDGET_SECONDS`.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        workspace_id: str,
        logger: FilteringBoundLogger,
        safe_point: Callable[[], None] | None = None,
        request_timeout: tuple[float, float] = REQUEST_TIMEOUT_SECONDS,
        max_attempts: int = MAX_RETRY_ATTEMPTS,
    ) -> None:
        self._request_timeout = request_timeout
        self._max_attempts = max_attempts
        self._tenant_id = tenant_id.strip()
        self._client_id = client_id.strip()
        self._client_secret = client_secret
        self._workspace_id = validate_workspace_id(workspace_id)
        self._logger = logger
        self._safe_point = safe_point
        self._token: Optional[str] = None
        redact = tuple(value for value in (client_secret,) if value)
        # The token exchange carries the secret and returns a bearer token; keep it out of samples.
        self._auth_session = make_tracked_session(retry=Retry(total=0), redact_values=redact, capture=False)
        self._api_session = make_tracked_session(retry=Retry(total=0), redact_values=redact)

    def mint_token(self) -> str:
        url = f"{LOGIN_HOST}/{quote(self._tenant_id, safe='')}/oauth2/v2.0/token"
        response = self._auth_session.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": TOKEN_SCOPE,
            },
            timeout=self._request_timeout,
        )
        if not response.ok:
            raise requests.HTTPError(
                f"{response.status_code} Client Error: {response.reason} for url: {LOGIN_HOST}{_error_description(response)}",
                response=response,
            )
        token = response.json().get("access_token")
        if not token:
            raise requests.HTTPError(f"Azure AD returned no access token for url: {LOGIN_HOST}", response=response)
        self._token = token
        return token

    def query(self, kql: str) -> list[dict[str, Any]]:
        url = f"{API_HOST}/v1/workspaces/{self._workspace_id}/query"
        attempt = 0
        reminted = False
        started = time.monotonic()

        while True:
            token = self._token or self.mint_token()
            response: requests.Response | None
            try:
                response = self._api_session.post(
                    url,
                    json={"query": kql},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=self._request_timeout,
                )
                status = str(response.status_code)
            except (requests.ConnectionError, requests.Timeout) as error:
                # Queries only read, so a dropped connection or a timeout is safe to send again.
                response = None
                status = type(error).__name__

            # Tokens last about an hour; a long backfill can outlive one.
            if response is not None and response.status_code == 401 and not reminted:
                reminted = True
                self._token = None
                continue

            if response is None or response.status_code == 429 or response.status_code >= 500:
                attempt += 1
                delay = _backoff_seconds(response, attempt)
                elapsed = time.monotonic() - started
                if attempt >= self._max_attempts or elapsed + delay + sum(self._request_timeout) > RETRY_BUDGET_SECONDS:
                    raise AzureLogAnalyticsRetryableError(f"Azure Log Analytics error (retryable): status={status}")
                self._logger.debug(f"Azure Log Analytics retry: status={status}, sleeping {delay}s (attempt {attempt})")
                interruptible_wait(delay, safe_point=self._safe_point)
                continue

            if not response.ok:
                raise requests.HTTPError(
                    f"{response.status_code} Client Error: {response.reason} for url: {API_HOST}{_error_description(response)}",
                    response=response,
                )

            return rows_from_response(response.json())


def rows_from_response(payload: Any) -> list[dict[str, Any]]:
    """Zip the primary result table's `columns` + `rows` into typed row dicts."""
    if not isinstance(payload, dict):
        return []
    # A query that hit a service limit returns 200 with the rows it managed and an `error`;
    # syncing those as if complete would lose the rest silently.
    if isinstance(payload.get("error"), dict):
        error = payload["error"]
        raise AzureLogAnalyticsPartialResultError(
            f"Azure Log Analytics returned a partial result: {error.get('code')} {error.get('message')}"
        )
    tables = payload.get("tables") or []
    if not tables:
        return []
    table = tables[0]
    columns = [(str(column.get("name")), str(column.get("type", ""))) for column in table.get("columns") or []]
    return [
        {name: _convert(value, column_type) for (name, column_type), value in zip(columns, values)}
        for values in table.get("rows") or []
    ]


def _convert(value: Any, column_type: str) -> Any:
    if value is None:
        return None
    if column_type == "datetime" and isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if column_type == "dynamic" and isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    if column_type == "bool" and isinstance(value, int | str):
        return str(value).lower() in ("1", "true")
    return value


def _format_datetime_literal(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if _DATETIME_LITERAL_RE.match(text):
            return text
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    raise ValueError(f"Azure Log Analytics incremental value is not a datetime: {value!r}")


def build_query(
    table: str,
    after: AzureLogAnalyticsResumeConfig,
    before: str,
    page_size: int,
) -> str:
    if not TABLE_NAME_RE.match(table):
        raise ValueError(f"{table!r} is not a valid Log Analytics table name.")
    for literal in (after.ingested_at, before):
        if not _DATETIME_LITERAL_RE.match(literal):
            raise ValueError("Azure Log Analytics cursor has an unexpected shape")
    if not _ITEM_ID_LITERAL_RE.match(after.item_id):
        raise ValueError("Azure Log Analytics cursor has an unexpected shape")

    moment = f"datetime({after.ingested_at})"
    lines = [table, f"| where {TIMESTAMP_FIELD} >= {moment} - {TIME_GENERATED_PRUNE}"]
    if after.item_id:
        lines.append(
            f"| where ingestion_time() > {moment} or "
            f"(ingestion_time() == {moment} and strcmp({ITEM_ID_FIELD}, '{after.item_id}') > 0)"
        )
    else:
        lines.append(f"| where ingestion_time() >= {moment}")
    lines.append(f"| where ingestion_time() < datetime({before})")
    # ingestion_time() only resolves against the table, so it is captured before the sort.
    lines.append(f"| extend {INGESTION_TIME_FIELD} = ingestion_time()")
    # _ItemId breaks ties, so a page that ends inside one ingestion time resumes without gaps.
    lines.append(f"| sort by {INGESTION_TIME_FIELD} asc, {ITEM_ID_FIELD} asc")
    lines.append(f"| take {page_size}")
    # Re-assigning _ItemId makes it a visible column in the result.
    lines.append(f"| extend {ITEM_ID_FIELD} = {ITEM_ID_FIELD}, {CURSOR_COLUMN} = tostring({INGESTION_TIME_FIELD})")
    return "\n".join(lines)


def window_end(after: AzureLogAnalyticsResumeConfig, run_start: datetime, hourly: bool) -> str:
    """The end of the day or hour the cursor sits in, capped at the run start.

    Each page sorts only the rows left in its window, so a backfill never re-scans the whole table
    for every page. A busy table walks hours instead of days. The cap leaves rows ingested during
    the run to the next run.
    """
    moment = datetime.fromisoformat(after.ingested_at[:19]).replace(tzinfo=UTC)
    if hourly:
        end = moment.replace(minute=0, second=0) + timedelta(hours=1)
    else:
        end = moment.replace(hour=0, minute=0, second=0) + timedelta(days=1)
    if end >= run_start:
        return _format_datetime_literal(run_start)
    return end.strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_cursor(client: AzureLogAnalyticsClient, table: str, watermark: Any) -> AzureLogAnalyticsResumeConfig | None:
    if watermark is not None:
        return AzureLogAnalyticsResumeConfig(ingested_at=_format_datetime_literal(watermark))
    rows = client.query(f"{table} | summarize start = min(ingestion_time()) | project start = tostring(start)")
    start = str(rows[0].get("start") or "") if rows else ""
    return AzureLogAnalyticsResumeConfig(ingested_at=start) if start else None


def get_rows(
    client: AzureLogAnalyticsClient,
    table: str,
    watermark: Any,
    resumable_source_manager: ResumableSourceManager[AzureLogAnalyticsResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        logger.debug(f"Azure Log Analytics: resuming {table} after {resume.ingested_at}")
    after = resume or _first_cursor(client, table, watermark)
    if after is None:
        return

    run_start = datetime.now(UTC)
    run_end = _format_datetime_literal(run_start)
    page_size = PAGE_SIZE
    hourly = False
    while True:
        before = window_end(after, run_start, hourly)
        try:
            rows = client.query(build_query(table, after, before, page_size))
        except AzureLogAnalyticsPartialResultError:
            if page_size <= MIN_PAGE_SIZE:
                raise
            hourly = True
            page_size = max(MIN_PAGE_SIZE, page_size // 2)
            logger.debug(f"Azure Log Analytics: {table} page hit a service limit, retrying with {page_size} rows")
            # The staged cursor covers every yielded row, so the run can hand over between retries.
            resumable_source_manager.safe_point()
            continue

        window_done = len(rows) < page_size
        if not window_done:
            hourly = True
            last = rows[-1]
            after = AzureLogAnalyticsResumeConfig(
                ingested_at=str(last.get(CURSOR_COLUMN)), item_id=str(last.get(ITEM_ID_FIELD))
            )
        else:
            page_size = PAGE_SIZE
            hourly = hourly and not before.endswith("T00:00:00Z")
            after = AzureLogAnalyticsResumeConfig(ingested_at=before)
        for row in rows:
            row.pop(CURSOR_COLUMN, None)

        # Staged before the yield it covers, the final page included: the pipeline commits it once
        # the page is written.
        resumable_source_manager.save_state(after)
        if rows:
            yield rows
        else:
            # A window with no rows yields nothing; the pipeline only sees a shutdown at an item or here.
            resumable_source_manager.safe_point()
        if window_done and before == run_end:
            return


def discover_tables(client: AzureLogAnalyticsClient) -> list[str]:
    rows = client.query(
        f"Usage | where TimeGenerated > ago({DISCOVERY_LOOKBACK_DAYS}d) | distinct DataType | sort by DataType asc"
    )
    return [str(row["DataType"]) for row in rows if TABLE_NAME_RE.match(str(row.get("DataType") or ""))]


def _is_missing_table(error: requests.HTTPError) -> bool:
    return getattr(error.response, "status_code", None) == 400 and "Failed to resolve table" in str(error)


def probe_tables(
    credentials: WorkspaceCredentials,
    tables: list[str],
    missing_table_reason: str,
    stop_at_first_readable: bool = False,
    budget_seconds: float = PROBE_BUDGET_SECONDS,
) -> dict[str, str | None]:
    """Why the query API cannot read each table, or None when it can.

    Basic and Auxiliary plan tables are only readable through the search API, so the query API
    rejects them with a 400, and table-level access control answers 403. A throttle or an outage
    is not a reason: the table counts as readable, and probing stops so setup stays fast.
    """
    reasons: dict[str, str | None] = dict.fromkeys(tables)
    client = credentials.client(structlog.get_logger(__name__), probe=True)
    try:
        client.mint_token()
    except (requests.RequestException, ValueError):
        return reasons
    started = time.monotonic()
    for table in tables:
        if time.monotonic() - started > budget_seconds:
            break
        try:
            client.query(f"{table} | take 0")
            if stop_at_first_readable:
                break
        except requests.HTTPError as error:
            status = getattr(error.response, "status_code", None)
            if _is_missing_table(error):
                reasons[table] = missing_table_reason
            elif status == 400:
                reasons[table] = (
                    "Log Analytics can't query this table. Basic and Auxiliary plan tables aren't supported."
                    f"{_error_description(error.response)}"
                )
            elif status == 403:
                reasons[table] = "The app can't read this table. Give it access to the table, or leave the table out."
            else:
                break
        except (AzureLogAnalyticsRetryableError, requests.RequestException):
            break
    return reasons


def _probe_failure_message(error: Exception, missing_table_message: str) -> str:
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 403:
        return (
            "The app registration cannot query this workspace. Give its service principal the Log Analytics "
            "Reader role on the workspace, or read access to the table, then try again."
        )
    if status == 404:
        return "No Log Analytics workspace has this workspace ID. Copy the workspace ID from the workspace's Overview page."
    if isinstance(error, requests.HTTPError) and _is_missing_table(error):
        return missing_table_message
    return f"Could not query the Log Analytics workspace: {error}"


def validate_workspace(
    credentials: WorkspaceCredentials, probe_query: str, missing_table_message: str
) -> tuple[bool, Optional[str]]:
    """Mint a token, then run `probe_query`, which proves the app can query the workspace.

    This runs inside the source setup request, so it uses the short probe deadlines.
    """
    try:
        client = credentials.client(structlog.get_logger(__name__), probe=True)
    except ValueError as error:
        return False, str(error)

    try:
        client.mint_token()
    except Exception:
        return (
            False,
            "Could not authenticate with Microsoft Entra ID. Check the tenant ID, client ID and client secret.",
        )

    try:
        client.query(probe_query)
    except Exception as error:
        return False, _probe_failure_message(error, missing_table_message)

    return True, None


def azure_log_analytics_source(
    credentials: WorkspaceCredentials,
    table: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AzureLogAnalyticsResumeConfig],
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    client = credentials.client(logger, safe_point=resumable_source_manager.safe_point)

    return SourceResponse(
        name=table,
        items=lambda: get_rows(client, table, db_incremental_field_last_value, resumable_source_manager, logger),
        primary_keys=PRIMARY_KEYS,
        partition_count=1,
        partition_size=1,
        partition_keys=[TIMESTAMP_FIELD],
        partition_mode="datetime",
        partition_format="day",
        # Every page is one query sorted by ingestion time, then _ItemId.
        sort_mode="asc",
        on_complete=resumable_source_manager.clear_state,
    )
