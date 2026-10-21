import re
import dataclasses
from datetime import date, datetime
from typing import Any, Optional

from requests import Request
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import (
    PAGE_SIZE,
    PICQER_ENDPOINTS,
    PicqerEndpointConfig,
)

PICQER_API_PATH = "/api/v1"

# Picqer requires a descriptive User-Agent identifying the application plus contact info.
PICQER_USER_AGENT = "PostHog (https://posthog.com - hey@posthog.com)"

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots) so the stored API key is only ever sent to `<account>.picqer.com`.
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclasses.dataclass(frozen=True)
class PicqerResumeConfig:
    # Next offset to fetch. None means "start from offset 0".
    offset: int | None = None
    # Framework fan-out resume state for fan-out endpoints:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {"offset": ...} | None}.
    fanout_state: dict | None = None


class PicqerOffsetPaginator(OffsetPaginator):
    """Picqer paginates purely by `offset`; its page size is fixed server-side at 100 with no
    `limit`/`per_page` override, so — unlike the built-in OffsetPaginator — we must never emit a
    limit query param. `limit` is still used internally to detect the short final page and stop."""

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.offset_param] = self.offset

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.offset_param] = self.offset


def normalize_account(account: str) -> str:
    """Reduce user input to a bare, validated Picqer account subdomain.

    Accepts either the full host (``yourcompany.picqer.com``) or the bare subdomain
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    API key can never be retargeted away from ``<account>.picqer.com``.
    """
    cleaned = account.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".picqer.com")
    if not _ACCOUNT_RE.match(cleaned):
        raise ValueError(
            f"Invalid Picqer account: {account!r}. Enter just your account name, e.g. 'yourcompany' "
            "for yourcompany.picqer.com."
        )
    return cleaned


def _base_url(account: str) -> str:
    return f"https://{normalize_account(account)}.picqer.com{PICQER_API_PATH}"


def to_picqer_datetime(value: Any) -> str:
    """Format an incremental cursor value into Picqer's ``YYYY-MM-DD HH:MM:SS`` filter format.

    The persisted last value arrives as a ``datetime`` for DateTime incremental fields. Picqer's
    timestamps carry no timezone, so we format the wall-clock components directly (no timezone
    shift) to round-trip against the same values the API returned.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S")
    # Defensive: an ISO string ("2013-07-17T16:01:42") reduced to Picqer's space-separated form.
    return str(value).replace("T", " ")[:19]


def _build_params(
    config: PicqerEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Query params kept on every offset page. Picqer applies a filter server-side across the whole
    result set, so the `updated_after` cursor narrows every page and pagination ends naturally. Only
    endpoints with a genuine update-based filter are ever narrowed — full-refresh endpoints must
    never leak a cursor into the request."""
    params: dict[str, Any] = {}
    if (
        config.supports_incremental
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
        and config.incremental_filter_param is not None
    ):
        params[config.incremental_filter_param] = to_picqer_datetime(db_incremental_field_last_value)
    return params


def flatten_warehouse_stock_row(row: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested per-warehouse `stock` object to the row root.

    Picqer returns `{"idproduct", "productcode", "stock": {"idwarehouse", "stock", ...}}`, so the
    `idwarehouse` half of the primary key only exists inside the nested object. The parent
    warehouse id injected by the fan-out is the fallback when the nested object omits it.
    """
    parent_idwarehouse = row.pop("_warehouses_idwarehouse", None)
    stock = row.pop("stock", None)
    if isinstance(stock, dict):
        row.update(stock)
    if row.get("idwarehouse") is None:
        row["idwarehouse"] = parent_idwarehouse
    return row


_ROW_MAPPERS = {"warehouse_stock": flatten_warehouse_stock_row}


def _resources(config: PicqerEndpointConfig, params: dict[str, Any]) -> list[str | EndpointResource]:
    endpoint: Endpoint = {"path": config.path, "params": params}
    if not config.paginated:
        endpoint["paginator"] = "single_page"
    resource: EndpointResource = {"name": config.name, "endpoint": endpoint}
    if config.name in _ROW_MAPPERS:
        resource["data_map"] = _ROW_MAPPERS[config.name]

    fanout = config.fanout
    if fanout is None:
        return [resource]

    parent = PICQER_ENDPOINTS[fanout.parent_name]
    endpoint["params"] = {
        **params,
        fanout.resolve_field: {"type": "resolve", "resource": parent.name, "field": fanout.resolve_field},
    }
    # A parent deleted between the parent listing and the child fetch 404s; skip it.
    endpoint["response_actions"] = [{"status_code": 404, "action": "ignore"}]
    resource["include_from_parent"] = [fanout.resolve_field]
    return [{"name": parent.name, "endpoint": {"path": parent.path, "params": {}}}, resource]


def picqer_source(
    account: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PicqerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PICQER_ENDPOINTS[endpoint]

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(account),
            # Non-secret headers only; the API key travels via HTTP Basic auth (below), whose base64
            # Authorization header is redacted by the tracked session's header denylist.
            "headers": {"User-Agent": PICQER_USER_AGENT, "Accept": "application/json"},
            # Picqer authenticates with the API key as the HTTP Basic username and a blank password.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            # Fixed page size of 100, offset-only advancement; termination is a short/empty page.
            "paginator": PicqerOffsetPaginator(limit=PAGE_SIZE, total_path=None),
            # Pin every request (including any resume URL) to `<account>.picqer.com` so the stored
            # API key can never be sent off-host.
            "allowed_hosts": [],
        },
        "resource_defaults": {},
        "resources": _resources(config, params),
    }

    is_fanout = config.fanout is not None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if is_fanout:
                initial_paginator_state = resume.fanout_state or None
            elif resume.offset is not None:
                initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if is_fanout:
            resumable_source_manager.save_state(PicqerResumeConfig(fanout_state=state))
        elif state and state.get("offset") is not None:
            resumable_source_manager.save_state(PicqerResumeConfig(offset=int(state["offset"])))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(account: str, api_key: str) -> tuple[bool, int | None]:
    """Probe a cheap Picqer list endpoint to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the account is malformed so the caller can surface a precise message. A
    ``403`` (valid key, insufficient scope) is treated as reachable — fulfilment keys legitimately
    have narrow scopes and per-table access is reported separately.
    """
    # `_base_url` normalizes (and validates) the account before the probe; a malformed account
    # raises ValueError here so the caller can surface a precise message.
    url = f"{_base_url(account)}/warehouses?offset=0"
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"User-Agent": PICQER_USER_AGENT, "Accept": "application/json"},
        auth=HTTPBasicAuth(api_key, ""),
        ok_statuses=(200, 403),
        timeout=10.0,
    )
