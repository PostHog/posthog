import functools
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Request, Response
from requests.exceptions import HTTPError
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.settings import (
    PAGERDUTY_ENDPOINTS,
    PagerDutyEndpointConfig,
)

PAGERDUTY_BASE_URL = "https://api.pagerduty.com"

# PagerDuty's max page size is 100; the default is 25.
PAGE_SIZE = 100

# The Analytics API pages with a body cursor and accepts up to 1,000 rows per page.
ANALYTICS_PAGE_SIZE = 1000

# PagerDuty rejects requests where `offset + limit` exceeds 10,000 with an HTTP 400.
# Stop paginating before we cross it. Incremental endpoints stay well under this because
# the `since` filter bounds the window; full-refresh endpoints could in theory truncate
# on very large accounts.
MAX_OFFSET = 10_000

# The statuses PagerDuty answers for a feature the account's plan does not include: 402 with error
# code 2014 ("required abilities are unavailable") for /teams, and 404 for /priorities. Each gated
# endpoint's `PagerDutyEndpointConfig.plan_gated_status` says which one applies to it — the other
# status on that same endpoint is a genuine failure and must still raise.


@frozen
class PagerDutyResumeConfig:
    # Row offset of the next unfetched page — PagerDuty list endpoints paginate with limit/offset.
    offset: int = 0
    # Framework fan-out checkpoint ({"completed": [...], "current": ..., "child_state": ...}) for
    # endpoints that read one child list per parent row.
    fanout_state: Optional[dict[str, Any]] = None
    # `starting_after` cursor of the next unfetched page, for the cursor-paged Analytics API.
    cursor: Optional[str] = None


def _format_incremental_value(value: Any) -> str:
    """Format an incremental field value as an ISO 8601 string for PagerDuty's `since` filter."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _format_incremental_value_or_none(value: Any) -> Optional[str]:
    # None means no watermark yet (first incremental sync) — return None so the framework drops the
    # `since` param entirely rather than sending the literal string "None".
    return _format_incremental_value(value) if value is not None else None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token token={api_token}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }


class PagerDutyPaginator(BasePaginator):
    """Offset paginator driven by PagerDuty's body-level ``more`` flag.

    PagerDuty signals another page with a ``more: true`` boolean rather than page fullness, and
    rejects ``offset + limit > 10000`` with an HTTP 400 — so we stop before crossing that ceiling.
    Neither shape is expressible with the built-in ``OffsetPaginator`` (which keys on a body ``total``
    or a short page), hence this small local paginator. Resume is supported via the row offset.
    """

    def __init__(self, limit: int = PAGE_SIZE, maximum_offset: int = MAX_OFFSET, offset: int = 0) -> None:
        super().__init__()
        self.limit = limit
        self.maximum_offset = maximum_offset
        self.offset = offset

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self.limit
        request.params["offset"] = self.offset

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # Empty page: stop without advancing (the API returned nothing more to read).
        if not data:
            self._has_next_page = False
            return

        try:
            more = bool(response.json().get("more", False))
        except Exception:
            more = False
        if not more:
            self._has_next_page = False
            return

        self.offset += self.limit
        # PagerDuty 400s when offset + limit exceeds MAX_OFFSET; stop before requesting that page
        # (results may be truncated on very large full-refresh accounts).
        if self.offset + self.limit > self.maximum_offset:
            self._has_next_page = False
            return

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["offset"] = self.offset

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state incremented it).
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True


class PagerDutyAnalyticsPaginator(JSONResponseCursorPaginator):
    """Body cursor paginator for the Analytics API.

    Each response carries the cursor of its last row in ``last`` even when it is the final page, so the
    body-level ``more`` flag decides whether another page exists.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="last", cursor_param="starting_after", param_location="json")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            more = bool(response.json().get("more", False))
        except Exception:
            more = False
        if not data or not more:
            self._has_next_page = False
            return
        super().update_state(response, data)


def _non_secret_headers() -> dict[str, str]:
    # Auth (the `Token token=...` Authorization header) is supplied via the framework auth config so
    # its value is redacted from logs and errors; only the non-secret headers are set here.
    return {
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }


def _reference_id(row: dict[str, Any], key: str) -> Optional[str]:
    reference = row.get(key)
    return reference.get("id") if isinstance(reference, dict) else None


def _shape_oncall(row: dict[str, Any]) -> dict[str, Any]:
    row["user_id"] = _reference_id(row, "user")
    row["escalation_policy_id"] = _reference_id(row, "escalation_policy")
    row["schedule_id"] = _reference_id(row, "schedule")
    # An on-call entry has no id of its own. A user holds one escalation level of one policy through
    # one schedule (none for a direct user target) for one shift, so those fields together name it.
    key_parts = (row["escalation_policy_id"], row.get("escalation_level"), row["user_id"], row["schedule_id"])
    row["id"] = ":".join("" if part is None else str(part) for part in (*key_parts, row.get("start")))
    return row


