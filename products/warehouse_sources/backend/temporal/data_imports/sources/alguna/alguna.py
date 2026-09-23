import dataclasses
from collections.abc import Iterable, Iterator
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.settings import (
    ALGUNA_ENDPOINTS,
    PAGE_LIMIT,
    AlgunaEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

ALGUNA_BASE_URL = "https://api.alguna.io"
# Alguna's API is date-versioned; every request must send this header or calls fail.
ALGUNA_API_VERSION = "2026-04-01"


@dataclasses.dataclass
class AlgunaResumeConfig:
    # Row offset of the next unfetched page — Alguna list endpoints paginate with limit/offset.
    offset: int = 0


def _version_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs;
    # only the non-secret version/accept headers are set here.
    return {"Alguna-Version": ALGUNA_API_VERSION, "Accept": "application/json"}


def _offset_paginator() -> OffsetPaginator:
    # Alguna has no top-level `total`; termination is a short/empty page (OffsetPaginator default).
    return OffsetPaginator(limit=PAGE_LIMIT, total_path=None)


def _list_params(config: AlgunaEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_LIMIT}
    if config.sort is not None:
        params["sort"] = config.sort
    return params


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": ALGUNA_BASE_URL,
        "headers": _version_headers(),
        "auth": {"type": "bearer", "token": api_key},
        "paginator": _offset_paginator(),
    }


def _source_response(
    config: AlgunaEndpointConfig,
    items_fn: Any,
    column_hints: Any = None,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        column_hints=column_hints,
    )


def _top_level_source(
    api_key: str,
    config: AlgunaEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AlgunaResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": _list_params(config),
                    "data_selector": "data",
                    # A 200 body without `data` means the response shape changed — fail loud
                    # instead of silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(AlgunaResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, lambda: resource, column_hints=resource.column_hints)


def _declarative_fanout_source(
    api_key: str,
    config: AlgunaEndpointConfig,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    # Path-based fan-out (e.g. /subscriptions/{subscription_id}/versions) via the shared helper.
    # Fan-out endpoints don't resume: a retry re-syncs from scratch and the merge dedupes.
    assert config.fanout is not None
    parent_config = ALGUNA_ENDPOINTS[config.fanout.parent_name]
    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=ALGUNA_ENDPOINTS,
            child_endpoint=config.name,
            # The child path takes no page-size param, so the parent's limit rides parent_params.
            fanout=dataclasses.replace(config.fanout, parent_params=_list_params(parent_config)),
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            page_size_param=None,
            parent_endpoint_extra={
                "paginator": _offset_paginator(),
                "data_selector": "data",
                "data_selector_required": True,
            },
            child_endpoint_extra={
                "paginator": SinglePagePaginator(),
                "data_selector": "data",
                "data_selector_required": True,
            },
        ),
    )
    return _source_response(config, lambda: dependent_resource)


def _query_fanout_pages(
    client: RESTClient,
    config: AlgunaEndpointConfig,
    parent_config: AlgunaEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    fanout = config.query_fanout
    assert fanout is not None
    for parent_page in client.paginate(
        path=parent_config.path,
        params=_list_params(parent_config),
        paginator=_offset_paginator(),
        data_selector="data",
        data_selector_required=True,
    ):
        for parent in parent_page:
            parent_id = parent.get(fanout.parent_field)
            if parent_id is None:
                continue
            yield from client.paginate(
                path=config.path,
                params={fanout.query_param: parent_id, "limit": PAGE_LIMIT},
                paginator=_offset_paginator(),
                data_selector="data",
                data_selector_required=True,
            )


def _query_fanout_source(api_key: str, config: AlgunaEndpointConfig) -> SourceResponse:
    # Fan-out where the parent id is a required query param on the child (e.g.
    # /credit-notes?customer_id=...). Fan-out endpoints don't resume: a retry re-syncs from
    # scratch and the merge dedupes.
    assert config.query_fanout is not None
    parent_config = ALGUNA_ENDPOINTS[config.query_fanout.parent_name]
    client = RESTClient(
        base_url=ALGUNA_BASE_URL,
        headers=_version_headers(),
        auth=BearerTokenAuth(api_key),
        paginator=_offset_paginator(),
    )
    return _source_response(config, lambda: _query_fanout_pages(client, config, parent_config))


def alguna_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AlgunaResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ALGUNA_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _declarative_fanout_source(api_key, config, team_id, job_id, db_incremental_field_last_value)
    if config.query_fanout is not None:
        return _query_fanout_source(api_key, config)
    return _top_level_source(
        api_key, config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
    )


def validate_credentials(api_key: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ALGUNA_BASE_URL}/customers?limit=1&offset=0&sort=created_at:asc",
        headers={"Authorization": f"Bearer {api_key}", **_version_headers()},
    )
    return ok
