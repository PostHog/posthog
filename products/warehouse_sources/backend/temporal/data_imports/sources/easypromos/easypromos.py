import dataclasses
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
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
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.settings import (
    EASYPROMOS_ENDPOINTS,
    EasypromosEndpointConfig,
)

EASYPROMOS_BASE_URL = "https://api.easypromosapp.com/v2"

# Easypromos wraps lists as `{"items": [...], "paging": {"next_cursor": <int|null>, "items_page": 100}}`;
# a null `next_cursor` marks the last page. The cursor is echoed back as the `next_cursor` query param.
_CURSOR_PATH = "paging.next_cursor"
_CURSOR_PARAM = "next_cursor"
_DATA_SELECTOR = "items"

# The parent id injected into every fan-out child row so the composite primary key is unique across
# promotions. `include_from_parent` surfaces the parent field under this prefixed name first.
_PARENT_ID_KEY = "_promotions_id"


@dataclasses.dataclass
class EasypromosResumeConfig:
    # Simple (top-level) endpoints checkpoint the cursor of the next page to fetch.
    cursor: int | None = None
    # Retained for backwards compatibility with resume state written by the previous hand-rolled
    # fan-out implementation. Unused by the rest_source framework path, which stores its fan-out
    # checkpoint in `fanout_state`; when only these legacy fields are present the fan-out restarts
    # fresh (the merge dedupes on primary key).
    promotion_id: int | None = None
    child_cursor: int | None = None
    # Fan-out checkpoint managed by the framework's dependent-resource resume:
    # `{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}`.
    fanout_state: dict[str, Any] | None = None


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so the token is redacted from logs;
    # only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _client_config(access_token: str) -> ClientConfig:
    return {
        "base_url": EASYPROMOS_BASE_URL,
        "headers": _headers(),
        "auth": {"type": "bearer", "token": access_token},
    }


def _cursor_paginator() -> JSONResponseCursorPaginator:
    return JSONResponseCursorPaginator(cursor_path=_CURSOR_PATH, cursor_param=_CURSOR_PARAM)


def _inject_promotion_id(row: dict[str, Any]) -> dict[str, Any]:
    if _PARENT_ID_KEY in row:
        row["promotion_id"] = row.pop(_PARENT_ID_KEY)
    return row


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    """One cheap probe of the account-wide Bearer token against `/promotions`."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{EASYPROMOS_BASE_URL}/promotions",
        headers={"Authorization": f"Bearer {access_token}", **_headers()},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Easypromos access token"
    if status == 403:
        # Valid token, but the account plan can't reach the REST API (Basic/Premium) or lacks
        # access to this resource. Surface it rather than silently failing.
        return False, "Your Easypromos plan does not have access to the REST API (requires White Label or Corporate)"
    if status is None:
        return False, "Could not reach the Easypromos API"
    return False, f"Easypromos API returned status {status}"


def _source_response(endpoint_config: EasypromosEndpointConfig, items_fn) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def _fan_out_resource(
    access_token: str,
    endpoint_config: EasypromosEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EasypromosResumeConfig],
):
    """Walk `/promotions` and emit child rows per promotion via a single-hop dependent resource.

    `promotion_id` is injected into every child row (from the parent's `id`) so the composite
    primary key is unique across promotions — identical to the old hand-rolled fan-out.
    """
    promotions_config = EASYPROMOS_ENDPOINTS["promotions"]

    parent_resource: EndpointResource = {
        "name": "promotions",
        "table_name": "promotions",
        "write_disposition": "replace",
        "endpoint": {
            "path": promotions_config.path,
            "data_selector": _DATA_SELECTOR,
            "paginator": _cursor_paginator(),
        },
        "table_format": "delta",
    }

    # The resolve param binds the parent `id` into the `{promotion_id}` path placeholder; the same
    # id is surfaced into each child row via include_from_parent (then renamed to `promotion_id`).
    child_resource: EndpointResource = {
        "name": endpoint_config.name,
        "table_name": endpoint_config.name,
        "write_disposition": "replace",
        "include_from_parent": ["id"],
        "endpoint": {
            "path": endpoint_config.path,
            "params": {
                "promotion_id": {"type": "resolve", "resource": "promotions", "field": "id"},
            },
            "data_selector": _DATA_SELECTOR,
            "paginator": _cursor_paginator(),
        },
        "table_format": "delta",
    }

    config: RESTAPIConfig = {
        "client": _client_config(access_token),
        "resource_defaults": {},
        "resources": [parent_resource, child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(EasypromosResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    child = next(r for r in resources if getattr(r, "name", None) == endpoint_config.name)
    return child.add_map(_inject_promotion_id)


def _top_level_resource(
    access_token: str,
    endpoint_config: EasypromosEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EasypromosResumeConfig],
):
    """Page through a top-level list endpoint (`/promotions`, `/organizing_brands`)."""
    config: RESTAPIConfig = {
        "client": _client_config(access_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint_config.name,
                "endpoint": {
                    "path": endpoint_config.path,
                    "data_selector": _DATA_SELECTOR,
                    "paginator": _cursor_paginator(),
                },
                "write_disposition": "replace",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the checkpointed page (merge dedupes) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(EasypromosResumeConfig(cursor=int(state["cursor"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def easypromos_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EasypromosResumeConfig],
) -> SourceResponse:
    endpoint_config = EASYPROMOS_ENDPOINTS[endpoint]

    if endpoint_config.fan_out_over_promotions:
        resource = cast(
            Any, _fan_out_resource(access_token, endpoint_config, team_id, job_id, resumable_source_manager)
        )
    else:
        resource = _top_level_resource(access_token, endpoint_config, team_id, job_id, resumable_source_manager)

    return _source_response(endpoint_config, lambda: resource)
