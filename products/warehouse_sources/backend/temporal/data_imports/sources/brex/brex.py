import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.settings import (
    BREX_ENDPOINTS,
    BrexEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BREX_BASE_URL = "https://api.brex.com"
# Expenses caps `limit` at 100; other endpoints don't document a max, so 100 is used uniformly.
PAGE_SIZE = 100

CASH_ACCOUNTS_PATH = "/v2/accounts/cash"
# Injected into cash transaction rows so rows from different cash accounts stay distinguishable.
CASH_ACCOUNT_ID_KEY = "account_id"
# Parent resource name in the cash-transactions fan-out config. With include_from_parent=["id"]
# the framework injects the parent account id into child rows as `_cash_accounts_id`; a data_map
# renames it to the `account_id` key the rows carried before the rest_source migration.
_CASH_ACCOUNTS_PARENT = "cash_accounts"
_PARENT_ACCOUNT_ID_KEY = f"_{_CASH_ACCOUNTS_PARENT}_id"


@dataclasses.dataclass
class BrexResumeConfig:
    # Pre-framework fields, kept so previously saved state still parses (dataclass(**saved)).
    # `next_cursor` of the last fully-yielded page for the endpoint (or current cash account).
    cursor: Optional[str] = None
    # Cash account currently being paged; None for top-level endpoints.
    account_id: Optional[str] = None
    # Cash accounts already fully synced in this run.
    completed_account_ids: list[str] = dataclasses.field(default_factory=list)
    # Framework fan-out checkpoint for cash_transactions
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
    }


def _endpoint_config(config: BrexEndpointConfig, path: str, should_use_incremental_field: bool) -> Endpoint:
    endpoint: Endpoint = {
        "path": path,
        "params": {"limit": PAGE_SIZE},
        "data_selector": "items",
    }
    if should_use_incremental_field and config.incremental_param is not None:
        # Brex docs don't state whether the cursor re-encodes the original filters, so the
        # timestamp filter is re-sent on every page to be safe.
        endpoint["incremental"] = {"start_param": config.incremental_param, "convert": _to_rfc3339}
    return endpoint


def _inject_account_id(row: dict[str, Any]) -> dict[str, Any]:
    row[CASH_ACCOUNT_ID_KEY] = row.pop(_PARENT_ACCOUNT_ID_KEY)
    return row


def _fanout_initial_state(config: BrexEndpointConfig, resume: BrexResumeConfig) -> Optional[dict[str, Any]]:
    if resume.fanout_state is not None:
        return resume.fanout_state
    # Translate pre-framework resume state (account ids + cursor) into the framework's
    # fan-out checkpoint shape (resolved child paths).
    if not (resume.completed_account_ids or resume.account_id):
        return None
    current = config.path.format(account_id=resume.account_id) if resume.account_id else None
    return {
        "completed": [config.path.format(account_id=account_id) for account_id in resume.completed_account_ids],
        "current": current,
        "child_state": {"cursor": resume.cursor} if resume.cursor is not None and current is not None else None,
    }


def brex_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BrexResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BREX_ENDPOINTS[endpoint]

    resume: Optional[BrexResumeConfig] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()

    if config.fan_out_cash_accounts:
        initial_state = _fanout_initial_state(config, resume) if resume is not None else None

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(BrexResumeConfig(fanout_state=state))

        rest_config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resources": [
                {
                    "name": _CASH_ACCOUNTS_PARENT,
                    "endpoint": {
                        "path": CASH_ACCOUNTS_PATH,
                        "params": {"limit": PAGE_SIZE},
                        "data_selector": "items",
                    },
                },
                {
                    "name": endpoint,
                    "endpoint": {
                        **_endpoint_config(config, config.path, should_use_incremental_field),
                        "params": {
                            "limit": PAGE_SIZE,
                            "account_id": {
                                "type": "resolve",
                                "resource": _CASH_ACCOUNTS_PARENT,
                                "field": "id",
                            },
                        },
                        # The path ends in `{account_id}`, which the framework would otherwise
                        # treat as a single-entity endpoint (SinglePagePaginator) — each
                        # account's transaction list is cursor-paged like everything else.
                        "paginator": _paginator(),
                    },
                    "include_from_parent": ["id"],
                    "data_map": _inject_account_id,
                },
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
                    "endpoint": _endpoint_config(config, config.path, should_use_incremental_field),
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
