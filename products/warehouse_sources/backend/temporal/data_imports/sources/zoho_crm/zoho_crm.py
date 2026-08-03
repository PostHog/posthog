import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.settings import (
    MODIFIED_TIME_FIELD,
    ZOHO_CRM_ENDPOINTS,
    ZohoCRMEndpointConfig,
)

DEFAULT_API_VERSION = "v8"

# Zoho accounts are pinned to one data center; the accounts host mints the token and the
# API host serves the records. The token response also names the account's real API domain,
# which wins over this mapping when present.
ZOHO_REGIONS: dict[str, tuple[str, str]] = {
    "us": ("https://accounts.zoho.com", "https://www.zohoapis.com"),
    "eu": ("https://accounts.zoho.eu", "https://www.zohoapis.eu"),
    "in": ("https://accounts.zoho.in", "https://www.zohoapis.in"),
    "au": ("https://accounts.zoho.com.au", "https://www.zohoapis.com.au"),
    "jp": ("https://accounts.zoho.jp", "https://www.zohoapis.jp"),
    "ca": ("https://accounts.zohocloud.ca", "https://www.zohoapis.ca"),
    "cn": ("https://accounts.zoho.com.cn", "https://www.zohoapis.com.cn"),
}

# Zoho caps `per_page` at 200.
PAGE_SIZE = 200
# `page`-based pagination stops at 2000 records (page * per_page); past that Zoho only
# serves further records through the response's `next_page_token`.
MAX_PAGE = 2000 // PAGE_SIZE
# Get Records accepts a bounded list of field API names, so wide modules are fetched as
# several field slices walked in lockstep and merged per page.
MAX_FIELDS_PER_REQUEST = 50
REQUEST_TIMEOUT_SECONDS = 60

# Shown when the refresh-token exchange is rejected. The raw Zoho `error` code (e.g. `invalid_code`)
# is kept on the exception for logs but never surfaced to users, who can't act on it.
REFRESH_TOKEN_REJECTED_MESSAGE = (
    "Zoho CRM rejected your refresh token. Generate a new one for your self client and reconnect."
)


class ZohoCRMAuthError(Exception):
    pass


@dataclasses.dataclass
class ZohoCRMResumeConfig:
    # 1-based page number for the `page` pagination window.
    page: int = 1
    # One `next_page_token` per field slice, in slice order. Empty until Zoho starts
    # returning tokens (i.e. once the page window is exhausted).
    page_tokens: list[str] = dataclasses.field(default_factory=list)


def resolve_hosts(region: str) -> tuple[str, str]:
    hosts = ZOHO_REGIONS.get(region)
    if hosts is None:
        raise ValueError(f"Invalid Zoho CRM region: {region}")
    return hosts


