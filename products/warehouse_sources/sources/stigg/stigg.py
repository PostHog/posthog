from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import quote

from requests import Response

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    IncrementalConfig,
    JSONResponseCursorPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.stigg.settings import STIGG_ENDPOINTS, StiggEndpointConfig

STIGG_BASE_URL = "https://api.stigg.io/api/v1"
# List endpoints accept a `limit` of up to 100 (default 20); the largest page minimises round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an API key is genuine. Server API keys are environment-wide,
# so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/customers"
# Versioned packages: the listing has one row per version, but their sub-resources take only the id.
_VERSIONED_PARENTS = frozenset({"plans", "addons"})


@frozen
class StiggResumeConfig:
    # Cursor for the next page: Stigg returns it as `pagination.next` and accepts it back as
    # the `after` query param. A crashed full-refresh sync resumes from the page after the last
    # one yielded; merge dedupes the re-pulled page on the primary key. `None` means start from
    # the first page.
    cursor: str | None = None
    # Paginator state of a fan-out table, including the position in the parent listing.
    fanout_state: dict[str, Any] | None = None


class StiggCursorPaginator(JSONResponseCursorPaginator):
    """Cursor paginator for Stigg's list contract.

    Stigg wraps records in ``{"data": [...], "pagination": {"next": ..., "prev": ...}}`` and
    accepts the `next` cursor back as the ``after`` query param. Beyond the built-in null-cursor
    stop, an EMPTY page also ends the sync — a defensive guard so a buggy upstream cursor that
    keeps returning a non-null `next` can't loop the sync forever.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="pagination.next", cursor_param="after")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not data:
            self._has_next_page = False


def _accept_header() -> dict[str, str]:
    # Auth (the X-API-KEY header) is supplied via the framework auth config so its value is
    # redacted from logs and raised errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": STIGG_BASE_URL,
        "headers": _accept_header(),
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"},
        "paginator": StiggCursorPaginator(),
    }


def _partition_kwargs(config: StiggEndpointConfig) -> dict[str, Any]:
    if config.partition_key is None:
        return {}
    return {
        "partition_count": 1,
        "partition_size": 1,
        "partition_mode": "datetime",
        "partition_format": "month",
        "partition_keys": [config.partition_key],
    }


def _parent_filter(parent_name: str) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    # Stigg ids are user-defined slugs, so they are percent-encoded before they go into a path
    # or a query string. A versioned package repeats its id once per version, so a repeated id
    # is dropped to keep one request (and one set of child rows) per package.
    seen: set[str] = set()

    def _map(row: dict[str, Any]) -> list[dict[str, Any]]:
        parent_id = row.get("id")
        if parent_id is None:
            return []
        parent_id = str(parent_id)
        if parent_name in _VERSIONED_PARENTS:
            if parent_id in seen:
                return []
            seen.add(parent_id)
        return [{**row, "pathId": quote(parent_id, safe="")}]

    return _map


def _lift_entitlement_keys(row: dict[str, Any]) -> dict[str, Any]:
    # A feature entitlement names its feature and a credit entitlement its currency, both in
    # nested objects. The primary key needs them at the row root.
    feature = row.get("feature")
    currency = row.get("currency")
    row["featureId"] = feature.get("id") if isinstance(feature, dict) else None
    row["currencyId"] = currency.get("currencyId") if isinstance(currency, dict) else None
    return row


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_incremental_value(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _incremental_window(cursor_path: str, db_incremental_field_last_value: Optional[Any]) -> IncrementalConfig | None:
    # A first incremental sync has no watermark, so it reads the whole ledger and still merges.
    if db_incremental_field_last_value is None:
        return None
    return {"cursor_path": cursor_path, "start_param": "startDate", "convert": _format_incremental_value}


def _fanout_source(
    api_key: str,
    endpoint: str,
    config: StiggEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[StiggResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str],
) -> SourceResponse:
    assert config.fanout is not None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(StiggResumeConfig(fanout_state=state))

    child_endpoint_extra: Endpoint = {
        "data_selector": config.data_selector,
        "data_selector_malformed_retryable": True,
        # A child path that ends in a placeholder defaults to a single page, so name the paginator.
        "paginator": StiggCursorPaginator() if config.paginated else "single_page",
        # A parent deleted after the parent listing returns 404 here, so skip it.
        "response_actions": [{"status_code": 404, "action": "ignore"}],
    }

    resource = build_dependent_resource(
        endpoint_configs=STIGG_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=config.fanout,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
        should_use_incremental_field=should_use_incremental_field,
        incremental_field=incremental_field,
        incremental_config_factory=lambda cursor_path: _incremental_window(
            cursor_path, db_incremental_field_last_value
        ),
        # Only some child endpoints document `limit`, so the page size goes in per endpoint below.
        page_size_param=None,
        parent_endpoint_extra={"data_selector": "data", "data_selector_malformed_retryable": True},
        child_endpoint_extra=child_endpoint_extra,
        child_params_extra={config.page_size_param: config.page_size} if config.page_size_param else None,
        parent_data_map=_parent_filter(config.fanout.parent_name),
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
        resume_parent_pagination=True,
    )
    if endpoint == "customer_entitlements":
        resource = cast(Resource, resource).add_map(_lift_entitlement_keys)

    return SourceResponse(
        name=endpoint,
        items=lambda: cast(Resource, resource),
        primary_keys=config.primary_keys,
        **_partition_kwargs(config),
    )


def stigg_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[StiggResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = STIGG_ENDPOINTS[endpoint]
    if not should_use_incremental_field:
        db_incremental_field_last_value = None

    if config.fanout is not None:
        return _fanout_source(
            api_key,
            endpoint,
            config,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                    # A 200 whose body isn't the `{"data": [...]}` shape (a non-dict body or a
                    # missing/ non-list `data` key) is treated as transient — retry rather than
                    # fail loud or ingest the stray payload as a single garbage row.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next page (already-yielded pages are persisted) rather than skipping it; merge
        # dedupes the re-pulled page on the primary key.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(StiggResumeConfig(cursor=str(state["cursor"])))

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
        column_hints=resource.column_hints,
        **_partition_kwargs(config),
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # Server API keys are environment-wide, so probing one cheap endpoint validates access to
    # every list endpoint. The framework probe swallows transport errors and returns (ok, status).
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{STIGG_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        headers={"X-API-KEY": api_key, **_accept_header()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys."
    if status is None:
        return False, "Could not validate Stigg API key"
    return False, f"Stigg returned HTTP {status}"
