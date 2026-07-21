from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.settings import (
    COHERE_ENDPOINTS,
    CohereEndpointConfig,
    CoherePagination,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

# Cohere serves a single global API host; there are no regional variants.
COHERE_BASE_URL = "https://api.cohere.com/v1"


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs;
    # only the non-secret accept header is set here.
    return {"Accept": "application/json"}


def _build_paginator(config: CohereEndpointConfig) -> BasePaginator:
    if config.pagination == CoherePagination.NONE:
        # /embed-jobs returns every row in a single unpaginated request.
        return SinglePagePaginator()
    if config.pagination == CoherePagination.OFFSET:
        # ?limit=&offset= — terminate when a page returns fewer rows than the page size (total_path
        # is None, so the paginator stops on a short/empty page).
        return OffsetPaginator(
            limit=config.page_size,
            offset_param="offset",
            limit_param="limit",
            total_path=None,
        )
    # PAGE_TOKEN: ?page_size=&page_token= with a next_page_token in the body — terminate when the
    # response omits the token.
    return JSONResponseCursorPaginator(cursor_path=config.next_token_key, cursor_param="page_token")


def cohere_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = COHERE_ENDPOINTS[endpoint]
    partitioned = config.partition_key is not None

    params: dict[str, Any] = {}
    if config.pagination == CoherePagination.PAGE_TOKEN:
        # The cursor param is injected by the paginator; the static page size is a plain query param.
        params["page_size"] = config.page_size

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": COHERE_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": _build_paginator(config),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_key,
                    # A successful response that omits the envelope key is a shape mismatch, not empty
                    # data. Every Cohere schema is full-refresh-only, so silently treating a missing
                    # key as an empty page would clear the existing warehouse table; fail loud instead.
                    "data_selector_required": True,
                },
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    # Leave every partition field unset for endpoints without a creation timestamp (the model
    # catalog). Setting partition_count/size here would make the warehouse writer fall back to
    # primary_keys and md5-partition the table by `name`; None keeps it unpartitioned as intended.
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1 if partitioned else None,
        partition_size=1 if partitioned else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="month" if partitioned else None,
        partition_keys=[config.partition_key] if config.partition_key is not None else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    # /models is the cheapest authenticated probe: a 200 confirms the key is genuine without
    # touching a user's data. An invalid key returns 401 ("invalid api token").
    # `redact_values` masks the API key in logged URLs and captured HTTP samples.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{COHERE_BASE_URL}/models?page_size=1",
        headers={"Authorization": f"Bearer {api_key}", **_headers()},
    )
    return ok