def format_modified_since(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 timestamp `If-Modified-Since` expects."""
    parsed = coerce_datetime_to_utc(value)
    if parsed is None:
        return str(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def chunk_fields(names: list[str], size: int = MAX_FIELDS_PER_REQUEST) -> list[list[str]]:
    """Split field API names into request-sized slices. An empty list means "no projection"."""
    if not names:
        return [[]]
    return [names[index : index + size] for index in range(0, len(names), size)]


class ZohoCRMClient:
    """Minimal Zoho CRM client: refresh-token auth, regional hosts, JSON GETs.

    Status-code retries (429/5xx) come from the tracked session, so nothing retries here.
    """

    def __init__(
        self,
        region: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        self._accounts_host, self._api_domain = resolve_hosts(region)
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        # capture=False keeps requests metered and logged but excludes them from HTTP sample
        # capture: Zoho responses carry raw CRM records (contacts, notes, emails, phone numbers,
        # free-text) and the token exchange returns the access token in a bare `access_token`
        # field — content the name-based scrubbers can't reliably redact.
        self._session = make_tracked_session(redact_values=(client_secret, refresh_token), capture=False)
        self._access_token: Optional[str] = None

    @property
    def api_domain(self) -> str:
        return self._api_domain

    def mint_access_token(self) -> str:
        response = self._session.post(
            f"{self._accounts_host}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()

        access_token = body.get("access_token")
        if not access_token:
            # Zoho answers a revoked or malformed refresh token with HTTP 200 and an `error` key.
            raise ZohoCRMAuthError(f"Zoho CRM token refresh failed: {body.get('error') or 'no access token returned'}")

        api_domain = body.get("api_domain")
        if api_domain:
            # The token response names the data center that actually owns this account.
            self._api_domain = str(api_domain).rstrip("/")

        self._access_token = str(access_token)
        return self._access_token

    def get(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> requests.Response:
        if self._access_token is None:
            self.mint_access_token()

        def _send() -> requests.Response:
            request_headers = {"Authorization": f"Zoho-oauthtoken {self._access_token}"}
            if headers:
                request_headers.update(headers)
            return self._session.get(
                f"{self._api_domain}{path}",
                params=params,
                headers=request_headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = _send()
        if response.status_code == 401:
            # Access tokens last an hour; a long sync outlives one.
            self.mint_access_token()
            response = _send()

        # 204 is Zoho's "nothing matched" — an empty body, not an error.
        if response.status_code != 204:
            response.raise_for_status()
        return response


def readable_field_names(client: ZohoCRMClient, api_version: str, module: str) -> list[str]:
    """Field API names Get Records can project for `module`, from the fields metadata API."""
    response = client.get(f"/crm/{api_version}/settings/fields", params={"module": module})
    if response.status_code == 204:
        return []

    names: list[str] = []
    for field in response.json().get("fields") or []:
        api_name = field.get("api_name")
        if not api_name:
            continue
        view_type = field.get("view_type")
        # `view_type.view` marks the fields Zoho will actually return on a read.
        if isinstance(view_type, dict) and view_type.get("view") is False:
            continue
        names.append(str(api_name))
    return names


def _fetch_page(
    client: ZohoCRMClient,
    api_version: str,
    config: ZohoCRMEndpointConfig,
    params: dict[str, str],
    headers: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    response = client.get(f"/crm/{api_version}/{config.path}", params=params, headers=headers)
    if response.status_code == 204:
        return [], {}

    body = response.json()
    return list(body.get(config.data_key) or []), dict(body.get("info") or {})


def _merge_slice(rows: dict[str, dict[str, Any]], order: list[str], records: list[dict[str, Any]]) -> None:
    """Fold one field slice's records into the page under construction, keyed by record id."""
    for position, record in enumerate(records):
        record_id = record.get("id")
        key = str(record_id) if record_id is not None else f"__position_{position}"
        if key not in rows:
            rows[key] = {}
            order.append(key)
        rows[key].update(record)


def _sort_params(
    config: ZohoCRMEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
) -> dict[str, str]:
    if not config.is_module:
        return {}
    # Ascending order on the cursor field keeps the pipeline's watermark monotonic. Full
    # refreshes sort by the immutable id so page boundaries don't shift mid-sync.
    if config.incremental and should_use_incremental_field:
        return {"sort_by": incremental_field or MODIFIED_TIME_FIELD, "sort_order": "asc"}
    return {"sort_by": "id", "sort_order": "asc"}


def get_rows(
    client: ZohoCRMClient,
    api_version: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[ZohoCRMResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ZOHO_CRM_ENDPOINTS[endpoint]

    headers: dict[str, str] = {}
    if config.incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        headers["If-Modified-Since"] = format_modified_since(db_incremental_field_last_value)

    base_params: dict[str, str] = {"per_page": str(PAGE_SIZE)}
    base_params.update(config.extra_params or {})
    base_params.update(_sort_params(config, should_use_incremental_field, incremental_field))

    field_slices: list[list[str]] = [[]]
    if config.is_module:
        field_slices = chunk_fields(readable_field_names(client, api_version, config.path))

    page = 1
    page_tokens: list[str] = []
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        page = max(resume.page, 1)
        # Page tokens encode the exact query that produced them, so a changed slice count
        # (a field added or removed since the checkpoint) invalidates them.
        if len(resume.page_tokens) == len(field_slices) and all(resume.page_tokens):
            page_tokens = list(resume.page_tokens)
        elif page > MAX_PAGE:
            # Past the page window with no usable token there is no way back in — restart.
            page = 1

    while True:
        rows: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        info: dict[str, Any] = {}
        next_tokens: list[str] = []

        for index, fields in enumerate(field_slices):
            params = dict(base_params)
            if fields:
                params["fields"] = ",".join(fields)
            token = page_tokens[index] if index < len(page_tokens) else ""
            if token:
                params["page_token"] = token
            else:
                params["page"] = str(page)

            records, slice_info = _fetch_page(client, api_version, config, params, headers)
            if index == 0:
                info = slice_info
            _merge_slice(rows, order, records)
            next_tokens.append(str(slice_info.get("next_page_token") or ""))

        page_rows = [rows[key] for key in order]
        if page_rows:
            yield page_rows

        if not page_rows or not info.get("more_records"):
            break

        page += 1
        # A token is only usable when every slice got one — a half-tokenized page would walk
        # the slices to different offsets and merge unrelated records.
        page_tokens = next_tokens if all(next_tokens) else []
        if not page_tokens and page > MAX_PAGE:
            logger.warning(
                "Zoho CRM stopped paginating at the 2000-record page limit without a next page token",
                endpoint=endpoint,
                page=page,
            )
            break

        resumable_source_manager.save_state(ZohoCRMResumeConfig(page=page, page_tokens=page_tokens))

    resumable_source_manager.clear_state()


def validate_credentials(
    region: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    api_version: str = DEFAULT_API_VERSION,
) -> tuple[bool, Optional[str]]:
    try:
        client = ZohoCRMClient(region, client_id, client_secret, refresh_token)
    except ValueError as e:
        return False, str(e)

    try:
        client.get(f"/crm/{api_version}/settings/modules")
    except ZohoCRMAuthError:
        return False, REFRESH_TOKEN_REJECTED_MESSAGE
    except Exception:
        return False, None
    return True, None


def zoho_crm_source(
    region: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[ZohoCRMResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = ZOHO_CRM_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        return get_rows(
            client=ZohoCRMClient(region, client_id, client_secret, refresh_token),
            api_version=api_version,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["id"],
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
