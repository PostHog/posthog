import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.wix.settings import WIX_ENDPOINTS

WIX_BASE_URL = "https://www.wixapis.com"
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass
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


def _first_page_criteria(
    endpoint: str,
    incremental_field: Optional[str],
    incremental_last_value: Any,
) -> dict[str, Any]:
    config = WIX_ENDPOINTS[endpoint]
    sort_field = incremental_field or config.sort_field
    criteria: dict[str, Any] = {
        "cursorPaging": {"limit": PAGE_SIZE},
        "sort": [{"fieldName": sort_field, "order": "ASC"}],
    }
    watermark = _to_wix_datetime(incremental_last_value) if incremental_field else None
    if watermark is not None:
        criteria["filter"] = {sort_field: {"$gte": watermark}}
    return criteria


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
    if response.status_code == 428:
        return False, (
            "Wix could not find this site. Check the site ID matches the site you want to sync, and that the "
            "API key belongs to the same account."
        )
    return False, f"Wix returned an unexpected error ({response.status_code}) while checking these credentials."


def check_endpoint_permissions(api_key: str, site_id: str, endpoints: list[str]) -> dict[str, Optional[str]]:
    """Report which endpoints this API key can read, so the picker can flag the rest."""
    session = _get_session(api_key, site_id)
    results: dict[str, Optional[str]] = {}
    for name in endpoints:
        config = WIX_ENDPOINTS.get(name)
        if config is None:
            results[name] = None
            continue
        try:
            response = session.post(
                f"{WIX_BASE_URL}{config.path}",
                json={config.body_key: {"cursorPaging": {"limit": 1}}},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
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
            criteria = {"cursorPaging": {"limit": PAGE_SIZE, "cursor": page_cursor}}
        response = session.post(url, json={config.body_key: criteria}, timeout=REQUEST_TIMEOUT_SECONDS)
        if not response.ok:
            logger.error(f"Wix API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()
        return response.json()

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
            payload = fetch(None)

        items = payload.get(config.data_key) or []
        cursor = _next_cursor(payload, config.cursors_key)

        if cursor is not None:
            resumable_source_manager.save_state(WixResumeConfig(cursor=cursor))

        if items:
            yield items

        if cursor is None or not items:
            break


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
        # Every page is requested with an ascending sort on the cursor field.
        sort_mode="asc",
    )
