import re
import base64
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import urlencode

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import (
    unreachable_vendor_message,
    validate_via_probe,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.settings import (
    PAGE_SIZE,
    XMATTERS_ENDPOINTS,
    XmattersEndpointConfig,
)

# xMatters is per-instance: every account lives at a customer-specific subdomain.
BASE_URL_TEMPLATE = "https://{subdomain}.xmatters.com/api/xm/1"

# A single DNS label: letters, digits, and internal hyphens only. Anything else (slashes, dots,
# `@`, etc.) could redirect worker requests to an attacker-controlled host (SSRF).
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")

# Historical data has a 15-minute synchronization window, so an `at` closer to now can be rejected.
HISTORICAL_DATA_LAG = timedelta(minutes=20)


@dataclasses.dataclass(frozen=True)
class XmattersResumeConfig:
    # Flat endpoints resume from `offset`; fan-out endpoints round-trip the framework's opaque
    # per-parent checkpoint through `paginator_state`.
    offset: int = 0
    paginator_state: Optional[dict[str, Any]] = None
    # A resumed child offset only addresses the same rows under the same historical snapshot.
    historical_at: Optional[str] = None


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(SUBDOMAIN_REGEX.match(subdomain))


def _base_url(subdomain: str) -> str:
    if not is_valid_subdomain(subdomain):
        raise ValueError("xMatters subdomain is invalid")
    return BASE_URL_TEMPLATE.format(subdomain=subdomain)


def _format_incremental_value(value: Any) -> str:
    """Format an incremental field value as an ISO 8601 UTC string for xMatters' `from` filter."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _get_headers(username: str, password: str) -> dict[str, str]:
    # HTTP Basic works for both a service account (username/password) and an xMatters REST API
    # key (key as username, secret as password).
    basic_token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {
        "Authorization": f"Basic {basic_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


class XmattersPaginator(OffsetPaginator):
    """Offset paginator driven by xMatters' `links.next` signal.

    xMatters list endpoints page with `limit`/`offset` and wrap results in `{"data": [...],
    "count", "total", "links"}`. It signals more pages via a `links.next` URL; we fall back to
    the page-fill heuristic (a full page implies another may follow) when that field is absent.
    An empty page stops iteration.
    """

    def __init__(self, limit: int = PAGE_SIZE, offset: int = 0) -> None:
        super().__init__(
            limit=limit,
            offset=offset,
            offset_param="offset",
            limit_param="limit",
            # Termination is driven by links.next / page-fill below, not a body `total`.
            total_path=None,
            stop_after_empty_page=True,
        )

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) == 0:
            self._has_next_page = False
            return

        try:
            body = response.json()
            has_next_link = bool(body.get("links", {}).get("next")) if isinstance(body, dict) else False
        except (ValueError, AttributeError):
            has_next_link = False

        # More pages iff the API hands us a `next` link OR the page came back full.
        if not (has_next_link or len(data) >= self.limit):
            self._has_next_page = False
            return

        self.offset += self.limit
        self._has_next_page = True


def _normalize_group_member(item: dict[str, Any]) -> dict[str, Any]:
    # Membership rows carry no id of their own; lift the nested member id so it can key the row.
    return {**item, "member_id": item["member"]["id"]}


def _normalize_on_call(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "shift_id": item["shift"]["id"]}


def _normalize_user_delivery(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "person_id": item["person"]["id"]}


_FANOUT_ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "group_members": _normalize_group_member,
    "on_call": _normalize_on_call,
    "user_deliveries": _normalize_user_delivery,
}


def _historical_at(now: datetime) -> str:
    return (now - HISTORICAL_DATA_LAG).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_params(
    config: XmattersEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.supports_from:
        # `sort_by` is the timestamp `from` filters on — sorting ascending on it means new rows
        # append to the end and never shift pages we've already read. Sent on every sync so full
        # refreshes paginate over a stable ordering too.
        params["sortBy"] = config.sort_by
        params["sortOrder"] = "ASCENDING"
        if should_use_incremental_field and db_incremental_field_last_value:
            params["from"] = _format_incremental_value(db_incremental_field_last_value)

    return params


def validate_credentials(
    subdomain: str, username: str, password: str, endpoint: Optional[str] = None
) -> tuple[bool, int | None, str | None]:
    """Probe xMatters with a cheap single-row request.

    Returns ``(ok, status_code, error_message)``. ``status_code`` is ``None`` on transport failure.
    The caller decides how to treat 403 (valid credentials, missing permission for the probed
    endpoint).
    """
    config = XMATTERS_ENDPOINTS.get(endpoint) if endpoint else None
    if config and config.fanout:
        # A per-parent path needs a parent id, so probe the parent listing instead.
        config = XMATTERS_ENDPOINTS[config.fanout.parent_name]
    path = config.path if config else "/people"
    url = f"{_base_url(subdomain)}{path}?{urlencode({'limit': 1})}"

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(password,)),
        url,
        headers=_get_headers(username, password),
    )
    if ok:
        return True, status, None
    if status == 401:
        return False, status, "Invalid xMatters credentials"
    if status == 403:
        return False, status, "Your xMatters account does not have access to this resource"
    if status is None or status >= 500:
        return False, status, unreachable_vendor_message("xMatters")
    return False, status, f"xMatters API returned status {status}"


def _fanout_source(
    config: XmattersEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[XmattersResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None

    initial_paginator_state: Optional[dict[str, Any]] = None
    historical_at: Optional[str] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = resume.paginator_state
            historical_at = resume.historical_at

    if config.name == "user_deliveries" and historical_at is None:
        historical_at = _historical_at(datetime.now(UTC))
    child_params_extra = {"at": historical_at} if historical_at is not None else None

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(
                XmattersResumeConfig(paginator_state=dict(state), historical_at=historical_at)
            )

    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=XMATTERS_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            # The per-parent endpoints have no server-side time filter, so they are full refresh.
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": "data"},
            child_endpoint_extra={"data_selector": "data"},
            child_params_extra=child_params_extra,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ),
    )
    row_map = _FANOUT_ROW_MAPS.get(config.name)
    if row_map is not None:
        resource = resource.add_map(row_map)

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def xmatters_source(
    subdomain: str,
    username: str,
    password: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[XmattersResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = XMATTERS_ENDPOINTS[endpoint]
    client_config: ClientConfig = {
        "base_url": _base_url(subdomain),
        # Auth (HTTP Basic) is supplied via the framework auth config so the password is
        # redacted from logs and raised error messages; only non-secret headers go here.
        "headers": {"Accept": "application/json", "Content-Type": "application/json"},
        "auth": {"type": "http_basic", "username": username, "password": password},
        "paginator": XmattersPaginator(limit=PAGE_SIZE),
    }

    if config.fanout is not None:
        return _fanout_source(config, client_config, team_id, job_id, resumable_source_manager)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _build_params(config, should_use_incremental_field, db_incremental_field_last_value),
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(XmattersResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # We request an ascending `sort_by` where a sort is available, and full-refresh endpoints
        # replace wholesale, so ascending is correct everywhere.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
