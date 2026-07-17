import hashlib
import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.settings import (
    DENO_DEPLOY_ENDPOINTS,
    DenoDeployEndpointConfig,
)

DENO_DEPLOY_HOST = "api.deno.com"
DENO_DEPLOY_BASE_URL = f"https://{DENO_DEPLOY_HOST}"

# Default page size for the cursor-paginated list endpoints (API default is 30, max 100).
DEFAULT_LIST_PAGE_SIZE = 100

# Name of the parent resource every fan-out endpoint hangs off. Its id/slug are carried into each
# child row via include_from_parent, which the framework surfaces as `_apps_id` / `_apps_slug`.
_APPS_RESOURCE = "apps"
_PARENT_ID_KEY = f"_{_APPS_RESOURCE}_id"
_PARENT_SLUG_KEY = f"_{_APPS_RESOURCE}_slug"


@dataclasses.dataclass
class DenoDeployResumeConfig:
    # Full URL of the next page to fetch, for the top-level (non-fan-out) list endpoints. This is the
    # legacy field name; a saved state written before the rest_source migration still parses here.
    next_url: str | None = None
    # Legacy fan-out bookmark (stable app id). Retained so old saved state parses; the rest_source
    # fan-out now checkpoints under `fanout_state` instead, and a state carrying only this restarts
    # the fan-out from scratch (the merge dedupes the re-pulled rows).
    app_id: str | None = None
    # rest_source fan-out resume snapshot: {"completed": [child_path, ...], "current": child_path |
    # None, "child_state": {...} | None}. Skips fully-synced apps and resumes the in-progress one.
    fanout_state: dict[str, Any] | None = None


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs; only
    # the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _format_rfc3339(dt: datetime) -> str:
    """Format a datetime as RFC 3339 / ISO 8601 with a `Z` suffix, which Deno Deploy's time filters
    accept. isoformat() emits `+00:00`; we normalize to `Z` to match the API's documented examples."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _as_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return None


def _time_window_params(
    config: DenoDeployEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> tuple[str, str]:
    """Resolve the [start, end] window for the time-ranged endpoints (logs, analytics).

    `end` is always `now` — never omitted, since the logs endpoint switches to real-time streaming
    without it. `start` is the incremental watermark (minus a small lookback for boundary/clock-skew
    slack, clamped to never exceed now) or, on the first sync / full refresh, `now - default_lookback`.
    Because each run fetches every app up to `now`, consecutive windows overlap and leave no gap."""
    now = datetime.now(UTC)
    last = _as_utc_datetime(db_incremental_field_last_value) if should_use_incremental_field else None
    if last is not None:
        start = min(last, now)
        if config.incremental_lookback:
            start = start - config.incremental_lookback
    else:
        start = now - timedelta(days=config.default_lookback_days or 7)
    return _format_rfc3339(start), _format_rfc3339(now)


def _log_row_id(app_id: str, log: dict[str, Any]) -> str:
    """Runtime log lines carry no natural id, so synthesize a stable content hash. Merging on it makes
    re-pulling the overlapping boundary window idempotent (identical lines collapse to one row). Two
    genuinely distinct lines identical across every field would also collapse — an accepted, rare loss
    for a source without log ids."""
    parts = [
        app_id,
        str(log.get("timestamp", "")),
        str(log.get("level", "")),
        str(log.get("message", "")),
        str(log.get("revision_id", "")),
        str(log.get("region", "")),
        str(log.get("trace_id", "")),
        str(log.get("span_id", "")),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _reshape_analytics(body: dict[str, Any], app_id: str, app_slug: str) -> list[dict[str, Any]]:
    """Deno returns analytics as a columnar {fields: [{name}], values: [[...], ...]} payload. Reshape
    it into one dict per time bucket keyed by field name (the docs say to map by name, not position)."""
    field_names = [f["name"] for f in body.get("fields", [])]
    rows: list[dict[str, Any]] = []
    for value_row in body.get("values", []):
        row: dict[str, Any] = dict(zip(field_names, value_row))
        row["app_id"] = app_id
        row["app_slug"] = app_slug
        rows.append(row)
    return rows


def _ensure_parent_slug(app: dict[str, Any]) -> dict[str, Any]:
    # The fan-out carries the parent slug into every child row; default it so an app without a slug
    # doesn't fail the include_from_parent lookup (the hand-rolled source used app.get("slug", "")).
    app.setdefault("slug", "")
    return app


def _list_child_map(row: dict[str, Any]) -> dict[str, Any]:
    # Rename the framework's include_from_parent keys back to the flat app_id / app_slug the child
    # rows carried before the migration.
    row["app_id"] = row.pop(_PARENT_ID_KEY)
    row["app_slug"] = row.pop(_PARENT_SLUG_KEY)
    return row


def _logs_child_map(row: dict[str, Any]) -> dict[str, Any]:
    app_id = row.pop(_PARENT_ID_KEY)
    app_slug = row.pop(_PARENT_SLUG_KEY)
    # `row` still holds only the raw log fields, so the content hash matches the pre-migration id.
    row_id = _log_row_id(app_id, row)
    row["app_id"] = app_id
    row["app_slug"] = app_slug
    row["id"] = row_id
    return row


def _analytics_child_map(body: dict[str, Any]) -> list[dict[str, Any]]:
    app_id = body.pop(_PARENT_ID_KEY)
    app_slug = body.pop(_PARENT_SLUG_KEY)
    return _reshape_analytics(body, app_id, app_slug)


def _apps_parent_resource() -> EndpointResource:
    # Parent list driving the fan-out. A separate dict per call — config setup mutates it.
    return {
        "name": _APPS_RESOURCE,
        "endpoint": {
            "path": "/v2/apps",
            "params": {"limit": DEFAULT_LIST_PAGE_SIZE},
            "paginator": HeaderLinkPaginator(),
        },
        "data_map": _ensure_parent_slug,
    }


def _resource_chain(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> list[EndpointResource]:
    config = DENO_DEPLOY_ENDPOINTS[endpoint]

    if not config.fan_out_over_apps:
        # Top-level cursor-paginated list (apps, domains): a plain Link-header list, rows used as-is.
        return [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": config.page_size or DEFAULT_LIST_PAGE_SIZE},
                    "paginator": HeaderLinkPaginator(),
                },
            }
        ]

    resolve_app = {"type": "resolve", "resource": _APPS_RESOURCE, "field": "id"}

    if config.kind == "logs":
        start, end = _time_window_params(config, should_use_incremental_field, db_incremental_field_last_value)
        child: EndpointResource = {
            "name": endpoint,
            "endpoint": {
                "path": config.path,
                "params": {
                    "app": resolve_app,
                    "start": start,
                    "end": end,
                    "limit": config.page_size or 1000,
                },
                "data_selector": "logs",
                # Cursor lives in the body (`next_cursor`); echo it as `cursor`, preserving start/end/limit.
                "paginator": JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor"),
            },
            "include_from_parent": ["id", "slug"],
            "data_map": _logs_child_map,
        }
    elif config.kind == "analytics":
        since, until = _time_window_params(config, should_use_incremental_field, db_incremental_field_last_value)
        child = {
            "name": endpoint,
            "endpoint": {
                "path": config.path,
                "params": {"app": resolve_app, "since": since, "until": until},
                # No data_selector: the columnar {fields, values} body is one item the data_map explodes.
                "paginator": SinglePagePaginator(),
            },
            "include_from_parent": ["id", "slug"],
            "data_map": _analytics_child_map,
        }
    else:
        # Plain fan-out list child (revisions): inject the parent app context the child response omits.
        child = {
            "name": endpoint,
            "endpoint": {
                "path": config.path,
                "params": {"app": resolve_app, "limit": config.page_size or DEFAULT_LIST_PAGE_SIZE},
                "paginator": HeaderLinkPaginator(),
            },
            "include_from_parent": ["id", "slug"],
            "data_map": _list_child_map,
        }

    return [_apps_parent_resource(), child]


def deno_deploy_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DenoDeployResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DENO_DEPLOY_ENDPOINTS[endpoint]
    is_fan_out = config.fan_out_over_apps

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": DENO_DEPLOY_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "bearer", "token": access_token},
            # SSRF host-pinning: every request URL — including Link-header continuations and seeded
            # resume URLs — must resolve to api.deno.com before the bearer token leaves the process,
            # and redirects are rejected so a 3xx can't bounce the token to another origin.
            "allowed_hosts": [DENO_DEPLOY_HOST],
            "allow_redirects": False,
        },
        "resources": _resource_chain(endpoint, should_use_incremental_field, db_incremental_field_last_value),
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if is_fan_out:
                initial_paginator_state = resume.fanout_state
            elif resume.next_url:
                initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state is None:
            return
        if is_fan_out:
            resumable_source_manager.save_state(DenoDeployResumeConfig(fanout_state=state))
        elif state.get("next_url"):
            resumable_source_manager.save_state(DenoDeployResumeConfig(next_url=state["next_url"]))

    # The time window is baked into the endpoint params above, so the framework's incremental param
    # injection is unused — pass a None watermark to keep it out of the request.
    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Every endpoint emits ascending by its partition/incremental field: the list endpoints are
        # full-refresh (order only needs to be stable), and the time-windowed endpoints (logs,
        # analytics) return oldest-first within the [start, end] window, matching the watermark's
        # forward advance.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    """Confirm the org access token is genuine with one cheap probe against the apps list."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,), allow_redirects=False),
        f"{DENO_DEPLOY_BASE_URL}/v2/apps?limit=1",
        headers={"Authorization": f"Bearer {access_token}", **_headers()},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Deno Deploy access token. Create a new organization access token and reconnect."
    if status == 403:
        return False, "Your Deno Deploy access token does not have permission to read this organization's data."
    if status is None:
        return False, "Could not reach the Deno Deploy API. Check your connection and try again."
    return False, f"Deno Deploy API returned an unexpected status ({status})."
