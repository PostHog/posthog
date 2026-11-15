import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import orjson
import pyarrow as pa
import requests
from asgiref.sync import async_to_sync

from products.warehouse_sources.sources.sdk import (
    Endpoint,
    EndpointResource,
    ExternalWebhookInfo,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSourceManager,
    make_tracked_session,
    rest_api_resource,
)
from products.warehouse_sources.sources.sdk.internals import table_from_py_list
from products.warehouse_sources.sources.webflow.settings import (
    ALL_WEBHOOK_EVENTS,
    ANALYZE_HISTORY_START,
    ANALYZE_METRIC_SCOPES,
    ANALYZE_REPORT_PATH,
    ANALYZE_REPORTS,
    ANALYZE_TOP_PAGES_LIMIT,
    COLLECTION_SCHEMA_PREFIX,
    DEFAULT_PAGE_SIZE,
    WEBFLOW_BASE_URL,
    WEBFLOW_ENDPOINTS,
    WEBHOOK_DELETE_PATH,
    WEBHOOK_PATH,
    WEBHOOK_SCHEMA_NAMES,
    WebflowAnalyzeReportConfig,
    WebflowEndpointConfig,
    collection_items_endpoint_config,
)

REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class WebflowResumeConfig:
    offset: int = 0
    # Start of the next Analyze report window, as an ISO 8601 UTC timestamp.
    analyze_window_start: Optional[str] = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _encode_path_segment(value: str) -> str:
    """Percent-encode a value before interpolating it into a URL path.

    ``site_id`` is a non-secret field a user can edit on an existing source while the
    saved ``api_token`` is preserved. Without encoding, a value containing ``/``, ``?``,
    or ``#`` could redirect the authenticated request to an unintended Webflow endpoint.
    Encoding with ``safe=""`` keeps every delimiter inside the single path segment.
    """
    return quote(value, safe="")


def _extract_items(data: Any, data_key: str) -> list[dict[str, Any]]:
    """Pull the list of records out of a Webflow list envelope.

    Webflow uses a per-resource envelope key (``sites``, ``collections``, ``items``,
    ``orders``, …) rather than a single consistent key. We try the configured key
    first, then fall back to the first list-valued, non-``pagination`` key so an
    unverified envelope guess degrades gracefully instead of silently dropping rows.
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    value = data.get(data_key)
    if isinstance(value, list):
        return value

    for key, candidate in data.items():
        if key != "pagination" and isinstance(candidate, list):
            return candidate
    return []


def _flatten_map(config: WebflowEndpointConfig) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Merge a nested object up into the row root (e.g. products nest the product
    under a ``product`` key alongside ``skus``)."""

    def _map(item: dict[str, Any]) -> dict[str, Any]:
        if config.flatten_key and isinstance(item.get(config.flatten_key), dict):
            rest = {**item}
            flattened = rest.pop(config.flatten_key)
            return {**flattened, **rest}
        return item

    return _map


