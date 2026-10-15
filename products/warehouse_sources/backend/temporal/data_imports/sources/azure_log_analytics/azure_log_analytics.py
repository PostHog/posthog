import re
import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
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
    ITEM_ID_FIELD,
    LOGIN_HOST,
    PAGE_SIZE,
    PRIMARY_KEYS,
    TABLE_NAME_RE,
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
# Five attempts with each wait capped at a minute keeps one request's throttle waits under the
# five-minute hold the source contract allows, whatever Retry-After asks for.
MAX_RETRY_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 60.0

_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# The cursor values are embedded in KQL, so they must keep the exact shape Log Analytics returns.
_DATETIME_LITERAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?Z$")
_ITEM_ID_LITERAL_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")
# TimeGenerated as KQL renders it (100 ns precision), so the cursor matches rows exactly. Dropped
# from every row before it is yielded.
CURSOR_COLUMN = "__posthog_cursor"


class AzureLogAnalyticsRetryableError(Exception):
    """Throttled (429) or a gateway failure (5xx) that outlived the retry budget."""

    pass


@frozen
class AzureLogAnalyticsResumeConfig:
    # The last row of the last page staged: its TimeGenerated exactly as returned (100 ns
    # precision, which a Python datetime cannot hold) and its _ItemId as the tie-breaker.
    time_generated: str
    item_id: str


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


def _backoff_seconds(response: requests.Response, attempt: int) -> float:
    raw = response.headers.get("Retry-After")
    if raw is not None:
        try:
            return min(max(float(raw), 0.0), MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt, MAX_BACKOFF_SECONDS)


class AzureLogAnalyticsClient:
    """Client-credentials client for the Log Analytics query API.

    Transport retries are off (`Retry(total=0)`): every query is a POST, which the default retry
    never covers, so throttling and gateway errors are retried once, here.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        workspace_id: str,
        logger: FilteringBoundLogger,
        safe_point: Callable[[], None] | None = None,
    ) -> None:
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
            timeout=REQUEST_TIMEOUT_SECONDS,
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

        while True:
            token = self._token or self.mint_token()
            response = self._api_session.post(
                url,
                json={"query": kql},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            # Tokens last about an hour; a long backfill can outlive one.
            if response.status_code == 401 and not reminted:
                reminted = True
                self._token = None
                continue

            if response.status_code == 429 or response.status_code >= 500:
                attempt += 1
                if attempt >= MAX_RETRY_ATTEMPTS:
                    raise AzureLogAnalyticsRetryableError(
                        f"Azure Log Analytics error (retryable): status={response.status_code}"
                    )
                delay = _backoff_seconds(response, attempt)
                self._logger.debug(
                    f"Azure Log Analytics throttled: status={response.status_code}, sleeping {delay}s (attempt {attempt})"
                )
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
        raise ValueError(f"Azure Log Analytics returned a partial result: {error.get('code')} {error.get('message')}")
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
    resume: AzureLogAnalyticsResumeConfig | None,
    watermark: Any,
    page_size: int,
) -> str:
    if not TABLE_NAME_RE.match(table):
        raise ValueError(f"{table!r} is not a valid Log Analytics table name.")
    # Re-assigning _ItemId makes it a visible column in the result.
    lines = [table, f"| extend {ITEM_ID_FIELD} = {ITEM_ID_FIELD}, {CURSOR_COLUMN} = tostring({TIMESTAMP_FIELD})"]
    if resume is not None:
        if not _DATETIME_LITERAL_RE.match(resume.time_generated) or not _ITEM_ID_LITERAL_RE.match(resume.item_id):
            raise ValueError("Azure Log Analytics resume cursor has an unexpected shape")
        moment = f"datetime({resume.time_generated})"
        lines.append(
            f"| where {TIMESTAMP_FIELD} > {moment} or "
            f"({TIMESTAMP_FIELD} == {moment} and strcmp({ITEM_ID_FIELD}, '{resume.item_id}') > 0)"
        )
    elif watermark is not None:
        lines.append(f"| where {TIMESTAMP_FIELD} >= datetime({_format_datetime_literal(watermark)})")
    # _ItemId breaks ties, so a page that ends inside one TimeGenerated value resumes without gaps.
    lines.append(f"| sort by {TIMESTAMP_FIELD} asc, {ITEM_ID_FIELD} asc")
    lines.append(f"| take {page_size}")
    return "\n".join(lines)


def get_rows(
    client: AzureLogAnalyticsClient,
    table: str,
    watermark: Any,
    resumable_source_manager: ResumableSourceManager[AzureLogAnalyticsResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        logger.debug(f"Azure Log Analytics: resuming {table} after {resume.time_generated}")

    while True:
        rows = client.query(build_query(table, resume, watermark, PAGE_SIZE))
        if not rows:
            return
        last = rows[-1]
        resume = AzureLogAnalyticsResumeConfig(
            time_generated=str(last.get(CURSOR_COLUMN)), item_id=str(last.get(ITEM_ID_FIELD))
        )
        for row in rows:
            row.pop(CURSOR_COLUMN, None)
        if len(rows) >= PAGE_SIZE:
            # Staged before the yield it covers: the pipeline commits it once this page is written.
            resumable_source_manager.save_state(resume)
        yield rows
        if len(rows) < PAGE_SIZE:
            return


def discover_tables(client: AzureLogAnalyticsClient) -> list[str]:
    rows = client.query(
        f"Usage | where TimeGenerated > ago({DISCOVERY_LOOKBACK_DAYS}d) | distinct DataType | sort by DataType asc"
    )
    return [str(row["DataType"]) for row in rows if TABLE_NAME_RE.match(str(row.get("DataType") or ""))]


def _probe_failure_message(error: Exception, table: str | None) -> str:
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 403:
        return "The app registration cannot query this workspace. Give its service principal the Log Analytics Reader role on the workspace, then try again."
    if status == 404:
        return "No Log Analytics workspace has this workspace ID. Copy the workspace ID from the workspace's Overview page."
    if status == 400 and table is not None and "Failed to resolve table" in str(error):
        return f"The workspace has no table named {table}. Check the table name, or remove it from the list."
    return f"Could not query the Log Analytics workspace: {error}"


def validate_credentials(
    tenant_id: str, client_id: str, client_secret: str, workspace_id: str, table: str | None = None
) -> tuple[bool, Optional[str]]:
    try:
        client = AzureLogAnalyticsClient(
            tenant_id, client_id, client_secret, workspace_id, structlog.get_logger(__name__)
        )
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
        client.query(f"{table} | take 0" if table else "print ok = 1")
    except Exception as error:
        return False, _probe_failure_message(error, table)

    return True, None


def azure_log_analytics_source(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    workspace_id: str,
    table: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AzureLogAnalyticsResumeConfig],
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    client = AzureLogAnalyticsClient(
        tenant_id, client_id, client_secret, workspace_id, logger, safe_point=resumable_source_manager.safe_point
    )

    return SourceResponse(
        name=table,
        items=lambda: get_rows(client, table, db_incremental_field_last_value, resumable_source_manager, logger),
        primary_keys=PRIMARY_KEYS,
        partition_count=1,
        partition_size=1,
        partition_keys=[TIMESTAMP_FIELD],
        partition_mode="datetime",
        partition_format="day",
        # Every page is one query sorted by TimeGenerated, then _ItemId.
        sort_mode="asc",
        on_complete=resumable_source_manager.clear_state,
    )