def _shape_user_reference(row: dict[str, Any]) -> dict[str, Any]:
    row["user_id"] = _reference_id(row, "user")
    return row


_ROW_SHAPERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "oncalls": _shape_oncall,
    "team_members": _shape_user_reference,
    "incident_notes": _shape_user_reference,
}


def _row_map(endpoint: str, config: PagerDutyEndpointConfig) -> Optional[Callable[[dict[str, Any]], dict[str, Any]]]:
    rename_parent_id = (
        rename_parent_fields(config.parent, {"id": config.parent_id_column})
        if config.parent and config.parent_id_column
        else None
    )
    shaper = _ROW_SHAPERS.get(endpoint)
    if rename_parent_id is None and shaper is None:
        return None

    def row_map(row: dict[str, Any]) -> dict[str, Any]:
        if rename_parent_id is not None:
            row = rename_parent_id(row)
        return shaper(row) if shaper is not None else row

    return row_map


def _list_params(config: PagerDutyEndpointConfig, should_use_incremental_field: bool) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)
    if config.supports_since:
        # created_at is immutable, so an ascending sort means new rows append to the end and never
        # shift pages we've already read. Sent on every sync (not just incremental ones) so full
        # refreshes paginate over a stable ordering too.
        params["sort_by"] = "created_at:asc"
        if should_use_incremental_field:
            # The framework injects the watermark as `since`; on the first incremental sync the value
            # is None and the param is dropped, so we only bound the window once we have a cursor.
            params["since"] = {
                "type": "incremental",
                "cursor_path": "created_at",
                "initial_value": None,
                "convert": _format_incremental_value_or_none,
            }
    return params


