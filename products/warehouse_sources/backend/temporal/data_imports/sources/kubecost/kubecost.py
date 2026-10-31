import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.settings import (
    DEFAULT_BACKFILL_DAYS,
    INCREMENTAL_LOOKBACK_DAYS,
    KUBECOST_ENDPOINTS,
)

# Kubecost aggregates cost data at query time, so responses for large clusters can be slow.
REQUEST_TIMEOUT_SECONDS = 180
MAX_RETRY_ATTEMPTS = 5


class KubecostRetryableError(Exception):
    pass


@dataclasses.dataclass
class KubecostResumeConfig:
    # The next unfetched day (yyyy-mm-dd) of the day-by-day window walk.
    next_date: Optional[str] = None


def normalize_host(host: str) -> str:
    """Normalize the Kubecost API URL and reject anything that isn't plain http(s).

    Accepts the address with or without the trailing `/model` prefix the cost-model
    API is served under (`http://kubecost.example.com` and
    `http://kubecost.example.com/model` both work).
    """
    host = host.strip()
    if not host:
        raise ValueError("Kubecost API URL is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    if host.endswith("/model"):
        host = host[: -len("/model")]
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Kubecost API URL: {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


_PLAINTEXT_API_KEY_ERROR = (
    "An API key can only be sent to an https:// URL. Use HTTPS for the Kubecost API URL or remove the API key."
)


def _check_api_key_transport(base_url: str, api_key: Optional[str]) -> str | None:
    """The API key rides an `Authorization: Bearer` header, so it must never go over plaintext HTTP."""
    if api_key and not base_url.startswith("https://"):
        return _PLAINTEXT_API_KEY_ERROR
    return None


def _get_session(api_key: Optional[str]) -> requests.Session:
    # `host` is user-supplied, so pin redirects off: validation and the outbound
    # request must stay on the same target (SSRF defense-in-depth).
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    return make_tracked_session(
        headers=headers,
        redact_values=(api_key,) if api_key else (),
        allow_redirects=False,
    )


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _day_window(day: date) -> SyncWindow[str]:
    start = f"{day.isoformat()}T00:00:00Z"
    end = f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z"
    return SyncWindow(start=start, end=end)


def validate_credentials(host: str, api_key: Optional[str]) -> tuple[bool, str | None]:
    """Confirm the cost-model API is reachable and the credentials (if any) are accepted."""
    base_url = normalize_host(host)
    transport_error = _check_api_key_transport(base_url, api_key)
    if transport_error is not None:
        return False, transport_error

    try:
        response = _get_session(api_key).get(
            f"{base_url}/model/allocation",
            params={"window": "1d", "aggregate": "namespace", "accumulate": "true"},
            timeout=30,
        )
    except Exception:
        return False, "Unable to reach the Kubecost API. Check that the URL is correct and publicly reachable."

    if response.status_code in (401, 403):
        return False, "Kubecost authentication failed. Please check your API key."
    if response.status_code != 200:
        return False, f"Kubecost API returned an unexpected status ({response.status_code})."

    try:
        body = response.json()
    except ValueError:
        return False, "The URL did not return a Kubecost API response. Check that it points at the cost-model API."
    if not isinstance(body, dict) or body.get("code") != 200:
        message = body.get("message") if isinstance(body, dict) else None
        return False, f"Kubecost API error: {message or 'unexpected response'}"

    return True, None


def _flatten_result_sets(
    data: Any, requested_window: SyncWindow[str], result_set_key: Optional[str] = None
) -> list[dict[str, Any]]:
    """Flatten result sets (dicts keyed by allocation/asset/cloud cost name) into rows.

    Windows with no data (e.g. beyond ETL retention) come back as ``data: [null]``
    (or ``cloudCosts: null`` for Cloud Cost), so null/non-dict sets are skipped
    rather than treated as errors.
    """
    rows: list[dict[str, Any]] = []
    if result_set_key is not None:
        sets = data.get("sets") if isinstance(data, dict) else None
        data = [s.get(result_set_key) for s in sets if isinstance(s, dict)] if isinstance(sets, list) else None
    if not isinstance(data, list):
        return rows
    for result_set in data:
        if not isinstance(result_set, dict):
            continue
        for key, item in result_set.items():
            if not isinstance(item, dict):
                continue
            window = item.get("window")
            if not isinstance(window, dict):
                window = {}
            rows.append(
                {
                    **item,
                    "key": key,
                    "window_start": window.get("start") or requested_window.start,
                    "window_end": window.get("end") or requested_window.end,
                }
            )
    return rows


def _flatten_timeseries(data: Any, requested_window: SyncWindow[str], items_key: str) -> list[dict[str, Any]]:
    """Flatten External Costs `timeseries` windows, each holding a list of line items, into rows."""
    rows: list[dict[str, Any]] = []
    timeseries = data.get("timeseries") if isinstance(data, dict) else None
    if not isinstance(timeseries, list):
        return rows
    for entry in timeseries:
        if not isinstance(entry, dict):
            continue
        items = entry.get(items_key)
        if not isinstance(items, list):
            continue
        window = entry.get("window")
        if not isinstance(window, dict):
            window = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    **item,
                    "key": item.get("aggregate") or item.get("id"),
                    "window_start": window.get("start") or requested_window.start,
                    "window_end": window.get("end") or requested_window.end,
                }
            )
    return rows


