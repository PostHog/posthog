import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.sdk import ResumableSourceManager, SourceResponse, make_tracked_session
from products.warehouse_sources.sources.wix.settings import WIX_ENDPOINTS, WixEndpointConfig

WIX_BASE_URL = "https://www.wixapis.com"
REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass(frozen=True)
class WixResumeConfig:
    cursor: str


def _get_session(api_key: str, site_id: str) -> requests.Session:
    return make_tracked_session(
        headers={
            "Authorization": api_key,
            "wix-site-id": site_id,
            "Content-Type": "application/json",
        },
        redact_values=(api_key,),
    )


def _to_wix_datetime(value: Any) -> Optional[str]:
    """Wix filters take RFC 3339 timestamps with a Z suffix."""
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        stamped = value if value.tzinfo else value.replace(tzinfo=UTC)
        return stamped.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return None


def _next_cursor(payload: dict[str, Any], cursors_key: str) -> Optional[str]:
    metadata = payload.get(cursors_key) or {}
    if metadata.get("hasNext") is False:
        return None
    cursor = (metadata.get("cursors") or {}).get("next")
    return cursor or None


def _query_field(config: WixEndpointConfig, field_name: str) -> str:
    return f"{config.record_key}.{field_name}" if config.record_key else field_name


def _first_page_criteria(
    endpoint: str,
    incremental_field: Optional[str],
    incremental_last_value: Any,
) -> dict[str, Any]:
    config = WIX_ENDPOINTS[endpoint]
    sort_field = _query_field(config, incremental_field or config.sort_field)
    paging_key = "paging" if config.paging == "offset" else "cursorPaging"
    criteria: dict[str, Any] = {
        paging_key: {"limit": config.page_size},
        "sort": [{"fieldName": sort_field, "order": "ASC"}],
    }
    watermark = _to_wix_datetime(incremental_last_value) if incremental_field else None
    if watermark is not None:
        criteria["filter"] = {sort_field: {"$gte": watermark}}
    return criteria


def _probe_body(config: WixEndpointConfig) -> dict[str, Any]:
    paging_key = "paging" if config.paging == "offset" else "cursorPaging"
    return {config.body_key: {paging_key: {"limit": 1}}, **config.extra_body}


def _get_params(config: WixEndpointConfig, limit: int, offset: Optional[int] = None) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if offset is not None:
        params.update(
            {"offset": offset, f"{config.body_key}.fieldName": config.sort_field, f"{config.body_key}.order": "ASC"}
        )
    return params


def _to_row(config: WixEndpointConfig, item: dict[str, Any]) -> dict[str, Any]:
    if config.record_key is None:
        return item
    extras = {key: value for key, value in item.items() if key != config.record_key}
    return {**(item.get(config.record_key) or {}), **extras}


