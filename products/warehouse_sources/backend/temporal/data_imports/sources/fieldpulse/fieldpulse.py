from datetime import datetime
from typing import Any, cast

from requests import HTTPError, Response, Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.fieldpulse.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    PRIMARY_KEYS,
)


@frozen
class FieldpulseResumeConfig:
    page: int
    lower_bound: str | None


REQUEST_TIMEOUT = (10.0, 60.0)


def _normalize_rate_limit_header(response: Response, *args: object, **kwargs: object) -> Response:
    if response.status_code == 429 and "RateLimit-Reset" in response.headers:
        # The shared client parses epoch resets under the X-RateLimit-Reset header.
        response.headers["X-RateLimit-Reset"] = response.headers["RateLimit-Reset"]
    return response


def _session(api_key: str) -> Session:
    session = make_tracked_session(redact_values=(api_key,))
    session.hooks["response"].append(_normalize_rate_limit_header)
    return session


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(name="x-api-key", api_key=api_key, location="header"),
        paginator=SinglePagePaginator(),
        allow_redirects=False,
        session=_session(api_key),
        request_timeout=REQUEST_TIMEOUT,
    )
    try:
        next(client.paginate("customers", params={"limit": 1}, data_selector="response", data_selector_required=True))
    except HTTPError as error:
        if error.response is not None and error.response.status_code in (401, 403, 422):
            return False, AUTH_ERROR
        raise
    return True, None


def fieldpulse_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FieldpulseResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: str | datetime | None,
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    watermark = db_incremental_field_last_value if should_use_incremental_field else None
    lower_bound = watermark.isoformat() if isinstance(watermark, datetime) else watermark
    initial_state = None
    if resumable_source_manager.can_resume():
        saved = resumable_source_manager.load_state()
        if saved is not None:
            initial_state = {"page": saved.page}
            # Page offsets must use the original filter, even when the pipeline has advanced its watermark.
            lower_bound = saved.lower_bound if should_use_incremental_field else None

    params: dict[str, Any] = {
        "limit": PAGE_SIZE,
        "sort[0][attribute]": "updated_at" if should_use_incremental_field else "id",
        "sort[0][order]": "asc",
    }
    if should_use_incremental_field:
        params.update({"sort[1][attribute]": "id", "sort[1][order]": "asc"})
    if lower_bound is not None:
        params.update(
            {
                "filter[0][attribute]": "updated_at",
                "filter[0][operator]": ">=",
                "filter[0][class]": "date",
                "filter[0][value]": lower_bound,
            }
        )

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                FieldpulseResumeConfig(page=int(state["page"]), lower_bound=lower_bound)
            )
        resumable_source_manager.safe_point()

    client_config: ClientConfig = {
        "base_url": BASE_URL,
        "auth": {"type": "api_key", "name": "x-api-key", "api_key": api_key, "location": "header"},
        "paginator": cast(PaginatorConfig, {"type": "page_number", "base_page": 1, "total_path": None}),
        "allow_redirects": False,
        "session": _session(api_key),
        "request_timeout": REQUEST_TIMEOUT,
    }
    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "response",
        "data_selector_required": True,
    }
    resource_config: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
    config: RESTAPIConfig = {"client": client_config, "resources": [resource_config]}
    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS,
        sort_mode="asc" if should_use_incremental_field else None,
    )