def _audit_event_key(event: dict[str, Any]) -> str:
    # Audit events carry no id, so the key is built from what identifies the change.
    properties = event.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    parts = [
        event.get("timestamp"),
        event.get("eventType"),
        event.get("resourceType"),
        properties.get("cluster"),
        properties.get("namespace"),
        properties.get("name"),
    ]
    return "/".join("" if part is None else str(part) for part in parts)


_SNAPSHOT_KEY_BUILDERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "audit_events": _audit_event_key,
}


def _snapshot_rows(endpoint: str, data: Any) -> list[dict[str, Any]]:
    # Request sizing documents a bare list, and its topline variant wraps the list
    # in `Recommendations`, so both shapes are accepted.
    if isinstance(data, dict):
        data = data.get("Recommendations", data.get("recommendations"))
    if not isinstance(data, list):
        return []
    rows = [item for item in data if isinstance(item, dict)]
    key_builder = _SNAPSHOT_KEY_BUILDERS.get(endpoint)
    if key_builder is not None:
        rows = [{**row, "key": key_builder(row)} for row in rows]
    return rows


def _unwrap_response(body: Any, allow_bare: bool) -> Any:
    if isinstance(body, dict) and "code" in body:
        if body.get("code") != 200:
            raise ValueError(f"Kubecost API error: {body.get('message')}")
        return body.get("data")
    if allow_bare and isinstance(body, list | dict):
        return body
    message = body.get("message") if isinstance(body, dict) else body
    raise ValueError(f"Kubecost API error: {message}")


def get_rows(
    host: str,
    api_key: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KubecostResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = KUBECOST_ENDPOINTS[endpoint]
    base_url = normalize_host(host)
    transport_error = _check_api_key_transport(base_url, api_key)
    if transport_error is not None:
        raise ValueError(transport_error)
    session = _get_session(api_key)
    url = f"{base_url}{config.path}"

    @retry_with_deadline(
        retry=retry_if_exception_type((KubecostRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def call(params: dict[str, str]) -> Any:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise KubecostRetryableError(f"Kubecost API error (retryable): status={response.status_code}")

        if not response.ok:
            logger.error(f"Kubecost API error: status={response.status_code}, body={response.text[:500]}")
            response.raise_for_status()

        return response.json()

    if config.snapshot_primary_keys is not None:
        rows = _snapshot_rows(endpoint, _unwrap_response(call(dict(config.params)), allow_bare=True))
        if rows:
            yield rows
        return

    # No cursor or pagination: the query window itself is the incremental filter, so we
    # walk contiguous one-day windows oldest-first. Recent days restate as cloud-billing
    # reconciliation lands, so incremental runs re-pull a trailing lookback window.
    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=DEFAULT_BACKFILL_DAYS)
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            start = watermark - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.next_date:
        resumed = _to_date(resume_config.next_date)
        if resumed is not None and resumed > start:
            start = resumed
            logger.debug(f"Kubecost: resuming {endpoint} from {start.isoformat()}")

    day = start
    while day <= today:
        window = _day_window(day)
        body = call({**config.params, "window": f"{window.start},{window.end}", "accumulate": "true"})
        data = _unwrap_response(body, allow_bare=False)
        if config.timeseries_items_key is not None:
            rows = _flatten_timeseries(data, window, config.timeseries_items_key)
        else:
            rows = _flatten_result_sets(data, window, config.result_set_key)
        if rows:
            yield rows

        day = day + timedelta(days=1)
        if day <= today:
            # Save state AFTER yielding so a crash re-yields the in-flight day
            # (merge dedupes on (key, window_start)).
            resumable_source_manager.save_state(KubecostResumeConfig(next_date=day.isoformat()))


def kubecost_source(
    host: str,
    api_key: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KubecostResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = KUBECOST_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        return get_rows(
            host=host,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    if config.snapshot_primary_keys is not None:
        return SourceResponse(name=endpoint, items=items, primary_keys=list(config.snapshot_primary_keys))

    return SourceResponse(
        name=endpoint,
        items=items,
        # The result-set key is only unique within one window, so the window start is
        # part of the key. `window_start` never changes for a given row, making it a
        # stable partition key too.
        primary_keys=["key", "window_start"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["window_start"],
        # Days are walked oldest-first; the cursor only moves forward.
        sort_mode="asc",
    )
