import re
import json
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser
from requests import Response

from products.warehouse_sources.sources.bolddesk.settings import (
    API_PATH,
    BOLDDESK_ENDPOINTS,
    PER_PAGE,
    BoldDeskEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

BOLDDESK_HOST_SUFFIX = ".bolddesk.com"

# One DNS label. Anything else (dots, slashes, `@`, a port) could move the API key to another host.
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


@dataclasses.dataclass(frozen=True)
class BoldDeskResumeConfig:
    next_page: int


class InvalidBoldDeskDomainError(ValueError):
    pass


def normalize_subdomain(domain: str) -> str:
    """Reduce `acme`, `acme.bolddesk.com` or `https://acme.bolddesk.com/` to `acme`."""
    cleaned = domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    cleaned = cleaned.removesuffix(BOLDDESK_HOST_SUFFIX)
    if not _SUBDOMAIN_RE.match(cleaned):
        raise InvalidBoldDeskDomainError(
            f"Invalid BoldDesk domain: {domain!r}. Enter your BoldDesk subdomain, for example 'yourcompany' "
            f"for yourcompany{BOLDDESK_HOST_SUFFIX}."
        )
    return cleaned


def base_url(domain: str) -> str:
    return f"https://{normalize_subdomain(domain)}{BOLDDESK_HOST_SUFFIX}{API_PATH}"


def _to_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        parsed = parser.isoparse(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_q_datetime(value: Any) -> str:
    # The documented `Q` range format, e.g. 2020-11-30T18:30:00.000Z. Dropping the milliseconds
    # moves the bound back, so a boundary row is read again and the merge dedupes it.
    return _to_utc_datetime(value).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build_params(
    config: BoldDeskEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)
    if config.paginated:
        params["PerPage"] = PER_PAGE
    if config.order_by:
        params["OrderBy"] = config.order_by

    # The first incremental sync sends no filter, so it reads every row.
    if not (config.incremental_filter and should_use_incremental_field and db_incremental_field_last_value):
        return params

    if config.incremental_filter == "q":
        from_value = json.dumps({"from": format_q_datetime(db_incremental_field_last_value)}, separators=(",", ":"))
        params["Q"] = f"lastmodifiedon:{from_value}"
    else:
        params["updatedFromDate"] = _to_utc_datetime(db_incremental_field_last_value).isoformat(timespec="seconds")
    return params


class BoldDeskPaginator(PageNumberPaginator):
    """`Page` pagination from 1. A page shorter than `PerPage` is the last page."""

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="Page", total_path=None)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < PER_PAGE:
            self._has_next_page = False


def _client_config(domain: str, api_key: str) -> ClientConfig:
    return {
        "base_url": base_url(domain),
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "name": "x-api-key", "api_key": api_key, "location": "header"},
        "paginator": BoldDeskPaginator(),
        # The key rides in a custom header, which `requests` keeps on a cross-host redirect.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def bolddesk_source(
    domain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BoldDeskResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BOLDDESK_ENDPOINTS[endpoint]
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)

    endpoint_def: Endpoint = {
        "path": config.path,
        "params": build_params(config, should_use_incremental_field, db_incremental_field_last_value),
        "data_selector": "result",
    }
    if not config.paginated:
        endpoint_def["paginator"] = "single_page"

    rest_config: RESTAPIConfig = {
        "client": _client_config(domain, api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "table_name": config.name,
                "primary_key": config.primary_keys,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
                "endpoint": endpoint_def,
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(BoldDeskResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(domain: str, api_key: str, endpoint: str = "tickets") -> tuple[bool, int | None]:
    """Read one row of `endpoint`. Returns `(ok, status_code)`, with `None` for a transport error."""
    config = BOLDDESK_ENDPOINTS[endpoint]
    url = f"{base_url(domain)}{config.path}"
    if config.paginated:
        url += "?Page=1&PerPage=1"
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"x-api-key": api_key, "Accept": "application/json"},
        allow_redirects=False,
    )
