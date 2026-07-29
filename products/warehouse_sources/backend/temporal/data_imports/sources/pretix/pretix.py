"""pretix transport layer.

pretix is an open-source event-ticketing platform offered both as the hosted SaaS
(``https://pretix.eu``) and self-hosted (a customer-supplied host), so the API base URL must be
configurable. Auth is a team-level API token in an ``Authorization: Token <token>`` header; a token
is scoped to a single organizer, and every resource lives under
``/api/v1/organizers/{organizer}/...``.

List endpoints are page-number paginated with a ``count``/``next``/``previous``/``results``
envelope where ``next`` is the full URL of the following page. Orders and invoices use the
organizer-level list endpoints spanning all events; the remaining event-scoped resources fan out
over the organizer's events.

Only ``orders`` documents a server-side timestamp filter (``modified_since``) together with a
``last_modified`` ordering key, so it is the only incremental stream. Everything else is full
refresh — pretix's other list endpoints only support ``If-Modified-Since`` conditional fetching
(all-or-nothing 304s), which is not a per-row cursor.

Built on the shared ``rest_source`` framework: a ``JSONResponsePaginator`` follows the ``next``
link, framework ``api_key`` auth carries the token (and redacts it from errors/logs), ``allowed_hosts``
pins every page/resume URL to the configured host, and ``allow_redirects=False`` rejects 3xx — the
SSRF guards the hand-rolled transport enforced by hand. Event-scoped resources are single-hop
dependent resources fanning out from the organizer's events list.
"""

import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlparse

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.settings import (
    EVENT_SLUG_KEY,
    EVENTS_PATH,
    PRETIX_ENDPOINTS,
    EndpointScope,
    PretixEndpointConfig,
)

DEFAULT_API_HOST = "https://pretix.eu"
API_VERSION_PATH = "/api/v1"

HOST_NOT_ALLOWED_ERROR = "pretix API URL is not allowed"
HTTP_NOT_ALLOWED_ERROR = "pretix API URL must use HTTPS"
INVALID_ORGANIZER_ERROR = "Invalid pretix organizer short name"

# The parent event slug, percent-encoded, stashed on each event row so the child fan-out URL quotes
# the slug exactly like the hand-rolled ``quote(slug, safe="")`` did — while the raw slug is stamped
# into child rows unchanged (see ``EVENT_SLUG_KEY``).
_EVENT_SLUG_ENCODED_KEY = "event_slug_encoded"
# ``include_from_parent=["slug"]`` copies the parent's raw slug under this framework-derived name.
_PARENT_SLUG_KEY = "_events_slug"


class PretixHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class PretixResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the API's ``next`` link (query params,
    # including any ``modified_since`` filter, are baked into it). Persisted for organizer-level
    # (simple) endpoints.
    next_url: str | None = None
    # Framework dependent-resource checkpoint for event fan-out endpoints (``{"completed": [...],
    # "current": ..., "child_state": ...}``). Defaults to None so an old ``{"next_url": ...}`` state
    # still parses after this change.
    fanout_state: Optional[dict[str, Any]] = None


def normalize_base_url(base_url: Optional[str]) -> str:
    """Turn whatever the user typed into a ``<scheme>://<host>/api/v1`` base URL.

    Blank → the hosted pretix SaaS. Accepts bare hosts (``tickets.example.com``), full URLs with or
    without a scheme, and values that already include the ``/api/v1`` suffix.
    """
    raw = (base_url or "").strip()
    if not raw:
        raw = DEFAULT_API_HOST
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    # Drop a trailing version segment the user may have pasted in, then re-add the version we target.
    raw = re.sub(r"/api/v\d+$", "", raw)
    return f"{raw}{API_VERSION_PATH}"


def _host_of(base_url: str) -> str:
    # `urlparse` treats a backslash (and its `%5c` encoding) as userinfo, so
    # `https://127.0.0.1\@example.com` parses as host `example.com` while requests/urllib3 (per the
    # WHATWG URL rules) treat `\` as a path separator and connect to `127.0.0.1`. Normalize to `/`
    # first so the host we validate is the host the request actually reaches (SSRF bypass guard).
    normalized = base_url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
    return (urlparse(normalized).hostname or "").lower()


