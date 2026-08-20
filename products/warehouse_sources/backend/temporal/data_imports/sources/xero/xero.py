import re
import datetime
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.settings import (
    TENANT_ID_COLUMN,
    TENANT_NAME_COLUMN,
    XERO_ENDPOINTS,
    XeroEndpointConfig,
)

XERO_CONNECTIONS_URL = "https://api.xero.com/connections"
XERO_API_BASE_URL = "https://api.xero.com/api.xro/2.0"

PAGE_SIZE = 500
# Belt and braces against an endpoint that quietly ignores `page` and keeps answering.
MAX_PAGES = 20_000
REQUEST_TIMEOUT_SECONDS = 120

# `/Date(1573755038314+0000)/` — the .NET serialization Xero still emits for its UTC timestamps.
_DOTNET_DATE_RE = re.compile(r"^/Date\((-?\d+)(?:[+-]\d{4})?\)/$")


class XeroAuthError(Exception):
    pass


@dataclasses.dataclass
class XeroResumeConfig:
    cursor: int
    """Next page number (page mode) or JournalNumber offset (offset mode) to request."""


def _dotnet_date_to_iso(value: str) -> Optional[str]:
    match = _DOTNET_DATE_RE.match(value)
    if match is None:
        return None
    millis = int(match.group(1))
    moment = datetime.datetime.fromtimestamp(millis / 1000, tz=datetime.UTC)
    return moment.isoformat()


def normalize_dates(value: Any) -> Any:
    """Rewrite Xero's .NET date strings into ISO 8601, recursively.

    Xero returns UTC timestamps as ``/Date(<epoch millis>+0000)/`` at every level of the
    payload (including nested line items), which no downstream consumer can read as a
    timestamp — and ``UpdatedDateUTC`` in that shape would make the incremental watermark
    a lexicographic comparison of opaque strings.
    """
    if isinstance(value, str):
        return _dotnet_date_to_iso(value) or value
    if isinstance(value, list):
        return [normalize_dates(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_dates(item) for key, item in value.items()}
    return value


def format_modified_since(value: Any) -> Optional[str]:
    """Format an incremental watermark for the ``If-Modified-Since`` header.

    Xero documents the header as a UTC timestamp in ``yyyy-mm-ddThh:mm:ss`` form, so an
    offset-aware value is converted to UTC and its offset dropped rather than sent as-is.
    """
    if value is None:
        return None

    if isinstance(value, str):
        try:
            parsed = datetime.datetime.fromisoformat(value)
        except ValueError:
            return None
    elif isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, datetime.date):
        parsed = datetime.datetime.combine(value, datetime.time.min)
    else:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.UTC).replace(tzinfo=None)

    return parsed.strftime("%Y-%m-%dT%H:%M:%S")


