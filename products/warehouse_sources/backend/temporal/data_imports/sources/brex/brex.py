import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.brex.settings import (
    BREX_ENDPOINTS,
    BrexEndpointConfig,
    BrexFanOutConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BREX_BASE_URL = "https://api.brex.com"

# Brex versions each product API independently in the URL path (transactions/users on /v2,
# expenses/vendors on /v1) — there is no global version header or segment. Every endpoint already
# targets its API's current path, so both labels resolve to identical requests today; the version
# seam (`BrexEndpointConfig.versioned_paths`) exists for when a specific API ships a new path.
BREX_API_VERSION_V1 = "v1"
BREX_API_VERSION_V2 = "v2"

# Expenses caps `limit` at 100; other endpoints don't document a max, so 100 is used uniformly.
PAGE_SIZE = 100


@dataclasses.dataclass(frozen=True)
class BrexResumeConfig:
    # Pre-framework fields, kept so previously saved state still parses (dataclass(**saved)).
    # `next_cursor` of the last fully-yielded page for the endpoint (or current cash account).
    cursor: Optional[str] = None
    # Cash account currently being paged; None for top-level endpoints.
    account_id: Optional[str] = None
    # Cash accounts already fully synced in this run.
    completed_account_ids: list[str] = dataclasses.field(default_factory=list)
    # Framework fan-out checkpoint
    # ({"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}).
    fanout_state: Optional[dict[str, Any]] = None


def _to_rfc3339(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to the RFC 3339 date-time format Brex's
    `*_start` filters expect. Watermarks arrive as datetimes, dates, or ISO strings
    depending on the endpoint's incremental field type."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    if isinstance(value, str):
        # Date-only strings (e.g. a posted_at_date watermark) need a time component.
        if len(value) == 10:
            return f"{value}T00:00:00Z"
        return value
    return None


def _resolve_path(config: BrexEndpointConfig, api_version: str) -> str:
    """Path for the endpoint under the resolved vendor API version, honoring any per-version
    override. Falls back to the endpoint's default path when the version has none."""
    return config.versioned_paths.get(api_version, config.path)


def _paginator() -> JSONResponseCursorPaginator:
    # All Brex sub-APIs paginate with `cursor` + `limit` params and `next_cursor` +
    # `items` in the response body.
    return JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BREX_BASE_URL,
        # Bearer auth via the framework auth config so the token is redacted from logs;
        # only the non-secret accept header is set here. Brex rate-limits at 1,000
        # requests per 60s — the client retries 429/5xx and honors Retry-After.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": _paginator(),
        # cash_accounts responses carry account_number/routing_number under generic field names
        # the name-based sample scrubber doesn't recognise, so keep all Brex bodies out of HTTP
        # sample capture rather than special-casing one endpoint.
        "capture": False,
    }


def _endpoint_config(config: BrexEndpointConfig, path: str, should_use_incremental_field: bool) -> Endpoint:
    endpoint: Endpoint = {"path": path, "data_selector": config.data_selector}
    if config.paginated:
        endpoint["params"] = {"limit": PAGE_SIZE}
    else:
        endpoint["paginator"] = "single_page"
    if should_use_incremental_field and config.incremental_param is not None:
        # Brex docs don't state whether the cursor re-encodes the original filters, so the
        # timestamp filter is re-sent on every page to be safe.
        endpoint["incremental"] = {"start_param": config.incremental_param, "convert": _to_rfc3339}
    return endpoint


def _fanout_initial_state(
    config: BrexEndpointConfig, fan_out: BrexFanOutConfig, resume: BrexResumeConfig
) -> Optional[dict[str, Any]]:
    if resume.fanout_state is not None:
        return resume.fanout_state
    # Translate pre-framework cash-transactions resume state (account ids + cursor) into the
    # framework's fan-out checkpoint shape (resolved child paths).
    if not (resume.completed_account_ids or resume.account_id):
        return None

    def child_path(parent_id: str) -> str:
        return config.path.format(**{fan_out.resolve_param: parent_id})

    current = child_path(resume.account_id) if resume.account_id else None
    return {
        "completed": [child_path(account_id) for account_id in resume.completed_account_ids],
        "current": current,
        "child_state": {"cursor": resume.cursor} if resume.cursor is not None and current is not None else None,
    }


def brex_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BrexResumeConfig],
    api_version: str = BREX_API_VERSION_V2,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BREX_ENDPOINTS[endpoint]
    path = _resolve_path(config, api_version)

    resume: Optional[BrexResumeConfig] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()

    if config.fan_out is not None:
        fan_out = config.fan_out
        parent_config = BREX_ENDPOINTS[fan_out.parent_name]
        initial_state = _fanout_initial_state(config, fan_out, resume) if resume is not None else None

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(BrexResumeConfig(fanout_state=state))

        child_resource: EndpointResource = {
            "name": endpoint,
            "endpoint": {
                **_endpoint_config(config, path, should_use_incremental_field),
                "params": {
                    "limit": PAGE_SIZE,
                    fan_out.resolve_param: {
                        "type": "resolve",
                        "resource": fan_out.parent_name,
                        "field": fan_out.parent_field,
                    },
                },
                # Set explicitly because a child path that ends in the resolved placeholder
                # would otherwise be treated as a single-entity endpoint (SinglePagePaginator).
                # Every parent's child list is cursor-paged like the top-level endpoints.
                "paginator": _paginator(),
            },
        }
        if fan_out.parent_field_renames:
            # include_from_parent injects each parent field as `_<parent>_<field>`; the data_map
            # renames it to the key the child rows are expected to carry.
            child_resource["include_from_parent"] = list(fan_out.parent_field_renames)
            child_resource["data_map"] = rename_parent_fields(fan_out.parent_name, fan_out.parent_field_renames)

        rest_config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resources": [
                {
                    "name": fan_out.parent_name,
                    "endpoint": _endpoint_config(
                        parent_config, _resolve_path(parent_config, api_version), should_use_incremental_field=False
                    ),
                },
                child_resource,
            ],
        }
        resources = {
            res.name: res
            for res in rest_api_resources(
                rest_config,
                team_id,
                job_id,
                db_incremental_field_last_value,
                resume_hook=save_fanout_checkpoint,
                initial_paginator_state=initial_state,
            )
        }
        resource = resources[endpoint]
    else:
        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only while a next page remains; the framework calls the hook AFTER a page
            # is yielded, so a crash re-yields the last batch (merge dedupes on primary key)
            # rather than skipping it.
            if state is not None and state.get("cursor") is not None:
                resumable_source_manager.save_state(BrexResumeConfig(cursor=state["cursor"]))

        rest_config = {
            "client": _client_config(api_key),
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": _endpoint_config(config, path, should_use_incremental_field),
                }
            ],
        }
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
        # Brex doesn't expose a sort param and doesn't document list ordering. "desc" makes the
        # pipeline commit the incremental watermark only after a fully successful run, which is
        # the safe choice when ascending order can't be requested.
        sort_mode="desc" if config.incremental_fields else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the API user token is genuine. /v2/users/me is a cheap authenticated probe.

    A 403 means the token is valid but wasn't granted the Team scope — users may
    legitimately scope tokens to only the endpoints they want to sync, so it's accepted.
    """
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BREX_BASE_URL}/v2/users/me",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        ok_statuses=(200, 403),
    )
    return ok