def _analytics_body(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> dict[str, Any]:
    # Without a created_at range the API answers its default window. UTC keeps timestamps comparable
    # with the other tables.
    body: dict[str, Any] = {
        "limit": ANALYTICS_PAGE_SIZE,
        "order": "asc",
        "order_by": "created_at",
        "time_zone": "Etc/UTC",
    }
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        body["filters"] = {"updated_after": _format_incremental_value(db_incremental_field_last_value)}
    return body


def _skip_when_plan_gated(
    items: Iterable[Any],
    endpoint: str,
    plan_gated_feature: str,
    plan_gated_status: int,
    logger: FilteringBoundLogger,
) -> Iterator[Any]:
    try:
        yield from items
    except HTTPError as err:
        if err.response is None or err.response.status_code != plan_gated_status:
            raise
        logger.warning(
            f"Your PagerDuty plan does not include {plan_gated_feature}, so the {endpoint} table synced no rows. "
            "Turn off syncing for this table, or upgrade your PagerDuty plan."
        )


ANALYTICS_READ_ONLY_KEY_ERROR = (
    "The PagerDuty Analytics API only accepts POST requests, so a read-only API key can't sync the "
    "incident_analytics table. Use a full access API key, or turn off syncing for this table."
)
ANALYTICS_PERSONAL_KEY_ERROR = (
    "The PagerDuty Analytics API needs an account-level API key. A personal API key can't sync the "
    "incident_analytics table. Use an account-level key, or turn off syncing for this table."
)


def _probe_analytics(api_token: str, url: str) -> tuple[bool, int | None]:
    try:
        session = make_tracked_session(redact_values=(api_token,))
        response = session.post(url, headers=_get_headers(api_token), json={"limit": 1}, timeout=10.0)
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, None
    return response.status_code == 200, response.status_code


def validate_credentials(api_token: str, endpoint: Optional[str] = None) -> tuple[bool, int, str | None]:
    """Probe PagerDuty with a cheap single-row request.

    Returns ``(ok, status_code, error_message)``. ``status_code`` is 0 on transport failure.
    The caller decides how to treat 403 (valid token, missing scope for the probed endpoint).
    """
    config = PAGERDUTY_ENDPOINTS.get(endpoint) if endpoint else None
    if config is not None and config.parent is not None:
        # A fan-out path carries an `{id}` placeholder. The parent list needs the same access scope.
        config = PAGERDUTY_ENDPOINTS[config.parent]
    path = config.path if config else "/users"

    is_post = config is not None and config.method == "POST"
    if is_post:
        ok, status = _probe_analytics(api_token, f"{PAGERDUTY_BASE_URL}{path}")
    else:
        ok, status = validate_via_probe(
            lambda: make_tracked_session(redact_values=(api_token,)),
            f"{PAGERDUTY_BASE_URL}{path}?{urlencode({'limit': 1})}",
            headers=_get_headers(api_token),
        )
    if ok:
        return True, status if status is not None else 200, None
    if status is None:
        return False, 0, "Could not reach PagerDuty"
    # Read-only keys can only make GET requests, and personal keys must filter Analytics requests by
    # team or service, which this source does not do.
    if is_post and status == 403:
        return False, 403, ANALYTICS_READ_ONLY_KEY_ERROR
    if is_post and status == 400:
        return False, 400, ANALYTICS_PERSONAL_KEY_ERROR
    if status == 401:
        return False, 401, "Invalid PagerDuty API key"
    if status == 403:
        return False, 403, "Your PagerDuty API key does not have access to this resource"
    return False, status, f"PagerDuty API error (status {status})"


def pagerduty_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PagerDutyResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: PagerDutyEndpointConfig = PAGERDUTY_ENDPOINTS[endpoint]

    endpoint_resource: EndpointResource
    resources: list[str | EndpointResource]
    if config.method == "POST":
        endpoint_resource = {
            "name": endpoint,
            "endpoint": {
                "method": "POST",
                "path": config.path,
                "json": _analytics_body(should_use_incremental_field, db_incremental_field_last_value),
                "data_selector": config.envelope_key,
                "paginator": PagerDutyAnalyticsPaginator(),
            },
        }
        resources = [endpoint_resource]
    elif config.parent is None:
        endpoint_resource = {
            "name": endpoint,
            "endpoint": {
                "path": config.path,
                "params": _list_params(config, should_use_incremental_field),
                # A missing envelope key yields no rows and stops pagination — the API returning an
                # unexpected shape isn't treated as fatal here (matches the prior data.get(key, [])).
                "data_selector": config.envelope_key,
            },
        }
        resources = [endpoint_resource]
    else:
        parent_config = PAGERDUTY_ENDPOINTS[config.parent]
        endpoint_resource = {
            "name": endpoint,
            "endpoint": {
                "path": config.path,
                "params": {"id": {"type": "resolve", "resource": config.parent, "field": "id"}},
                "data_selector": config.envelope_key,
                # A parent removed between the parent listing and its child fetch has no children left.
                "response_actions": [{"status_code": 404, "action": "ignore"}],
            },
            "include_from_parent": ["id"],
        }
        parent_resource: EndpointResource = {
            "name": config.parent,
            "endpoint": {
                "path": parent_config.path,
                "params": _list_params(parent_config, should_use_incremental_field=False),
                "data_selector": parent_config.envelope_key,
            },
        }
        resources = [parent_resource, endpoint_resource]

    row_map = _row_map(endpoint, config)
    if row_map is not None:
        endpoint_resource["data_map"] = row_map

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PAGERDUTY_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {
                "type": "api_key",
                "api_key": f"Token token={api_token}",
                "name": "Authorization",
                "location": "header",
            },
            "paginator": PagerDutyPaginator(limit=PAGE_SIZE, maximum_offset=MAX_OFFSET),
        },
        "resources": resources,
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.parent:
                initial_paginator_state = resume.fanout_state
            elif config.method == "POST":
                initial_paginator_state = {"cursor": resume.cursor} if resume.cursor else None
            else:
                initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if not state:
            return
        if config.parent is not None:
            resumable_source_manager.save_state(PagerDutyResumeConfig(fanout_state=state))
        elif state.get("cursor") is not None:
            resumable_source_manager.save_state(PagerDutyResumeConfig(cursor=str(state["cursor"])))
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        elif state.get("offset") is not None:
            resumable_source_manager.save_state(PagerDutyResumeConfig(offset=int(state["offset"])))

    resource = next(
        built
        for built in rest_api_resources(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value if should_use_incremental_field else None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        if built.name == endpoint
    )

    gated_resource = resource
    if config.plan_gated_feature is not None and config.plan_gated_status is not None:
        # The plan gate hands each page on unchanged and holds no rows. As a `Resource` it keeps the
        # framework's checkpoints and safe points, which a plain generator wrapper would disable.
        gated_resource = Resource(
            functools.partial(
                _skip_when_plan_gated,
                resource,
                endpoint,
                config.plan_gated_feature,
                config.plan_gated_status,
                logger,
            ),
            name=endpoint,
            hints=resource._hints,
        )

    def items() -> Iterable[Any]:
        return gated_resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # We request created_at ascending where a sort is available, and full-refresh endpoints replace
        # wholesale. Endpoints whose incremental field the API can't sort by declare no order.
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