class XeroClient:
    """Minimal Xero client: resolves organizations and reads collections with an OAuth access token."""

    def __init__(self, access_token: str) -> None:
        # Sample capture is off: the data responses carry financial and contact records the generic
        # scrubber would not strip. Traffic stays metered but is never sampled.
        self._session = make_tracked_session(
            headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
            redact_values=(access_token,),
            capture=False,
        )

    def list_organisations(self) -> list[dict[str, Any]]:
        """Organizations the connected Xero login granted us.

        Xero has no implicit "current" organization — every Accounting API call must name one
        via the ``Xero-Tenant-Id`` header, and ``/connections`` is the only way to learn them.
        """
        response = self._session.get(XERO_CONNECTIONS_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()

        payload = response.json()
        connections = payload if isinstance(payload, list) else []
        return [
            connection
            for connection in connections
            if connection.get("tenantType", "ORGANISATION") == "ORGANISATION" and connection.get("tenantId")
        ]

    def get_organisation(self, tenant_id: str) -> dict[str, Any]:
        for organisation in self.list_organisations():
            if organisation["tenantId"] == tenant_id:
                return organisation
        raise XeroAuthError(f"Xero organization {tenant_id} is not connected to this app")

    def get_collection(
        self,
        endpoint: XeroEndpointConfig,
        tenant_id: str,
        params: dict[str, Any],
        modified_since: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        url = f"{XERO_API_BASE_URL}/{endpoint.path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        headers = {"Xero-Tenant-Id": tenant_id}
        if modified_since is not None:
            headers["If-Modified-Since"] = modified_since

        response = self._session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # `If-Modified-Since` makes an unchanged collection answer 304 with no body.
        if response.status_code == 304:
            return []

        response.raise_for_status()

        rows = response.json().get(endpoint.data_key) or []
        return rows if isinstance(rows, list) else []


def _decorate(rows: list[dict[str, Any]], tenant: dict[str, Any]) -> list[dict[str, Any]]:
    tenant_id = tenant["tenantId"]
    tenant_name = tenant.get("tenantName")
    return [
        {**normalize_dates(row), TENANT_ID_COLUMN: tenant_id, TENANT_NAME_COLUMN: tenant_name}
        for row in rows
        if isinstance(row, dict)
    ]


def _first_key(rows: list[dict[str, Any]], endpoint: XeroEndpointConfig) -> Optional[str]:
    if not rows:
        return None
    return str(rows[0].get(endpoint.primary_key[0]))


def _initial_cursor(endpoint: XeroEndpointConfig) -> int:
    # Pages are 1-based; the Journals offset is exclusive and starts below the first JournalNumber.
    return 1 if endpoint.pagination == "page" else 0


def _query_params(endpoint: XeroEndpointConfig, cursor: int) -> dict[str, Any]:
    if endpoint.pagination == "page":
        params: dict[str, Any] = {"page": cursor, "pageSize": PAGE_SIZE}
        if endpoint.incremental_field == "UpdatedDateUTC":
            # Pin the order so the pipeline's ascending watermark advances monotonically across
            # pages instead of trusting Xero's unspecified default ordering.
            params["order"] = "UpdatedDateUTC ASC"
        return params
    if endpoint.pagination == "offset":
        return {"offset": cursor}
    return {}


def _next_offset(rows: list[dict[str, Any]], current: int) -> int:
    numbers = [value for value in (row.get("JournalNumber") for row in rows) if isinstance(value, int)]
    return max(numbers) if numbers else current + len(rows)


def get_rows(
    client: XeroClient,
    endpoint_name: str,
    tenant_id: str,
    resumable_source_manager: ResumableSourceManager[XeroResumeConfig],
    logger: FilteringBoundLogger,
    modified_since: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = XERO_ENDPOINTS[endpoint_name]
    organisation = client.get_organisation(tenant_id)

    resume: Optional[XeroResumeConfig] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()

    cursor = resume.cursor if resume else _initial_cursor(endpoint)
    previous_first_key: Optional[str] = None
    pages = 0

    while True:
        rows = client.get_collection(
            endpoint,
            tenant_id=tenant_id,
            params=_query_params(endpoint, cursor),
            modified_since=modified_since,
        )
        if not rows:
            break

        if endpoint.pagination == "page":
            first_key = _first_key(rows, endpoint)
            if first_key is not None and first_key == previous_first_key:
                logger.warning(
                    "Xero returned an identical page — stopping to avoid an unbounded walk",
                    endpoint=endpoint.name,
                    page=cursor,
                )
                break
            previous_first_key = first_key

        yield _decorate(rows, organisation)

        if endpoint.pagination == "single":
            break

        cursor = cursor + 1 if endpoint.pagination == "page" else _next_offset(rows, cursor)
        # Checkpoint after the batch is yielded: a crash re-fetches from here and the merge
        # dedupes on the primary key, whereas checkpointing first would skip the batch.
        resumable_source_manager.save_state(XeroResumeConfig(cursor=cursor))

        pages += 1
        if pages >= MAX_PAGES:
            logger.warning(
                "Xero page cap reached — stopping early",
                endpoint=endpoint.name,
                tenant_id=tenant_id,
                pages=pages,
            )
            break

    resumable_source_manager.clear_state()


def xero_source(
    access_token: str,
    tenant_id: str,
    endpoint_name: str,
    resumable_source_manager: ResumableSourceManager[XeroResumeConfig],
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint = XERO_ENDPOINTS[endpoint_name]
    client = XeroClient(access_token=access_token)
    modified_since = format_modified_since(db_incremental_field_last_value) if endpoint.incremental_field else None

    return SourceResponse(
        name=endpoint.name,
        items=lambda: get_rows(
            client=client,
            endpoint_name=endpoint_name,
            tenant_id=tenant_id,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            modified_since=modified_since,
        ),
        primary_keys=[TENANT_ID_COLUMN, *endpoint.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        sort_mode="asc",
    )


def validate_credentials(access_token: str, tenant_id: str) -> tuple[bool, Optional[str]]:
    client = XeroClient(access_token=access_token)
    try:
        client.get_organisation(tenant_id)
    except XeroAuthError as e:
        return False, str(e)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (401, 403):
            return False, "Xero rejected the connection. Reconnect your Xero account and grant the read scopes."
        return False, f"Could not reach Xero: {e}"
    except Exception as e:
        return False, f"Could not reach Xero: {e}"

    return True, None