def validate_credentials(api_key: str, site_id: str) -> tuple[bool, Optional[str]]:
    """Probe one cheap query to tell a bad key (401) from a key missing a permission (403)."""
    try:
        response = _get_session(api_key, site_id).post(
            f"{WIX_BASE_URL}/contacts/v4/contacts/query",
            json={"query": {"cursorPaging": {"limit": 1}}},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, "Could not reach the Wix API. Check your connection and try again."

    if response.ok:
        return True, None
    if response.status_code == 403:
        # The key is genuine; the site owner has not granted Contacts. Other tables may still sync,
        # and the schema picker reports per-table permissions separately.
        return True, None
    if response.status_code == 401:
        return False, "Wix rejected this API key. Check the key in the Wix API Key Manager and try again."
    # Wix answers an API key call with 404 when the site ID does not belong to the key's account.
    if response.status_code in (404, 428):
        return False, (
            "Wix could not find this site. Check the site ID matches the site you want to sync, and that the "
            "API key belongs to the same account."
        )
    return False, "Wix couldn't check your API key. Check the API key and site ID, then try again."


def check_endpoint_permissions(api_key: str, site_id: str, endpoints: list[str]) -> dict[str, Optional[str]]:
    """Report which endpoints this API key can read, so the picker can flag the rest."""
    session = _get_session(api_key, site_id)
    results: dict[str, Optional[str]] = {}
    for name in endpoints:
        config = WIX_ENDPOINTS.get(name)
        if config is None:
            results[name] = None
            continue
        # A batch lookup needs real parent IDs, and it needs the same permission as its parent.
        probe_config = WIX_ENDPOINTS[config.parent] if config.parent else config
        url = f"{WIX_BASE_URL}{probe_config.path}"
        try:
            if probe_config.http_method == "GET":
                response = session.get(url, params=_get_params(probe_config, 1), timeout=REQUEST_TIMEOUT_SECONDS)
            else:
                response = session.post(url, json=_probe_body(probe_config), timeout=REQUEST_TIMEOUT_SECONDS)
        except Exception:
            # A network blip is not a permission problem, so leave the table selectable.
            results[name] = None
            continue

        if response.status_code == 403:
            results[name] = f"This API key is missing the '{config.permission}' permission in Wix."
        elif response.status_code == 404:
            results[name] = "This app is not installed on the site."
        else:
            results[name] = None
    return results


def _get_offset_rows(
    session: requests.Session,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = WIX_ENDPOINTS[endpoint]
    url = f"{WIX_BASE_URL}{config.path}"
    criteria = _first_page_criteria(endpoint, None, None)
    offset = 0
    while True:
        if config.http_method == "GET":
            response = session.get(
                url, params=_get_params(config, config.page_size, offset), timeout=REQUEST_TIMEOUT_SECONDS
            )
        else:
            criteria["paging"]["offset"] = offset
            response = session.post(
                url, json={config.body_key: criteria, **config.extra_body}, timeout=REQUEST_TIMEOUT_SECONDS
            )
        if not response.ok:
            logger.error(f"Wix API request failed for {endpoint}: status={response.status_code}")
            response.raise_for_status()
        items = response.json().get(config.data_key) or []
        if items:
            yield [_to_row(config, item) for item in items]
        if len(items) < config.page_size:
            break
        offset += len(items)


def _get_cursor_rows(
    session: requests.Session,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WixResumeConfig],
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = WIX_ENDPOINTS[endpoint]
    url = f"{WIX_BASE_URL}{config.path}"

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume_config.cursor if resume_config is not None else None
    if cursor is not None:
        logger.debug(f"Wix: resuming {endpoint} from a saved cursor")

    def fetch(page_cursor: Optional[str]) -> dict[str, Any]:
        if page_cursor is None:
            criteria = _first_page_criteria(endpoint, incremental_field, db_incremental_field_last_value)
        else:
            # Wix encodes the filter and sort into the cursor, and rejects a request that repeats
            # them, so a follow-up page carries the cursor alone.
            criteria = {"cursorPaging": {"limit": config.page_size, "cursor": page_cursor}}
        response = session.post(
            url, json={config.body_key: criteria, **config.extra_body}, timeout=REQUEST_TIMEOUT_SECONDS
        )
        if not response.ok:
            logger.error(f"Wix API request failed for {endpoint}: status={response.status_code}")
            response.raise_for_status()
        return response.json()

    seen_cursors = {cursor} if cursor is not None else set()
    while True:
        try:
            payload = fetch(cursor)
        except requests.HTTPError as error:
            response = error.response
            if cursor is None or response is None or response.status_code != 400:
                raise
            # Wix cursors expire, so a resumed run can open with a cursor the API no longer accepts.
            # Restarting the stream is safe: merge dedupes on the primary key.
            logger.warning(f"Wix: {endpoint} cursor expired, restarting the stream from the first page")
            cursor = None
            seen_cursors.clear()
            payload = fetch(None)

        items = payload.get(config.data_key) or []
        cursor = _next_cursor(payload, config.cursors_key)

        if cursor is not None:
            if cursor in seen_cursors:
                raise RuntimeError(f"Wix returned a repeated cursor while paging {endpoint}")
            seen_cursors.add(cursor)
            resumable_source_manager.save_state(WixResumeConfig(cursor=cursor))

        if items:
            yield [_to_row(config, item) for item in items]

        if cursor is None or not items:
            break


def _get_order_child_rows(
    session: requests.Session,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WixResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = WIX_ENDPOINTS[endpoint]
    if config.parent is None:
        raise ValueError(f"Wix endpoint {endpoint} has no parent endpoint")
    url = f"{WIX_BASE_URL}{config.path}"

    # The parent walk stages its next cursor before it hands over a page, so a resumed run picks up
    # after the last page of orders whose transactions were yielded. One orders page holds at most
    # PAGE_SIZE orders, which is also the most order IDs Wix accepts in one lookup.
    for orders in _get_cursor_rows(session, config.parent, logger, resumable_source_manager):
        created_dates = {order["id"]: order.get("createdDate") for order in orders if order.get("id")}
        rows: list[dict[str, Any]] = []
        if created_dates:
            response = session.post(url, json={config.body_key: list(created_dates)}, timeout=REQUEST_TIMEOUT_SECONDS)
            if not response.ok:
                logger.error(f"Wix API request failed for {endpoint}: status={response.status_code}")
                response.raise_for_status()
            rows = [
                {**order_rows, "orderCreatedDate": created_dates.get(order_rows.get("orderId"))}
                for order_rows in response.json().get(config.data_key) or []
            ]
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def get_rows(
    api_key: str,
    site_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WixResumeConfig],
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = WIX_ENDPOINTS[endpoint]
    session = _get_session(api_key, site_id)

    if config.parent is not None:
        yield from _get_order_child_rows(session, endpoint, logger, resumable_source_manager)
    elif config.paging == "offset":
        yield from _get_offset_rows(session, endpoint, logger)
    else:
        yield from _get_cursor_rows(
            session,
            endpoint,
            logger,
            resumable_source_manager,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )


def wix_source(
    api_key: str,
    site_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WixResumeConfig],
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = WIX_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            site_id=site_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Every page is requested with an ascending sort on the cursor field. Transactions and
        # fulfillments follow their orders, so they have no order of their own.
        sort_mode=None if config.parent else "asc",
    )