def validate_credentials(api_token: str, site_id: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    url = f"{WEBFLOW_BASE_URL}/sites/{_encode_path_segment(site_id)}"
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            url, headers=_get_headers(api_token), timeout=10
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return (
            False,
            "Webflow rejected your API token. Create a new Site API token under Site settings → Apps & integrations "
            "→ API access, then reconnect.",
        )

    # A 403 means the token is genuine but lacks the scope for this probe. Accept it
    # at source-create (schema_name is None) so users only need to grant scopes for
    # the resources they actually want to sync; sync-time 403s are caught by
    # get_non_retryable_errors instead.
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Your Webflow API token is missing the scope required for this resource"

    if response.status_code == 404:
        return False, f"Webflow site '{site_id}' was not found or is not accessible by this token"

    # A 400 means Webflow rejected the Site ID as malformed before looking it up — distinct from a
    # 404 for a well-formed but unknown/inaccessible id. Surface a clear message instead of leaking
    # Webflow's raw "Validation Error: ..." envelope.
    if response.status_code == 400:
        return (
            False,
            "The Webflow Site ID isn't valid. Check that you entered the Site ID (not the site name or URL) and try again.",
        )

    try:
        message = response.json().get("message", response.text)
    except ValueError:
        message = response.text
    return False, message


def list_collections(api_token: str, site_id: str) -> list[dict[str, Any]]:
    url = f"{WEBFLOW_BASE_URL}/sites/{_encode_path_segment(site_id)}/collections"
    response = make_tracked_session(redact_values=(api_token,)).get(url, headers=_get_headers(api_token), timeout=30)
    response.raise_for_status()
    return _extract_items(response.json(), "collections")


def _resolve_collection_id(api_token: str, site_id: str, schema_name: str) -> str:
    for collection in list_collections(api_token, site_id):
        slug = collection.get("slug")
        if slug and f"{COLLECTION_SCHEMA_PREFIX}{slug}" == schema_name:
            return collection["id"]
    raise ValueError(f"Webflow collection for schema '{schema_name}' was not found on site '{site_id}'")


def _endpoint_config_for_schema(api_token: str, site_id: str, schema_name: str) -> WebflowEndpointConfig:
    if schema_name in WEBFLOW_ENDPOINTS:
        return WEBFLOW_ENDPOINTS[schema_name]
    if schema_name.startswith(COLLECTION_SCHEMA_PREFIX):
        collection_id = _resolve_collection_id(api_token, site_id, schema_name)
        return collection_items_endpoint_config(collection_id)
    raise ValueError(f"Unknown Webflow schema '{schema_name}'")


def _make_webhook_session(api_token: str) -> requests.Session:
    # Webflow returns a webhook's signing secret in the create response, so these responses
    # must stay out of sample capture.
    return make_tracked_session(
        headers=_get_headers(api_token),
        redact_values=(api_token,),
        capture=False,
    )


def _list_webhooks(session: requests.Session, site_id: str) -> list[dict[str, Any]]:
    url = f"{WEBFLOW_BASE_URL}{WEBHOOK_PATH.format(site_id=_encode_path_segment(site_id))}"
    webhooks: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = session.get(
            url, params={"limit": DEFAULT_PAGE_SIZE, "offset": offset}, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        body = response.json()
        page = [item for item in _extract_items(body, "webhooks") if isinstance(item, dict)]
        webhooks.extend(page)

        total = (body.get("pagination") or {}).get("total") if isinstance(body, dict) else None
        offset += len(page)
        if not page or not isinstance(total, int) or offset >= total:
            return webhooks


def _webhooks_matching(session: requests.Session, site_id: str, webhook_url: str) -> list[dict[str, Any]]:
    return [item for item in _list_webhooks(session, site_id) if item.get("url") == webhook_url]


def create_webhook(api_token: str, site_id: str, webhook_url: str) -> WebhookCreationResult:
    """Register one Webflow webhook per trigger type feeding a webhook-eligible table.

    Webflow's create endpoint takes a single ``triggerType``, so covering the order tables needs
    one registration per event. Each registration is issued its own ``secretKey``, returned only
    at creation time, so every secret is collected and stored together — a delivery is accepted
    if it verifies against any of them.
    """
    try:
        session = _make_webhook_session(api_token)
        url = f"{WEBFLOW_BASE_URL}{WEBHOOK_PATH.format(site_id=_encode_path_segment(site_id))}"

        # Already-registered triggers are skipped: Webflow caps registrations per trigger type
        # per site, and re-creating one would leave an orphan we'd keep delivering to.
        existing = {webhook.get("triggerType") for webhook in _webhooks_matching(session, site_id, webhook_url)}

        secrets: list[str] = []
        registered: list[str] = []
        errors: list[str] = []

        for trigger_type in ALL_WEBHOOK_EVENTS:
            if trigger_type in existing:
                continue
            response = session.post(
                url,
                json={"triggerType": trigger_type, "url": webhook_url},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code not in (200, 201):
                errors.append(f"{trigger_type}: HTTP {response.status_code}")
                continue
            registered.append(trigger_type)
            secret = response.json().get("secretKey")
            if secret:
                secrets.append(secret)

        if not registered and not existing:
            detail = f" ({'; '.join(errors)})" if errors else ""
            return WebhookCreationResult(
                success=False,
                error=(
                    f"Webflow refused to register the webhook{detail}. Check that your API token has "
                    "the sites:write scope, or create the webhook manually below."
                ),
            )

        # A secret we never saw can't be reconstructed — Webflow only returns it on create, and
        # tokens predating its per-webhook secrets return none at all. Ask for one by hand so
        # deliveries aren't silently rejected.
        complete = len(secrets) == len(ALL_WEBHOOK_EVENTS)
        pending_inputs = [] if complete else ["signing_secret"]
        extra_inputs: dict[str, Any] = (
            {"signing_secrets": secrets, "signing_secrets_complete": complete} if secrets else {}
        )
        return WebhookCreationResult(success=True, extra_inputs=extra_inputs, pending_inputs=pending_inputs)
    except Exception as e:
        return WebhookCreationResult(
            success=False,
            error=f"Failed to create the Webflow webhook: {e}. Please create it manually below.",
        )


def get_external_webhook_info(api_token: str, site_id: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        matching = _webhooks_matching(_make_webhook_session(api_token), site_id, webhook_url)
        if not matching:
            return ExternalWebhookInfo(exists=False)
        return ExternalWebhookInfo(
            exists=True,
            url=webhook_url,
            enabled_events=sorted({str(webhook.get("triggerType")) for webhook in matching}),
            status="enabled",
            created_at=min(
                (str(webhook["createdOn"]) for webhook in matching if webhook.get("createdOn")), default=None
            ),
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))


def delete_webhook(api_token: str, site_id: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        session = _make_webhook_session(api_token)
        errors: list[str] = []
        for webhook in _webhooks_matching(session, site_id, webhook_url):
            webhook_id = webhook.get("id")
            if not webhook_id:
                continue
            response = session.delete(
                f"{WEBFLOW_BASE_URL}{WEBHOOK_DELETE_PATH.format(webhook_id=_encode_path_segment(str(webhook_id)))}",
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            # 404 means it's already gone, which is the outcome we wanted.
            if response.status_code not in (200, 204, 404):
                errors.append(f"webhook {webhook_id}: HTTP {response.status_code}")
        if errors:
            return WebhookDeletionResult(success=False, error="; ".join(errors))
        return WebhookDeletionResult(success=True)
    except Exception as e:
        return WebhookDeletionResult(success=False, error=str(e))


def _delivered_at(value: Any) -> int:
    """Webflow's x-webflow-timestamp as an int, or 0 when it's missing or unparseable."""
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _coerce_payload(value: Any) -> Optional[dict[str, Any]]:
    """Nested objects survive the arrow round trip as JSON strings, so decode before reading."""
    if isinstance(value, str | bytes):
        try:
            value = orjson.loads(value)
        except orjson.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Reshape raw webhook deliveries into rows matching the polled orders table.

    The Hog template delivers `{triggerType, webflowTimestamp, payload}`, so the Order object has
    to be lifted out of `payload`. Only the newest delivery per `orderId` survives: delta merge
    dedupes across syncs but not within one batch, so an `ecomm_new_order` followed by an
    `ecomm_order_changed` for the same order must collapse here.
    """
    if "payload" not in table.column_names:
        return table_from_py_list([])

    timestamps = (
        table.column("webflowTimestamp").to_pylist()
        if "webflowTimestamp" in table.column_names
        else [None] * table.num_rows
    )

    latest_by_id: dict[Any, tuple[int, dict[str, Any]]] = {}
    for raw_payload, timestamp in zip(table.column("payload").to_pylist(), timestamps):
        payload = _coerce_payload(raw_payload)
        if payload is None:
            continue
        order_id = payload.get("orderId")
        if order_id is None:
            continue

        delivered_at = _delivered_at(timestamp)
        existing = latest_by_id.get(order_id)
        # Later rows win ties, so batch arrival order breaks equal or missing timestamps.
        if existing is None or delivered_at >= existing[0]:
            latest_by_id[order_id] = (delivered_at, payload)

    return table_from_py_list([payload for _, payload in latest_by_id.values()])


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _start_of_day(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _analyze_start(should_use_incremental_field: bool, last_value: Any) -> datetime:
    last = _parse_time(last_value) if should_use_incremental_field else None
    if last is None:
        return ANALYZE_HISTORY_START
    # Fetch the last synced day again, because late events can still change its numbers.
    return max(ANALYZE_HISTORY_START, _start_of_day(last))


def _analyze_windows(start: datetime, end: datetime, days: int) -> Iterator[tuple[datetime, datetime]]:
    while start < end:
        window_end = min(start + timedelta(days=days), end)
        yield start, window_end
        start = window_end


def _get_report(session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {}


def _daily_series_rows(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    value_key: str,
    column_for_scope: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Merge the per-scope series of a report into one row per day.

    The report returns one metric scope per request, so each scope is a separate call.
    """
    rows: dict[datetime, dict[str, Any]] = {}
    for scope in ANALYZE_METRIC_SCOPES:
        body = _get_report(session, url, {**params, "metricScope": scope})
        for point in body.get("data") or []:
            if not isinstance(point, dict):
                continue
            timestamp = _parse_time(point.get("timestamp"))
            if timestamp is None:
                continue
            rows.setdefault(timestamp, {"timestamp": timestamp})[column_for_scope(scope)] = point.get(value_key)
    return [rows[timestamp] for timestamp in sorted(rows)]


def _analyze_window_rows(
    session: requests.Session,
    url: str,
    config: WebflowAnalyzeReportConfig,
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    window = {"startTime": _format_time(window_start), "endTime": _format_time(window_end)}

    if config.report == "traffic":
        return _daily_series_rows(
            session, url, {**window, "bucketTimeZone": "UTC"}, "count", lambda scope: f"{scope}Count"
        )

    if config.report == "time_on_page":
        return _daily_series_rows(
            session,
            url,
            {**window, "timeseries[granularityPeriod]": "day", "timeseries[bucketTimeZone]": "UTC"},
            "averageSeconds",
            lambda scope: f"averageSecondsPer{scope.capitalize()}",
        )

    if config.report == "top_pages":
        body = _get_report(session, url, {**window, "limit": ANALYZE_TOP_PAGES_LIMIT})
        # A non-CMS page has no itemSlug. The key column cannot be null, because null never
        # matches in a merge.
        return [
            {**item, "timestamp": window_start, "itemSlug": item.get("itemSlug") or ""}
            for item in body.get("data") or []
            if isinstance(item, dict)
        ]

    raise ValueError(f"Unknown Webflow Analyze report '{config.report}'")


def _analyze_rows(
    api_token: str,
    site_id: str,
    config: WebflowAnalyzeReportConfig,
    resumable_source_manager: ResumableSourceManager[WebflowResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,))
    url = WEBFLOW_BASE_URL + ANALYZE_REPORT_PATH.format(site_id=_encode_path_segment(site_id), report=config.report)

    start = _analyze_start(should_use_incremental_field, db_incremental_field_last_value)
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        resumed_start = _parse_time(resume.analyze_window_start) if resume else None
        if resumed_start is not None:
            start = resumed_start

    # Only complete UTC days, so a synced day is never a partial count.
    end = _start_of_day(datetime.now(UTC))

    # Analyze allows one request in flight per token, so the windows are fetched in sequence.
    for window_start, window_end in _analyze_windows(start, end, config.window_days):
        rows = _analyze_window_rows(session, url, config, window_start, window_end)
        if window_end < end:
            resumable_source_manager.save_state(WebflowResumeConfig(analyze_window_start=_format_time(window_end)))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def _analyze_source_response(
    api_token: str,
    site_id: str,
    config: WebflowAnalyzeReportConfig,
    resumable_source_manager: ResumableSourceManager[WebflowResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=lambda: _analyze_rows(
            api_token,
            site_id,
            config,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["timestamp"],
        sort_mode=config.sort_mode,
    )


def webflow_source(
    api_token: str,
    site_id: str,
    schema_name: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WebflowResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    if schema_name in ANALYZE_REPORTS:
        return _analyze_source_response(
            api_token,
            site_id,
            ANALYZE_REPORTS[schema_name],
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    config = _endpoint_config_for_schema(api_token, site_id, schema_name)

    path = config.path.format(site_id=_encode_path_segment(site_id)) if config.requires_site else config.path

    params: dict[str, Any] = {}
    if config.sort_by:
        params["sortBy"] = config.sort_by
        params["sortOrder"] = config.sort_order

    # Paginated list endpoints page with limit/offset and report the grand total under
    # `pagination.total`; single-object and non-paginated list endpoints are one request.
    if config.paginated:
        paginator: OffsetPaginator | SinglePagePaginator = OffsetPaginator(
            limit=DEFAULT_PAGE_SIZE, total_path="pagination.total"
        )
    else:
        paginator = SinglePagePaginator()

    endpoint: Endpoint = {
        "path": path,
        "params": params,
        # A single-object endpoint (/sites/{site_id}) has no list envelope; "$" wraps the
        # whole object into one row. List endpoints carry rows under a per-resource key.
        "data_selector": "$" if config.single_object else config.data_key,
    }

    resource_config: EndpointResource = {
        "name": schema_name,
        "endpoint": endpoint,
    }
    if config.flatten_key:
        resource_config["data_map"] = _flatten_map(config)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": WEBFLOW_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes) rather than skipping it. The saved offset
        # already points at the next page to fetch.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(WebflowResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    webhook_enabled = False
    if webhook_source_manager is not None and schema_name in WEBHOOK_SCHEMA_NAMES:
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    def items():
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=webhook_table_transformer)
        return resource

    return SourceResponse(
        name=schema_name,
        items=items,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
