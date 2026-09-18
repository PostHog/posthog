import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, Optional

from requests import Request, Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ANALYTICS_DATA_FLOOR,
    ANALYTICS_PATH_PREFIX,
    ANTHROPIC_ENDPOINTS,
    ENDPOINT_RETIRED_ERROR,
    RBAC_GROUPS_PATH,
    RBAC_ROLES_PATH,
    USAGE_GROUP_BY_FALLBACKS,
    AnalyticsWindowKind,
    AnthropicEndpointConfig,
    FanOutConfig,
    PaginationType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ApiKeyAuthConfig,
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
# Entity list endpoints allow up to 1000 per page.
ENTITY_PAGE_SIZE = 1000
# Attempts per request for the entity list endpoints (users, workspaces, api_keys, ...). They are
# not organization-rate-limited, so a modest budget above the client default is enough to ride out
# a transient blip without letting a genuinely broken endpoint retry for long.
MAX_RETRY_ATTEMPTS = 8
# The usage/cost/analytics report endpoints share one organization-level rate limit on Anthropic's
# Admin API, which answers 429 with no `Retry-After`. The `anthropic-ratelimit-requests-reset`
# instant is often already stale when we read it, so the client falls back to exponential backoff.
# A per-minute limit needs a budget that outlasts the window, so give the report endpoints more
# attempts and a higher backoff ceiling than the entity lists — each wait still stays capped, so a
# sync never stalls indefinitely.
REPORT_MAX_RETRY_ATTEMPTS = 12
REPORT_RETRY_BACKOFF_MAX_SECONDS = 300.0
# Floor for the required `starting_at` on a full refresh. Anthropic launched in 2023, so no usage or
# cost data can predate this — starting here rather than the epoch avoids requesting decades of empty
# buckets while still pulling all available history.
DEFAULT_STARTING_AT = datetime(2023, 1, 1, tzinfo=UTC)
# Floor for the day-by-day fan-out of the Claude Code analytics endpoint (one required `starting_at`
# day per request). Claude Code became available in 2025, so earlier days only return empty pages —
# starting here avoids fanning out over hundreds of pre-launch days on a full refresh.
DEFAULT_CLAUDE_CODE_START = date(2025, 1, 1)
# Shown against the Claude Enterprise Analytics tables in the schema picker when the configured key
# cannot reach them, so the customer deselects those tables instead of watching them fail to sync.
ANALYTICS_ACCESS_MISSING = (
    "This table comes from the Claude Enterprise Analytics API, which this key can't reach. It needs "
    "a Claude Enterprise key with the read:analytics scope, created in claude.ai organization "
    "settings by your primary owner."
)
# Shown against the Claude Enterprise group and custom role tables in the schema picker when the
# configured key cannot reach them. The two families take different scopes, so they get their own
# probes and their own messages.
RBAC_GROUP_ACCESS_MISSING = (
    "This table comes from the Claude Enterprise user management API, which this key can't reach. It "
    "needs an Admin API key with the read:rbac_groups scope, created in claude.ai organization "
    "settings for all your linked organizations."
)
RBAC_ROLE_ACCESS_MISSING = (
    "This table comes from the Claude Enterprise user management API, which this key can't reach. It "
    "needs an Admin API key with the read:members scope, created in claude.ai organization settings."
)


@frozen
class AnthropicResumeConfig:
    # Opaque pagination cursor: an `after_id` for CURSOR endpoints or a `next_page` token for PAGE
    # endpoints. None means "start at the first page".
    cursor: str | None = None
    # Legacy workspace_members resume field (pre-framework): the workspace whose members we were
    # paging when we saved state. Kept so previously-saved state still parses; the framework's
    # fan-out checkpoint below supersedes it, and an old-shape state restarts the fan-out fresh.
    workspace_id: str | None = None
    # workspace_members fan-out checkpoint from the framework:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict | None = None
    # Claude Code day fan-out checkpoint: {"date": "YYYY-MM-DD", "cursor": next_page | None}.
    day_fanout_state: dict | None = None
    # Claude Enterprise Analytics day fan-out checkpoint: {"start": "YYYY-MM-DD"}, the first day not
    # yet fully yielded. The within-day page cursor is deliberately not saved: it is bound to the
    # query that minted it and expires when the underlying export refreshes, so replaying a whole
    # day costs one extra request set and can never hand the API a cursor it has since rejected.
    analytics_window_state: dict | None = None


class AnthropicCursorPaginator(BasePaginator):
    """Token-plus-flag pagination shared by every Anthropic endpoint.

    Entity lists page with `after_id` and echo `last_id`; the report endpoints page with `page` and
    echo `next_page`. Both signal continuation via `has_more`. The built-in cursor paginator stops
    only on a missing token, but the entity endpoints return `last_id` on the final page too —
    `has_more` is the authoritative stop signal, so both are honored here.
    """

    def __init__(self, cursor_path: str, cursor_param: str) -> None:
        super().__init__()
        self.cursor_path = cursor_path
        self.cursor_param = cursor_param
        self._cursor_value: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request.
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            self._has_next_page = False
            return
        token = body.get(self.cursor_path)
        # `/organizations/analytics/users` omits `has_more` and marks its last page with a null
        # `next_page`. Every other endpoint sends both, and there `has_more` stays authoritative
        # because the entity lists echo `last_id` on the final page too.
        has_more = body.get("has_more", token is not None)
        if has_more and token:
            self._cursor_value = token
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"AnthropicCursorPaginator(cursor_path={self.cursor_path}, cursor_param={self.cursor_param})"


