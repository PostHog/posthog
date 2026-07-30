import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.settings import LAMBDA_LABS_ENDPOINTS

# cloud.lambdalabs.com is a deprecated alias for the same API.
LAMBDA_LABS_BASE_URL = "https://cloud.lambda.ai/api/v1"


@dataclasses.dataclass
class LambdaLabsResumeConfig:
    # The `page_token` cursor of the next page to fetch. Lambda's cursor already encodes the query
    # window (the incremental `start` filter is only sent on the first request), so the token alone
    # is enough to resume mid-endpoint.
    page_token: str


def _format_iso8601(value: Any) -> str:
    """Format a datetime/date as an ISO 8601 UTC timestamp with a `Z` suffix (millisecond precision),
    which the Lambda API's `start`/`end` filters accept."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_iso8601(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


# `/instances` records carry a live JupyterLab access token (`jupyter_token`) and a URL that
# embeds the same token (`jupyter_url`). Either grants terminal access to the running instance, so
# they must never land in the warehouse where any project member with read access could retrieve
# them. Stripped from every record defensively, regardless of endpoint.
_SENSITIVE_FIELDS: frozenset[str] = frozenset({"jupyter_token", "jupyter_url"})


def _scrub_sensitive(record: dict[str, Any]) -> dict[str, Any]:
    if _SENSITIVE_FIELDS.isdisjoint(record):
        return record
    return {key: value for key, value in record.items() if key not in _SENSITIVE_FIELDS}


def _flatten_instance_type(value: dict[str, Any]) -> dict[str, Any]:
    """Turn one `/instance-types` map value into a flat row.

    The endpoint returns `data` as an object keyed by instance-type name; each value nests the
    catalog entry under `instance_type` alongside `regions_with_capacity_available`. We hoist the
    `instance_type` fields (which include `name`, the primary key) to the top level and keep the
    regional availability alongside them.

    A missing or malformed `instance_type` raises rather than yielding a row without its primary
    key, which would otherwise surface later as a warehouse load failure or a keyless bad row.
    """
    row = dict(value["instance_type"])
    row["regions_with_capacity_available"] = value.get("regions_with_capacity_available", [])
    return _scrub_sensitive(row)


def lambda_labs_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LambdaLabsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LAMBDA_LABS_ENDPOINTS[endpoint]

    # `data` is an object keyed by id for the map endpoint (`/instance-types`); `data.*` selects its
    # values so each becomes a row. Every other endpoint wraps its list under `records_path`.
    data_selector = f"{config.records_path}.*" if config.is_map else config.records_path

    paginator: BasePaginator
    if config.page_token_path:
        paginator = JSONResponseCursorPaginator(cursor_path=config.page_token_path, cursor_param="page_token")
    else:
        # Unpaginated endpoints return the whole collection in one response.
        paginator = SinglePagePaginator()

    params: dict[str, Any] = {}
    initial_paginator_state: Optional[dict[str, Any]] = None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume is not None and resume.page_token:
        # Mid-endpoint resume: the cursor already encodes the query window, so only the token is sent.
        initial_paginator_state = {"cursor": resume.page_token}
    elif config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        # `start` is inclusive, so the boundary event is re-fetched and deduped on the primary key.
        params["start"] = _format_iso8601(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": LAMBDA_LABS_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so the key is redacted from logs
            # and raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": data_selector,
                    "paginator": paginator,
                },
                # Strip the JupyterLab token from every record; the map endpoint also flattens its
                # nested catalog entry (which scrubs too).
                "data_map": _flatten_instance_type if config.is_map else _scrub_sensitive,
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes the overlap on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(LambdaLabsResumeConfig(page_token=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental filtering is injected manually into `params` above (Lambda only exposes it on
        # `audit-events`), so the framework's incremental machinery is intentionally unused.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # audit-events pages forward from `start` via an ascending timestamp cursor; the unpaginated
        # full-refresh endpoints don't use the watermark, so asc is a safe default for them too.
        sort_mode="asc",
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is accepted with one cheap, account-wide read (`/ssh-keys`).

    Returns False only on a definitive auth rejection (401/403). A network error, timeout, or
    5xx propagates so the caller can tell an invalid key apart from a temporary Lambda outage
    rather than reporting the latter as an invalid key.
    """
    response = make_tracked_session(redact_values=(api_key,)).get(
        f"{LAMBDA_LABS_BASE_URL}/ssh-keys",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=10,
    )
    if response.status_code in (401, 403):
        return False
    response.raise_for_status()
    return True
