import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
import structlog
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.settings import (
    AZURE_COST_MANAGEMENT_ENDPOINTS,
    AzureCostManagementEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

LOGIN_HOST = "https://login.microsoftonline.com"
MANAGEMENT_HOST = "https://management.azure.com"
# Client-credentials token audience for Azure Resource Manager, which fronts Cost Management.
MANAGEMENT_TOKEN_SCOPE = "https://management.azure.com/.default"

REQUEST_TIMEOUT_SECONDS = 180
MAX_RETRY_ATTEMPTS = 6
MAX_BACKOFF_SECONDS = 120.0
# The Query API caps a single request's date range at one year, so longer backfills are walked as
# consecutive one-year windows.
MAX_WINDOW_DAYS = 365
# How far back a first sync reaches when no start date is configured.
DEFAULT_HISTORY_DAYS = 365
# Azure forecasts at most a rolling year ahead; a month is the useful horizon for daily granularity.
FORECAST_HORIZON_DAYS = 30

# Cost Management throttles per scope (roughly a handful of query calls a minute) and returns the
# wait in its own headers rather than only in `Retry-After`.
RETRY_AFTER_HEADERS = (
    "Retry-After",
    "x-ms-ratelimit-microsoft.consumption-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-clienttype-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after",
)
# Sent so Azure buckets our throttling separately from other clients on the same subscription.
COMMAND_NAME = "PostHogDataWarehouse"


class AzureCostManagementRetryableError(Exception):
    """Transient upstream failure (throttle or 5xx) worth retrying."""

    pass


@frozen
class AzureCostManagementResumeConfig:
    # ISO date of the window the sync was on when state was saved. Windows are recomputed
    # deterministically, so replaying from this date skips every window already walked.
    window_start: str | None = None
    # Azure's `properties.nextLink` for the page to fetch next within that window. None means
    # "start the window from its first page".
    next_link: str | None = None


def _snake_case(name: str) -> str:
    """`ServiceName` -> `service_name`, `ResourceId` -> `resource_id`, `CostUSD` -> `cost_usd`."""
    with_boundaries = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", with_boundaries).lower()


def normalize_scope(scope: str) -> str:
    """Trim a user-entered ARM scope to the bare path segment used to build request URLs.

    The scope is user-supplied and becomes part of the request URL, so a value carrying its own
    host (or scheme) is rejected rather than silently repointing our credentialed requests.
    """
    raw = (scope or "").strip()
    # The scope is interpolated into the request URL, so reject anything that could break out of
    # the path: a scheme/host (`://` or a protocol-relative `//`), or a delimiter (`?`, `#`, `\`)
    # that would push the appended Cost Management path into the query string or fragment and
    # repoint the credentialed request at an arbitrary ARM operation.
    if "://" in raw or raw.startswith("//") or any(char in raw for char in ("?", "#", "\\")):
        raise ValueError("Azure Cost Management scope must be an ARM path, not a URL")

    trimmed = raw.strip("/")
    if not trimmed:
        raise ValueError("Azure Cost Management scope is required")
    return trimmed


def _endpoint_url(scope: str, operation: str, api_version: str) -> str:
    query = urlencode({"api-version": api_version})
    return f"{MANAGEMENT_HOST}/{scope}/providers/Microsoft.CostManagement/{operation}?{query}"


def _validated_next_link(next_link: str) -> str:
    """Only follow a continuation URL that stays on Azure Resource Manager."""
    if not next_link.startswith(f"{MANAGEMENT_HOST}/"):
        raise ValueError("Azure Cost Management returned a nextLink outside management.azure.com")
    return next_link


def _error_description(response: requests.Response) -> str:
    # Azure Resource Manager errors look like {"error": {"code": ..., "message": ...}}.
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        return f" — {error['message']}"
    if isinstance(body.get("error_description"), str):
        return f" — {body['error_description']}"
    return ""


def _retry_after_seconds(response: requests.Response) -> Optional[float]:
    for header in RETRY_AFTER_HEADERS:
        raw = response.headers.get(header)
        if raw is None:
            continue
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            continue
        if seconds >= 0:
            return min(seconds, MAX_BACKOFF_SECONDS)
    return None


def _backoff_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = _retry_after_seconds(response)
    if retry_after is not None:
        return retry_after
    return min(2.0**attempt, MAX_BACKOFF_SECONDS)


def _parse_usage_date(value: Any) -> Any:
    """Normalize Azure's `UsageDate` (an int like 20240115, or an ISO timestamp) to `YYYY-MM-DD`."""
    if value is None:
        return None
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return value

    if len(text) == 8 and text.isdigit():
        try:
            return date(int(text[0:4]), int(text[4:6]), int(text[6:8])).isoformat()
        except ValueError:
            return text
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text


def rows_from_query_result(payload: Any, scope: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Zip the query API's `columns` + `rows` matrix into row dicts, plus the continuation link."""
    properties = payload.get("properties") if isinstance(payload, dict) else None
    if not isinstance(properties, dict):
        return [], None

    columns = [_snake_case(str(column.get("name", ""))) for column in properties.get("columns") or []]
    rows: list[dict[str, Any]] = []
    for values in properties.get("rows") or []:
        row: dict[str, Any] = dict(zip(columns, values))
        if "usage_date" in row:
            row["usage_date"] = _parse_usage_date(row["usage_date"])
        row["scope"] = scope
        rows.append(row)

    next_link = properties.get("nextLink")
    return rows, next_link if isinstance(next_link, str) and next_link else None


def rows_from_dimensions(payload: Any, scope: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    rows: list[dict[str, Any]] = []
    for item in payload.get("value") or []:
        properties = item.get("properties") or {}
        rows.append(
            {
                "scope": scope,
                "id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "category": properties.get("category"),
                "description": properties.get("description"),
                "filter_enabled": properties.get("filterEnabled"),
                "grouping_enabled": properties.get("groupingEnabled"),
                "usage_start": properties.get("usageStart"),
                "usage_end": properties.get("usageEnd"),
                "total": properties.get("total"),
                "data": properties.get("data"),
            }
        )
    return rows


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def resolve_window_start(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    configured_start_date: str | None,
    today: date,
) -> date:
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            # Re-pull the watermark day itself; Azure restates the tail of the window and merge
            # dedupes the overlap on the composite key.
            return min(watermark, today)

    configured = _to_date(configured_start_date)
    if configured is not None:
        return min(configured, today)

    return today - timedelta(days=DEFAULT_HISTORY_DAYS)


def build_windows(start: date, end: date, max_days: int = MAX_WINDOW_DAYS) -> list[SyncWindow[date]]:
    """Split an inclusive date range into consecutive windows the query API will accept."""
    if start > end:
        return []

    windows: list[SyncWindow[date]] = []
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=max_days - 1), end)
        windows.append(SyncWindow(start=window_start, end=window_end))
        window_start = window_end + timedelta(days=1)
    return windows


def build_query_body(config: AzureCostManagementEndpointConfig, window_start: date, window_end: date) -> dict[str, Any]:
    dataset: dict[str, Any] = {
        "granularity": "Daily",
        "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
    }
    if config.grouping:
        dataset["grouping"] = [{"type": "Dimension", "name": dimension} for dimension in config.grouping]

    body: dict[str, Any] = {
        "type": config.export_type,
        "timeframe": "Custom",
        "timePeriod": {
            "from": f"{window_start.isoformat()}T00:00:00+00:00",
            "to": f"{window_end.isoformat()}T23:59:59+00:00",
        },
        "dataset": dataset,
    }

    if config.kind == "forecast":
        # Only the projection is wanted here — actual spend already lands in the cost tables.
        body["includeActualCost"] = False
        body["includeFreshPartialCost"] = False
    else:
        # Ascending usage date so rows arrive in watermark order across every page.
        dataset["sorting"] = [{"direction": "Ascending", "name": "UsageDate"}]

    return body


class AzureCostManagementClient:
    """Minted-token ARM client for the Cost Management POST query API.

    The tracked session's retries are disabled (`Retry(total=0)`) because they never cover this
    source: the query API is a POST (excluded from the default retry's allowed methods) and Azure
    reports its throttle wait in vendor headers the transport can't read. Backoff is therefore
    handled once, here, rather than layered on top of the transport's.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        logger: FilteringBoundLogger,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._logger = logger
        self._sleep = sleep
        self._token: Optional[str] = None
        redact = tuple(value for value in (client_secret,) if value)
        # The token exchange body carries the client secret and returns a bearer token, neither of
        # which the name-based scrubbers recognise — keep it out of sample capture entirely.
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
                "scope": MANAGEMENT_TOKEN_SCOPE,
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

    def _token_or_mint(self) -> str:
        return self._token or self.mint_token()

    def request(self, method: str, url: str, body: Optional[dict[str, Any]] = None) -> Any:
        attempt = 0
        reminted = False

        while True:
            headers = {
                "Authorization": f"Bearer {self._token_or_mint()}",
                "X-Ms-Command-Name": COMMAND_NAME,
            }
            if method == "POST":
                response = self._api_session.post(
                    url, json=body or {}, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
                )
            else:
                response = self._api_session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

            # Tokens last ~1h; a long backfill can outlive one, so re-mint once before giving up.
            if response.status_code == 401 and not reminted:
                reminted = True
                self._token = None
                self.mint_token()
                continue

            if response.status_code == 429 or response.status_code >= 500:
                attempt += 1
                if attempt >= MAX_RETRY_ATTEMPTS:
                    raise AzureCostManagementRetryableError(
                        f"Azure Cost Management error (retryable): status={response.status_code}, url={url}"
                    )
                delay = _backoff_seconds(response, attempt)
                self._logger.debug(
                    f"Azure Cost Management throttled: status={response.status_code}, sleeping {delay}s (attempt {attempt})"
                )
                self._sleep(delay)
                continue

            if not response.ok:
                self._logger.error(
                    f"Azure Cost Management error: status={response.status_code}, body={response.text}, url={url}"
                )
                raise requests.HTTPError(
                    f"{response.status_code} Client Error: {response.reason} for url: {MANAGEMENT_HOST}{_error_description(response)}",
                    response=response,
                )

            return response.json()


def validate_credentials(
    tenant_id: str, client_id: str, client_secret: str, scope: str, api_version: str
) -> tuple[bool, Optional[str]]:
    """Mint a token, then probe the scope's dimension catalog — the cheapest call that proves both
    the service principal is genuine and that it holds Cost Management Reader on the scope."""
    try:
        normalized_scope = normalize_scope(scope)
    except ValueError as error:
        return False, str(error)

    client = AzureCostManagementClient(tenant_id, client_id, client_secret, structlog.get_logger(__name__))
    try:
        client.mint_token()
    except Exception:
        return False, "Could not authenticate with Azure AD. Check the tenant ID, client ID, and client secret."

    try:
        client.request("GET", _endpoint_url(normalized_scope, "dimensions", api_version))
    except Exception:
        return (
            False,
            "Could not read Azure Cost Management for that scope. Check the scope path and that the service principal has the Cost Management Reader role on it.",
        )

    return True, None


def get_rows(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    scope: str,
    endpoint: str,
    start_date: str | None,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AzureCostManagementResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = AZURE_COST_MANAGEMENT_ENDPOINTS[endpoint]
    normalized_scope = normalize_scope(scope)
    client = AzureCostManagementClient(tenant_id, client_id, client_secret, logger)

    if config.kind == "dimensions":
        payload = client.request("GET", _endpoint_url(normalized_scope, "dimensions", api_version))
        rows = rows_from_dimensions(payload, normalized_scope)
        if rows:
            yield rows
        return

    today = datetime.now(tz=UTC).date()
    if config.kind == "forecast":
        windows = [SyncWindow(start=today, end=today + timedelta(days=FORECAST_HORIZON_DAYS))]
    else:
        window_start = resolve_window_start(
            should_use_incremental_field, db_incremental_field_last_value, start_date, today
        )
        windows = build_windows(window_start, today)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    pending_next_link: Optional[str] = None
    if resume is not None and resume.window_start:
        windows = [window for window in windows if window.start.isoformat() >= resume.window_start]
        pending_next_link = resume.next_link
        logger.debug(f"Azure Cost Management: resuming {endpoint} from {resume.window_start}")

    url = _endpoint_url(normalized_scope, "forecast" if config.kind == "forecast" else "query", api_version)

    for index, window in enumerate(windows):
        body = build_query_body(config, window.start, window.end)
        next_link = pending_next_link
        pending_next_link = None

        while True:
            payload = client.request("POST", _validated_next_link(next_link) if next_link else url, body)
            rows, next_link = rows_from_query_result(payload, normalized_scope)
            if rows:
                yield rows

            # Checkpoint AFTER yielding, so a crash re-yields the last page instead of skipping it.
            if not next_link:
                break
            resumable_source_manager.save_state(
                AzureCostManagementResumeConfig(window_start=window.start.isoformat(), next_link=next_link)
            )

        if index + 1 < len(windows):
            resumable_source_manager.save_state(
                AzureCostManagementResumeConfig(window_start=windows[index + 1].start.isoformat())
            )


def azure_cost_management_source(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    scope: str,
    endpoint: str,
    start_date: str | None,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AzureCostManagementResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AZURE_COST_MANAGEMENT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            scope=scope,
            endpoint=endpoint,
            start_date=start_date,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_keys=config.partition_keys,
        partition_mode=config.partition_mode,
        partition_format=config.partition_format,
        # Windows are walked oldest-first and each query is sorted ascending on UsageDate.
        sort_mode="asc",
    )