class ClaudeCodeDayPaginator(BasePaginator):
    """Day-by-day fan-out for the Claude Code analytics endpoint.

    The endpoint windows on a single required `starting_at` day (not a range) and page-cursors within
    that day via `page`/`next_page`+`has_more`. This paginator walks each day's pages, then advances
    `starting_at` to the next day, stopping once it passes today — so the whole history is one resource
    driven entirely by the paginator (there is no parent API resource to resolve days from).
    """

    def __init__(self, start_day: date, today: date) -> None:
        super().__init__()
        # Never request a future day: if the watermark is at/after today, re-pull today only.
        self._current_day = min(start_day, today)
        self._today = today
        self._page: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["starting_at"] = self._current_day.isoformat()
        if self._page is not None:
            request.params["page"] = self._page
        else:
            request.params.pop("page", None)

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        next_page = body.get("next_page") if isinstance(body, dict) else None
        has_more = bool(body.get("has_more")) if isinstance(body, dict) else False
        if has_more and next_page and data:
            # More pages within the current day.
            self._page = next_page
            self._has_next_page = True
            return
        # Day exhausted — advance to the next day, or stop once we pass today.
        self._current_day = self._current_day + timedelta(days=1)
        self._page = None
        self._has_next_page = self._current_day <= self._today

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._has_next_page:
            return None
        return {"date": self._current_day.isoformat(), "cursor": self._page}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        saved_date = state.get("date")
        if saved_date:
            self._current_day = _parse_iso_date(str(saved_date))
            self._page = state.get("cursor")
            self._has_next_page = True

    def __str__(self) -> str:
        return f"ClaudeCodeDayPaginator(current_day={self._current_day}, today={self._today})"


def _version_headers() -> dict[str, str]:
    # Auth (x-api-key) is supplied via the framework auth config so its value is redacted from
    # logs; only the non-secret version/accept headers are set here.
    return {"anthropic-version": ANTHROPIC_VERSION, "accept": "application/json"}


def _auth_config(api_key: str) -> ApiKeyAuthConfig:
    return {"type": "api_key", "name": "x-api-key", "api_key": api_key, "location": "header"}