def _is_https(base_url: str) -> bool:
    # The API token rides in the Authorization header, so refuse plaintext HTTP to keep an on-path
    # attacker from capturing it.
    return urlparse(base_url).scheme == "https"


def _quote_organizer(organizer: str) -> str:
    """URL-quote the organizer slug so it can't inject path segments into request URLs."""
    cleaned = organizer.strip().strip("/")
    if not cleaned:
        raise ValueError(INVALID_ORGANIZER_ERROR)
    return quote(cleaned, safe="")


def _get_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Token {api_token}", "Accept": "application/json"}


def _format_modified_since(value: Any) -> str:
    """Format an incremental value for pretix's ``modified_since`` filter (ISO 8601 UTC, Z suffix)."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _check_host(base_url: str, team_id: int) -> None:
    """Raise unless the (customer-controlled, possibly self-hosted) base URL is safe to call."""
    host = _host_of(base_url)
    host_ok, host_err = _is_host_safe(host, team_id)
    if not host_ok:
        raise PretixHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
    if not _is_https(base_url):
        raise PretixHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)


def _client_config(api_token: str, base_url: str) -> ClientConfig:
    # Auth is supplied via the framework `api_key` config (header `Authorization: Token <token>`) so
    # the value is redacted from logs and raised error messages; only the non-secret Accept header is
    # set on the client. `allowed_hosts=[]` pins every page/resume URL to the base host (the base host
    # is always implicitly allowed), and `allow_redirects=False` rejects 3xx — a tampered `next` link
    # or a redirect can't hand the token to another origin.
    return {
        "base_url": base_url,
        "auth": {
            "type": "api_key",
            "api_key": f"Token {api_token}",
            "name": "Authorization",
            "location": "header",
        },
        "headers": {"Accept": "application/json"},
        "paginator": JSONResponsePaginator(next_url_path="next"),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _modified_since_incremental() -> IncrementalConfig:
    return {
        "cursor_path": "last_modified",
        "start_param": "modified_since",
        "convert": _format_modified_since,
    }


def _should_apply_incremental(
    config: PretixEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> bool:
    # Mirror the hand-rolled gate: only narrow with the server-side `modified_since` filter when the
    # endpoint supports it and the user's chosen cursor is the field that filter targets
    # (`last_modified`). Honors the selected incremental_field rather than assuming it.
    return (
        should_use_incremental_field
        and config.modified_since_field is not None
        and db_incremental_field_last_value is not None
        and incremental_field in (None, config.modified_since_field)
    )


def _encode_event_slug(row: dict[str, Any]) -> dict[str, Any]:
    # Percent-encode the slug for the child fan-out path (matches the old `quote(slug, safe="")`),
    # keeping the raw `slug` for the row stamp. Fail fast on a malformed event with no slug.
    row[_EVENT_SLUG_ENCODED_KEY] = quote(str(row["slug"]), safe="")
    return row


def _stamp_event_slug(row: dict[str, Any]) -> dict[str, Any]:
    # `include_from_parent=["slug"]` copies the raw parent slug under `_events_slug`; rename it to the
    # stable `event_slug` column so composite primary keys (event_slug, id) stay table-wide unique.
    row[EVENT_SLUG_KEY] = row.pop(_PARENT_SLUG_KEY)
    return row


def pretix_source(
    api_token: str,
    organizer: str,
    base_url: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PretixResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config: PretixEndpointConfig = PRETIX_ENDPOINTS[endpoint]
    resolved_base_url = normalize_base_url(base_url)
    # Re-check at run time (not just at source-create) in case the URL was edited or now resolves to
    # an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    _check_host(resolved_base_url, team_id)
    quoted_organizer = _quote_organizer(organizer)

    incremental: Optional[IncrementalConfig] = None
    if _should_apply_incremental(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    ):
        incremental = _modified_since_incremental()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None:
        if resume.fanout_state:
            initial_paginator_state = resume.fanout_state
        elif resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-fetches the last page (merge dedupes on PK).
        if not state:
            return
        if "next_url" in state:
            if state.get("next_url"):
                resumable_source_manager.save_state(PretixResumeConfig(next_url=state["next_url"]))
        else:
            resumable_source_manager.save_state(PretixResumeConfig(fanout_state=state))

    client = _client_config(api_token, resolved_base_url)
    # An explicit stable sort keeps page boundaries deterministic, and for `orders` makes the response
    # order match `sort_mode="asc"` so the incremental watermark advances correctly.
    static_params: dict[str, Any] = {"ordering": config.ordering} if config.ordering else {}

    resource: Resource
    if config.scope == EndpointScope.ORGANIZER:
        organizer_endpoint: Endpoint = {
            "path": config.path.format(organizer=quoted_organizer),
            "data_selector": "results",
            # An unexpected 200 body shape (not the `{results: [...]}` envelope) is treated as
            # transient and reissued, as the hand-rolled fetch did.
            "data_selector_malformed_retryable": True,
        }
        if static_params:
            organizer_endpoint["params"] = static_params
        if incremental is not None:
            organizer_endpoint["incremental"] = incremental

        rest_config: RESTAPIConfig = {
            "client": client,
            "resources": [{"name": endpoint, "endpoint": organizer_endpoint}],
        }
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
    else:
        # Event fan-out: discover the organizer's events, then paginate the child endpoint per event,
        # stamping each row with its parent event slug (single-hop dependent resource, resume enabled).
        events_endpoint: Endpoint = {
            "path": EVENTS_PATH.format(organizer=quoted_organizer),
            "data_selector": "results",
            "data_selector_malformed_retryable": True,
        }
        events_resource: EndpointResource = {
            "name": "events",
            "endpoint": events_endpoint,
            "data_map": _encode_event_slug,
        }

        leaf_endpoint: Endpoint = {
            "path": config.path.format(organizer=quoted_organizer, event="{event}"),
            "data_selector": "results",
            "params": {
                "event": {"type": "resolve", "resource": "events", "field": _EVENT_SLUG_ENCODED_KEY},
                **static_params,
            },
        }
        leaf_resource: EndpointResource = {
            "name": endpoint,
            "endpoint": leaf_endpoint,
            "include_from_parent": ["slug"],
            "data_map": _stamp_event_slug,
        }

        rest_config = {"client": client, "resources": [events_resource, leaf_resource]}
        built = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        resource = next(r for r in built if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(
    api_token: str, organizer: str, base_url: Optional[str], team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe the organizer's events list to confirm the token is genuine and scoped correctly.

    pretix team tokens carry per-resource permissions, so a single cheap probe only asserts the
    token + organizer pair is valid — per-endpoint 403s at sync time surface through
    ``get_non_retryable_errors``.
    """
    resolved_base_url = normalize_base_url(base_url)

    try:
        quoted_organizer = _quote_organizer(organizer)
    except ValueError:
        return False, INVALID_ORGANIZER_ERROR

    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_of(resolved_base_url), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR
    if not _is_https(resolved_base_url):
        return False, HTTP_NOT_ALLOWED_ERROR

    url = f"{resolved_base_url}{EVENTS_PATH.format(organizer=quoted_organizer)}?page_size=1"
    # allow_redirects=False so a 3xx surfaces as its own status rather than being followed off-host.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,), allow_redirects=False),
        url,
        headers=_get_headers(api_token),
    )

    if status is None:
        return False, "Could not connect to pretix"
    if status == 200:
        return True, None
    if 300 <= status < 400:
        return False, HOST_NOT_ALLOWED_ERROR
    if status == 401:
        return False, "Invalid pretix API token"
    if status == 403:
        # pretix returns 403 both for an unknown organizer and for a token without access to it.
        return False, (
            "Your pretix API token does not have access to this organizer. "
            "Check the organizer short name and the token's team permissions."
        )
    return False, f"pretix returned HTTP {status}"