def _format_rfc3339(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC timestamp with a Z suffix (Anthropic's format)."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe against the smallest list endpoint confirms the admin key is genuine.
    # 200 => valid. 403 => valid key without a scope we probed here; still a real key, so accept it
    # at create time (sync-time 403s are caught by get_non_retryable_errors). 401 => bad key.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ANTHROPIC_BASE_URL}/v1/organizations/users?limit=1",
        headers={"x-api-key": api_key, **_version_headers()},
        ok_statuses=(200, 403),
    )
    return ok


def _check_path_access(api_key: str, path: str, missing_reason: str) -> Optional[str]:
    """Report whether the configured key can read a path that needs access beyond the Admin API key.

    Returns None when it can, or the reason to show against the tables that need it. Only a real
    denial counts as missing access: a throttle, a server error, or a network failure leaves those
    tables reported as reachable, so a blip during schema discovery never hides a table the customer
    can sync. A 401 is left to `validate_credentials`, which reports a bad key for the whole source.
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ANTHROPIC_BASE_URL}{path}",
        headers={"x-api-key": api_key, **_version_headers()},
    )
    # 404 as well as 403: an organization that is not on a Claude Enterprise plan does not serve
    # these routes at all.
    if status in (403, 404):
        return missing_reason
    return None


def check_analytics_access(api_key: str) -> Optional[str]:
    return _check_path_access(api_key, f"{ANALYTICS_PATH_PREFIX}users?limit=1", ANALYTICS_ACCESS_MISSING)


def check_rbac_group_access(api_key: str) -> Optional[str]:
    return _check_path_access(api_key, f"{RBAC_GROUPS_PATH}?limit=1", RBAC_GROUP_ACCESS_MISSING)


def check_rbac_role_access(api_key: str) -> Optional[str]:
    # The custom role reads take their own scope, so a key that reaches the group tables can still
    # be denied here.
    return _check_path_access(api_key, f"{RBAC_ROLES_PATH}?limit=1", RBAC_ROLE_ACCESS_MISSING)


def _flatten_created_by(item: dict[str, Any]) -> dict[str, Any]:
    """api_keys carry a nested `created_by: {id, type}`; surface it as flat columns."""
    created_by = item.get("created_by")
    if isinstance(created_by, dict):
        item = {**item}
        item.pop("created_by")
        item["created_by_id"] = created_by.get("id")
        item["created_by_type"] = created_by.get("type")
    return item


def _row_id(*parts: Any) -> str:
    """Deterministic surrogate id for a report row.

    Hashes only the identity/dimension fields (never the metric values), so a bucket whose metrics
    get restated between runs keeps the same id and merge updates it in place rather than inserting a
    duplicate.
    """
    # Use a sentinel for None so a missing dimension can never collide with an empty-string value.
    joined = "|".join("\x00" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def _flatten_usage_result(bucket: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    starting_at = bucket.get("starting_at")
    cache_creation = result.get("cache_creation") or {}
    server_tool_use = result.get("server_tool_use") or {}
    row = {
        "id": _row_id(
            starting_at,
            result.get("account_id"),
            result.get("api_key_id"),
            result.get("service_account_id"),
            result.get("workspace_id"),
            result.get("model"),
            result.get("service_tier"),
            result.get("context_window"),
            result.get("inference_geo"),
        ),
        "starting_at": starting_at,
        "ending_at": bucket.get("ending_at"),
        "account_id": result.get("account_id"),
        "api_key_id": result.get("api_key_id"),
        "service_account_id": result.get("service_account_id"),
        "workspace_id": result.get("workspace_id"),
        "model": result.get("model"),
        "service_tier": result.get("service_tier"),
        "context_window": result.get("context_window"),
        "inference_geo": result.get("inference_geo"),
        "uncached_input_tokens": result.get("uncached_input_tokens"),
        "cache_read_input_tokens": result.get("cache_read_input_tokens"),
        "cache_creation_ephemeral_1h_input_tokens": cache_creation.get("ephemeral_1h_input_tokens"),
        "cache_creation_ephemeral_5m_input_tokens": cache_creation.get("ephemeral_5m_input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "web_search_requests": server_tool_use.get("web_search_requests"),
    }
    return row


def _flatten_cost_result(bucket: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    starting_at = bucket.get("starting_at")
    return {
        "id": _row_id(
            starting_at,
            result.get("workspace_id"),
            result.get("description"),
            result.get("cost_type"),
            result.get("model"),
            result.get("service_tier"),
            result.get("token_type"),
            result.get("context_window"),
        ),
        "starting_at": starting_at,
        "ending_at": bucket.get("ending_at"),
        "workspace_id": result.get("workspace_id"),
        "description": result.get("description"),
        "cost_type": result.get("cost_type"),
        "model": result.get("model"),
        "service_tier": result.get("service_tier"),
        "token_type": result.get("token_type"),
        "context_window": result.get("context_window"),
        # Data-residency dimension parsed from `description`; kept out of the id (description already
        # disambiguates it) so existing rows' surrogate keys stay stable.
        "inference_geo": result.get("inference_geo"),
        "currency": result.get("currency"),
        "amount": result.get("amount"),
    }


def _explode_usage_bucket(bucket: dict[str, Any]) -> list[dict[str, Any]]:
    # One report page is a list of time buckets, each carrying grouped results — flatten to one row
    # per result with the bucket window merged in. An empty bucket yields no rows.
    return [_flatten_usage_result(bucket, result) for result in bucket.get("results") or []]


def _explode_cost_bucket(bucket: dict[str, Any]) -> list[dict[str, Any]]:
    return [_flatten_cost_result(bucket, result) for result in bucket.get("results") or []]


def _parse_iso_date(value: str) -> date:
    # Accept a bare date or a full RFC 3339 timestamp; only the calendar day matters for the fan-out.
    return date.fromisoformat(value.strip()[:10])


def _as_date(value: Any) -> date:
    """Resolve an incremental watermark to the UTC calendar day it falls in."""
    # datetime subclasses date, so it has to be tested first.
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)).date()
    if isinstance(value, date):
        return value
    return _parse_iso_date(str(value))


def _claude_code_start_day(db_incremental_field_last_value: Any) -> date:
    """Resolve the first day to request: the incremental watermark (already shifted back by the
    pipeline's lookback) on an incremental run, else the Claude Code launch-era floor."""
    if db_incremental_field_last_value is None:
        return DEFAULT_CLAUDE_CODE_START
    return _as_date(db_incremental_field_last_value)


@frozen
class ClaudeCodeActor:
    date: Any
    actor_type: str | None
    email: str | None
    api_key_name: str | None
    terminal_type: str | None


def _claude_code_actor_dims(item: dict[str, Any]) -> ClaudeCodeActor:
    """Pull the shared (date, actor, terminal) dimensions every Claude Code row carries.

    `actor` is either a user (`email_address`) or an API actor (`api_key_name`); surface both as flat
    columns so the grain is queryable without unpacking a nested object.
    """
    actor = item.get("actor") or {}
    return ClaudeCodeActor(
        date=item.get("date"),
        actor_type=actor.get("type"),
        email=actor.get("email_address"),
        api_key_name=actor.get("api_key_name"),
        terminal_type=item.get("terminal_type"),
    )


def _flatten_claude_code_core(item: dict[str, Any]) -> dict[str, Any]:
    """One row per (day, actor): Claude Code core productivity metrics and tool-action counts."""
    dims = _claude_code_actor_dims(item)
    core = item.get("core_metrics") or {}
    lines_of_code = core.get("lines_of_code") or {}
    tool_actions = item.get("tool_actions") or {}

    def _tool(name: str) -> tuple[Any, Any]:
        action = tool_actions.get(name) or {}
        return action.get("accepted"), action.get("rejected")

    edit_accepted, edit_rejected = _tool("edit_tool")
    multi_edit_accepted, multi_edit_rejected = _tool("multi_edit_tool")
    write_accepted, write_rejected = _tool("write_tool")
    notebook_edit_accepted, notebook_edit_rejected = _tool("notebook_edit_tool")

    return {
        "id": _row_id(dims.date, dims.actor_type, dims.email, dims.api_key_name, dims.terminal_type),
        "date": dims.date,
        "organization_id": item.get("organization_id"),
        "actor_type": dims.actor_type,
        "actor_email_address": dims.email,
        "actor_api_key_name": dims.api_key_name,
        "customer_type": item.get("customer_type"),
        "terminal_type": dims.terminal_type,
        "num_sessions": core.get("num_sessions"),
        "lines_of_code_added": lines_of_code.get("added"),
        "lines_of_code_removed": lines_of_code.get("removed"),
        "commits_by_claude_code": core.get("commits_by_claude_code"),
        "pull_requests_by_claude_code": core.get("pull_requests_by_claude_code"),
        "edit_tool_accepted": edit_accepted,
        "edit_tool_rejected": edit_rejected,
        "multi_edit_tool_accepted": multi_edit_accepted,
        "multi_edit_tool_rejected": multi_edit_rejected,
        "write_tool_accepted": write_accepted,
        "write_tool_rejected": write_rejected,
        "notebook_edit_tool_accepted": notebook_edit_accepted,
        "notebook_edit_tool_rejected": notebook_edit_rejected,
    }


def _flatten_claude_code_models(item: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per (day, actor, model): the per-model token and estimated-cost breakdown.

    Split out from the core metrics because tokens/cost are at a finer grain (per model) than sessions
    and commits (per day) — keeping them in one table would either duplicate the core metrics across a
    day's models or bury the per-model cost in a nested column.
    """
    dims = _claude_code_actor_dims(item)
    rows: list[dict[str, Any]] = []
    for entry in item.get("model_breakdown") or []:
        model = entry.get("model")
        tokens = entry.get("tokens") or {}
        estimated_cost = entry.get("estimated_cost") or {}
        rows.append(
            {
                "id": _row_id(dims.date, dims.actor_type, dims.email, dims.api_key_name, dims.terminal_type, model),
                "date": dims.date,
                "organization_id": item.get("organization_id"),
                "actor_type": dims.actor_type,
                "actor_email_address": dims.email,
                "actor_api_key_name": dims.api_key_name,
                "customer_type": item.get("customer_type"),
                "terminal_type": dims.terminal_type,
                "model": model,
                "input_tokens": tokens.get("input"),
                "output_tokens": tokens.get("output"),
                "cache_read_tokens": tokens.get("cache_read"),
                "cache_creation_tokens": tokens.get("cache_creation"),
                "estimated_cost_amount": estimated_cost.get("amount"),
                "estimated_cost_currency": estimated_cost.get("currency"),
            }
        )
    return rows


@frozen
class AnalyticsWindow:
    start: date
    # Exclusive end of the requested range. None for an endpoint that takes a single `date` instead.
    end: Optional[date] = None


def _analytics_windows(
    config: AnthropicEndpointConfig,
    db_incremental_field_last_value: Optional[Any],
    today: date,
    resume_from: Optional[date] = None,
) -> list[AnalyticsWindow]:
    """Resolve the UTC days to request, oldest first.

    A full refresh starts at the oldest day the endpoint serves; an incremental run starts at the
    watermark (already shifted back by the pipeline's lookback), and a resumed run at its checkpoint.
    A start past the newest available day is clamped onto that day, so a run always re-pulls the most
    recent day rather than requesting a day the endpoint would reject.
    """
    floor = ANALYTICS_DATA_FLOOR
    if config.analytics_max_history_days is not None:
        floor = max(floor, today - timedelta(days=config.analytics_max_history_days))
    start = floor
    if db_incremental_field_last_value is not None:
        start = max(start, _as_date(db_incremental_field_last_value))
    if resume_from is not None:
        start = max(start, resume_from)

    last_day = today - timedelta(days=config.analytics_lag_days)
    day = min(start, last_day)
    windows: list[AnalyticsWindow] = []
    while day <= last_day:
        if config.analytics_window == AnalyticsWindowKind.DATE:
            windows.append(AnalyticsWindow(start=day))
        else:
            windows.append(AnalyticsWindow(start=day, end=day + timedelta(days=1)))
        day = day + timedelta(days=1)
    return windows


def _analytics_resume_day(resume: Optional[AnthropicResumeConfig]) -> Optional[date]:
    saved = resume.analytics_window_state if resume is not None else None
    start = saved.get("start") if isinstance(saved, dict) else None
    return _parse_iso_date(str(start)) if start else None


def _analytics_params(config: AnthropicEndpointConfig, window: AnalyticsWindow) -> dict[str, Any]:
    if window.end is None:
        return {"limit": config.limit, "date": window.start.isoformat()}
    if config.analytics_window == AnalyticsWindowKind.DATE_RANGE:
        # Calendar dates rather than RFC 3339 instants, and no `limit`: the summaries endpoint
        # answers a whole range in one response and rejects pagination parameters.
        return {"starting_date": window.start.isoformat(), "ending_date": window.end.isoformat()}
    return {
        "limit": config.limit,
        "starting_at": _format_rfc3339(window.start),
        "ending_at": _format_rfc3339(window.end),
        "bucket_width": config.bucket_width,
    }


def _iter_analytics_windows(
    build_resource: Callable[[AnalyticsWindow], Any],
    windows: list[AnalyticsWindow],
    save_checkpoint: Callable[[date], None],
) -> Iterator[list[dict[str, Any]]]:
    """Yield every day's pages in ascending day order, checkpointing once a day is fully yielded.

    The checkpoint names the first day not yet yielded, so a restart replays at most the day that was
    in progress and merge dedupes it on the synthesized `id`.
    """
    for index, window in enumerate(windows):
        yield from build_resource(window)
        if index + 1 < len(windows):
            save_checkpoint(windows[index + 1].start)


def _flatten_metrics(prefix: str, value: dict[str, Any], row: dict[str, Any]) -> None:
    """Flatten a nested metric object into `prefix_key` columns, one segment per nesting level.

    Anthropic adds per-product metric blocks to the activity record as it ships products, so
    flattening whatever the response carries picks up a new product's metrics with no change here.
    """
    for key, item in value.items():
        name = f"{prefix}_{key}" if prefix else key
        if isinstance(item, dict):
            _flatten_metrics(name, item, row)
        else:
            row[name] = item


def _flatten_analytics_user_activity(day: date, item: dict[str, Any]) -> dict[str, Any]:
    """One row per (day, user): every per-product engagement metric the activity record carries."""
    user = item.get("user") or {}
    row: dict[str, Any] = {
        # The record carries no day of its own, so stamp the day the request asked for.
        "date": _format_rfc3339(day),
        "user_id": user.get("id"),
        "user_email_address": user.get("email_address"),
    }
    for key, value in item.items():
        if key == "user":
            continue
        if isinstance(value, dict):
            # `chat_metrics` becomes `chat_message_count`, `office_metrics.excel` becomes
            # `office_excel_message_count`, and so on.
            _flatten_metrics(key.removesuffix("_metrics"), value, row)
        else:
            row[key] = value
    row["id"] = _row_id(row["date"], row["user_id"])
    return row


def _flatten_analytics_entity_usage(name_field: str, day: date, item: dict[str, Any]) -> dict[str, Any]:
    """One row per (day, entity) for the connector, plugin and skill adoption breakdowns.

    Each record carries no day of its own, so the day the request asked for is stamped on. The
    nested per-product metric blocks are flattened the same way the activity record's are, so a new
    product's metrics arrive as columns with no change here.
    """
    row: dict[str, Any] = {"date": _format_rfc3339(day)}
    for key, value in item.items():
        if isinstance(value, dict):
            # `chat_metrics` becomes `chat_distinct_conversation_skill_used_count`, and
            # `office_metrics.excel` becomes `office_excel_distinct_session_skill_used_count`.
            _flatten_metrics(key.removesuffix("_metrics"), value, row)
        else:
            row[key] = value
    row["id"] = _row_id(row["date"], row.get(name_field))
    return row


# Endpoints whose rows carry no day, mapped to the flattener that stamps the requested day onto each
# row. `analytics_row_map` binds the day before handing the mapper to the resource.
_ANALYTICS_DAY_ROW_MAPS: dict[str, Callable[[date, dict[str, Any]], dict[str, Any]]] = {
    "analytics_user_activity": _flatten_analytics_user_activity,
    "analytics_connector_usage": partial(_flatten_analytics_entity_usage, "connector_name"),
    "analytics_plugin_usage": partial(_flatten_analytics_entity_usage, "plugin_name"),
    "analytics_skill_usage": partial(_flatten_analytics_entity_usage, "skill_name"),
}


def _flatten_rbac_role_permission(item: dict[str, Any]) -> dict[str, Any]:
    """One row per (role, action, resource) grant.

    `resource` is a tagged union whose `type` decides which identifier fields it carries, so every
    identifier gets a column of its own and the ones a given tag does not use stay null. A blanket
    `capability_access_all` or `capability_access_all_ga` action arrives as one row rather than
    expanded per feature, so a query that tallies a role's grants has to treat it as covering every
    product feature its variant describes.
    """
    resource = item.get("resource") or {}
    role_id = item.get("role_id")
    action = item.get("action")
    resource_type = resource.get("type")
    organization_id = resource.get("organization_id")
    connector_id = resource.get("connector_id")
    tool_name = resource.get("tool_name")
    scope = resource.get("scope")
    return {
        "id": _row_id(role_id, action, resource_type, organization_id, connector_id, tool_name, scope),
        "role_id": role_id,
        "action": action,
        "resource_type": resource_type,
        "organization_id": organization_id,
        "connector_id": connector_id,
        "tool_name": tool_name,
        "scope": scope,
    }


# Row mapping applied to a fan-out child after the parent id is stamped on. A child with no entry
# needs nothing beyond the stamp.
_FAN_OUT_ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "rbac_role_permissions": _flatten_rbac_role_permission,
}


def _analytics_actor_columns(item: dict[str, Any]) -> dict[str, Any]:
    """Surface the seat user a per-user report row is attributed to as flat columns."""
    actor = item.get("actor") or {}
    return {
        "user_id": actor.get("user_id"),
        "user_email": actor.get("email"),
        "user_name": actor.get("name"),
        "user_deleted": actor.get("deleted"),
    }


# The per-user report requests carry no `group_by`, so the dimension fields Anthropic populates only
# for a grouped query (model, product, cost_type, token_type, context_window, inference_geo, speed,
# rbac_group_id, and the Claude Tag and Slack fields) are null on every row and are left out below.
def _flatten_analytics_user_cost(item: dict[str, Any]) -> dict[str, Any]:
    """One row per (day, user): cost attributed to that seat user for that day."""
    starting_at = item.get("starting_at")
    actor = _analytics_actor_columns(item)
    return {
        "id": _row_id(starting_at, actor["user_id"]),
        "starting_at": starting_at,
        "ending_at": item.get("ending_at"),
        **actor,
        # Fractional cents as a decimal string, kept as the API sends it. The values can run past
        # what binary floating point represents exactly, so converting them belongs in a query.
        "amount": item.get("amount"),
        "list_amount": item.get("list_amount"),
        "currency": item.get("currency"),
        "requests": item.get("requests"),
    }


def _flatten_analytics_user_usage(item: dict[str, Any]) -> dict[str, Any]:
    """One row per (day, user): token usage attributed to that seat user for that day."""
    starting_at = item.get("starting_at")
    actor = _analytics_actor_columns(item)
    cache_creation = item.get("cache_creation") or {}
    server_tool_use = item.get("server_tool_use") or {}
    return {
        "id": _row_id(starting_at, actor["user_id"]),
        "starting_at": starting_at,
        "ending_at": item.get("ending_at"),
        **actor,
        "uncached_input_tokens": item.get("uncached_input_tokens"),
        "cache_read_input_tokens": item.get("cache_read_input_tokens"),
        "cache_creation_ephemeral_1h_input_tokens": cache_creation.get("ephemeral_1h_input_tokens"),
        "cache_creation_ephemeral_5m_input_tokens": cache_creation.get("ephemeral_5m_input_tokens"),
        "output_tokens": item.get("output_tokens"),
        "total_tokens": item.get("total_tokens"),
        "requests": item.get("requests"),
        "web_search_requests": server_tool_use.get("web_search_requests"),
    }


def _stamp_parent_id(fan_out: FanOutConfig, row: dict[str, Any]) -> dict[str, Any]:
    # The fan-out injects the parent's id as `_<parent>_id`. Fall back to it so the primary key is
    # always populated: the member objects carry their own parent id, but a role permission object
    # carries no role id at all.
    parent_id = row.pop(f"_{fan_out.parent}_id", None)
    row[fan_out.id_column] = row.get(fan_out.id_column) or parent_id
    return row


def _list_paginator(config: AnthropicEndpointConfig) -> AnthropicCursorPaginator:
    if config.pagination == PaginationType.PAGE_TOKEN:
        return AnthropicCursorPaginator(cursor_path="next_page", cursor_param="page")
    return AnthropicCursorPaginator(cursor_path="last_id", cursor_param="after_id")


def _is_bad_request(exc: HTTPError) -> bool:
    return exc.response is not None and exc.response.status_code == 400


def _iter_narrowing_group_by(
    build_resource: Callable[[list[str], Optional[dict[str, Any]]], Any],
    group_by_fallbacks: list[list[str]],
    initial_paginator_state: Optional[dict[str, Any]],
) -> Iterator[list[dict[str, Any]]]:
    """Yield the endpoint's pages, retrying with a narrower `group_by` when the API rejects the query.

    The usage report answers 400 for a query that groups more finely than it will serve, which fails
    the whole sync rather than returning coarser rows. Each fallback is tried in turn until one is
    accepted, so the sync lands on the finest breakdown that org's report serves.

    Narrowing happens only while no page has been yielded yet: once rows are out, re-running at a
    coarser grain would re-emit the same buckets under different synthesized ids. A narrowed query
    also starts from its own first page, since a resume cursor minted by the wider query no longer
    addresses anything.
    """
    for index, group_by in enumerate(group_by_fallbacks):
        resume_state = initial_paginator_state if index == 0 else None
        yielded = False
        try:
            for page in build_resource(group_by, resume_state):
                yielded = True
                yield page
            return
        except HTTPError as exc:
            if yielded or index == len(group_by_fallbacks) - 1 or not _is_bad_request(exc):
                raise


def anthropic_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ANTHROPIC_ENDPOINTS.get(endpoint)
    if config is None:
        # A schema row outlives the catalog entry it was discovered from when an endpoint is
        # dropped. Raise the message `get_non_retryable_errors` keys on, so the run disables the
        # schema and pauses its schedule instead of retrying a KeyError forever.
        raise ValueError(f"{ENDPOINT_RETIRED_ERROR}: {endpoint}")
    # Set only where the rows come from something other than iterating `resource` once.
    items: Optional[Callable[[], Iterator[list[dict[str, Any]]]]] = None

    # The report endpoints page the rate-limited Admin API; the entity lists do not. Give the reports
    # a wider retry budget so it can outlast the organization rate-limit window.
    is_report_endpoint = config.pagination == PaginationType.PAGE
    client_config: ClientConfig = {
        "base_url": ANTHROPIC_BASE_URL,
        "headers": _version_headers(),
        "auth": _auth_config(api_key),
        "max_retries": REPORT_MAX_RETRY_ATTEMPTS if is_report_endpoint else MAX_RETRY_ATTEMPTS,
    }
    if is_report_endpoint:
        client_config["retry_backoff_max_seconds"] = REPORT_RETRY_BACKOFF_MAX_SECONDS

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.analytics_window is not None:
        # Claude Enterprise Analytics: one request per UTC day, each day its own resource so the
        # requested day is available to the row mapper. One day per request is also what keeps the
        # rows ascending by day: within a wider range the per-user reports rank rows by spend rather
        # than by time, which the pipeline's `sort_mode="asc"` watermark could not follow.
        analytics_windows = _analytics_windows(
            config,
            db_incremental_field_last_value,
            datetime.now(UTC).date(),
            resume_from=_analytics_resume_day(resume),
        )
        # One tracked session shared by every day's client, so a backfill reuses a single connection
        # pool instead of opening one per day.
        client_config["session"] = make_tracked_session(redact_values=(api_key,))

        def analytics_row_map(
            window: AnalyticsWindow,
        ) -> Optional[Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]]:
            if config.analytics_window == AnalyticsWindowKind.DATE:
                # These records carry no day, so bind the day this request asks for.
                return partial(_ANALYTICS_DAY_ROW_MAPS[endpoint], window.start)
            if config.analytics_window == AnalyticsWindowKind.DATE_RANGE:
                # A summary row is already flat and carries its own `starting_at`.
                return None
            return _flatten_analytics_user_cost if endpoint == "analytics_user_cost" else _flatten_analytics_user_usage

        def save_analytics_checkpoint(next_start: date) -> None:
            resumable_source_manager.save_state(
                AnthropicResumeConfig(analytics_window_state={"start": next_start.isoformat()})
            )

        def build_analytics_resource(window: AnalyticsWindow) -> Any:
            analytics_resource: EndpointResource = {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _analytics_params(config, window),
                    "data_selector": config.data_selector,
                    "paginator": AnthropicCursorPaginator(cursor_path="next_page", cursor_param="page"),
                },
                "data_map": analytics_row_map(window),
            }
            analytics_rest_config: RESTAPIConfig = {
                "client": client_config,
                "resource_defaults": None,
                "resources": [analytics_resource],
            }
            return rest_api_resource(
                analytics_rest_config,
                team_id,
                job_id,
                db_incremental_field_last_value,
            )

        # Built for the first day only to carry the resource's column hints; the fan-out below
        # rebuilds a resource per day.
        resource = build_analytics_resource(analytics_windows[0])
        items = partial(_iter_analytics_windows, build_analytics_resource, analytics_windows, save_analytics_checkpoint)
    elif config.fan_out_over_days:
        # Claude Code analytics: one windowed request per calendar day, driven entirely by the
        # paginator (there is no parent API resource to resolve days from).
        start_day = _claude_code_start_day(db_incremental_field_last_value)
        # Annotated to the shared base so the other branches can rebind it to AnthropicCursorPaginator.
        paginator: BasePaginator = ClaudeCodeDayPaginator(start_day, datetime.now(UTC).date())
        day_data_map: Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]] = (
            _flatten_claude_code_models if endpoint == "claude_code_model_breakdown" else _flatten_claude_code_core
        )
        day_params: dict[str, Any] = {}
        if config.limit is not None:
            day_params["limit"] = config.limit

        cc_endpoint_resource: EndpointResource = {
            "name": endpoint,
            "endpoint": {
                "path": config.path,
                "params": day_params,
                "data_selector": "data",
                "paginator": paginator,
            },
            "data_map": day_data_map,
        }
        cc_rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": None,
            "resources": [cc_endpoint_resource],
        }

        initial_day_state = resume.day_fanout_state if resume is not None else None

        def save_day_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(AnthropicResumeConfig(day_fanout_state=state))

        resource = rest_api_resource(
            cc_rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_day_checkpoint,
            initial_paginator_state=initial_day_state,
        )
    elif config.fan_out is not None:
        # Anthropic serves no org-wide list for this sub-resource, so enumerate the parent endpoint
        # and fetch the sub-resource once per parent row. The workspaces parent includes archived
        # workspaces (see its extra_params), since historical usage and cost rows still name them.
        fan_out = config.fan_out
        parent_config = ANTHROPIC_ENDPOINTS[fan_out.parent]
        child_row_map = _FAN_OUT_ROW_MAPS.get(endpoint)

        def fan_out_data_map(row: dict[str, Any]) -> dict[str, Any]:
            stamped = _stamp_parent_id(fan_out, row)
            return child_row_map(stamped) if child_row_map else stamped

        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": None,
            "resources": [
                {
                    "name": fan_out.parent,
                    "endpoint": {
                        "path": parent_config.path,
                        "params": {"limit": ENTITY_PAGE_SIZE, **parent_config.extra_params},
                        "data_selector": parent_config.data_selector,
                        "paginator": _list_paginator(parent_config),
                    },
                },
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": {
                            "limit": ENTITY_PAGE_SIZE,
                            fan_out.path_param: {"type": "resolve", "resource": fan_out.parent, "field": "id"},
                        },
                        "data_selector": config.data_selector,
                        "paginator": _list_paginator(config),
                        # A parent that does not serve this sub-resource, or that was archived or
                        # deleted between enumeration and the child fetch, answers 404. Skip that
                        # parent instead of failing the whole schema. 429/5xx are retried by the
                        # client before hooks run, and any other 4xx still raises.
                        "response_actions": [{"status_code": 404, "action": "ignore"}],
                    },
                    "include_from_parent": ["id"],
                    "data_map": fan_out_data_map,
                },
            ],
        }

        # Only a framework-shaped checkpoint can seed the fan-out. A legacy (cursor, workspace_id)
        # state restarts the fan-out fresh, and the overlap merge dedupes on the composite key.
        initial_fanout_state = resume.fanout_state if resume is not None else None

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(AnthropicResumeConfig(fanout_state=state))

        resources = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=initial_fanout_state,
        )
        resource = next(r for r in resources if r.name == endpoint)
    else:
        is_report = config.pagination == PaginationType.PAGE
        data_map: Optional[Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]]
        if is_report:
            data_map = _explode_usage_bucket if endpoint == "usage_report" else _explode_cost_bucket
        else:
            data_map = _flatten_created_by if endpoint == "api_keys" else None

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None and resume.cursor:
            initial_paginator_state = {"cursor": resume.cursor}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only while a next page remains; the checkpoint is saved AFTER a page is
            # yielded, pointing at the next page, so a crash resumes from a page whose predecessors
            # were all yielded — the overlap merge dedupes on the primary key.
            if state and state.get("cursor"):
                resumable_source_manager.save_state(AnthropicResumeConfig(cursor=state["cursor"]))

        def build_resource(group_by: list[str], resume_state: Optional[dict[str, Any]]) -> Any:
            if is_report:
                # Report endpoints: `starting_at` is required. On an incremental run start from the
                # watermark (already shifted back by the pipeline's lookback); otherwise fall back to
                # the Anthropic launch date to pull all history.
                params: dict[str, Any] = {"bucket_width": config.bucket_width}
                if config.limit is not None:
                    params["limit"] = config.limit
                if group_by:
                    # requests encodes a list value as one repeated query param per element.
                    params["group_by[]"] = group_by
                params["starting_at"] = {
                    "type": "incremental",
                    "cursor_path": "starting_at",
                    "initial_value": DEFAULT_STARTING_AT,
                    "convert": _format_rfc3339,
                }
                paginator: BasePaginator = AnthropicCursorPaginator(cursor_path="next_page", cursor_param="page")
            else:
                params = {"limit": ENTITY_PAGE_SIZE, **config.extra_params}
                paginator = _list_paginator(config)

            endpoint_resource: EndpointResource = {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_selector,
                    "paginator": paginator,
                },
                "data_map": data_map,
            }
            rest_config: RESTAPIConfig = {
                "client": client_config,
                "resource_defaults": None,
                "resources": [endpoint_resource],
            }
            return rest_api_resource(
                rest_config,
                team_id,
                job_id,
                db_incremental_field_last_value,
                resume_hook=save_checkpoint,
                initial_paginator_state=resume_state,
            )

        if endpoint == "usage_report":
            resource = build_resource(USAGE_GROUP_BY_FALLBACKS[0], initial_paginator_state)
            items = partial(_iter_narrowing_group_by, build_resource, USAGE_GROUP_BY_FALLBACKS, initial_paginator_state)
        else:
            resource = build_resource(config.group_by, initial_paginator_state)

    return SourceResponse(
        name=endpoint,
        items=items if items is not None else (lambda: resource),
        primary_keys=config.primary_keys,
        # Report buckets return oldest-first from `starting_at`, and entity cursors page forward, so
        # rows arrive in ascending order — the pipeline checkpoints the watermark after each batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
