from collections.abc import Iterator
from datetime import UTC
from typing import Any

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.poplar.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PoplarEndpoint,
)

REQUEST_TIMEOUT_SECONDS = 30


@frozen
class PoplarResumeConfig:
    paginator_state: dict[str, Any] | None = None


class PoplarPagePaginator(PageNumberPaginator):
    """Stops on `total_pages` in the body (stats) or on an empty `X-Next-Page` header (mailings).

    When a response carries neither, the walk ends at the first empty page.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, total_path="total_pages")

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        super().update_state(response, data)
        next_page = response.headers.get("X-Next-Page")
        if self._has_next_page and next_page is not None:
            self._has_next_page = bool(next_page.strip())


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{BASE_URL}/me",
        auth=BearerTokenAuth(access_token),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, AUTH_ERROR
    if status is None:
        return False, "Could not connect to Poplar. Try again in a few minutes."
    return False, f"Poplar returned HTTP {status}. Try again in a few minutes."


def endpoint_config(endpoint: PoplarEndpoint) -> Endpoint:
    return {
        "path": endpoint.path,
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "paginator": PoplarPagePaginator() if endpoint.page_size else SinglePagePaginator(),
    }


def request_params(endpoint: PoplarEndpoint, inputs: SourceInputs) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if endpoint.page_size:
        params["per_page"] = endpoint.page_size
    # A mailing changes state after it is created and its rows carry no `updated_at`, so the
    # `created_at` cursor cannot bound the request. The previous sync started at `last_synced_at`,
    # so every later change is at or after it. A stored cursor is also required, because it proves
    # that an incremental sync already filled the table.
    if (
        endpoint.incremental_fields
        and inputs.should_use_incremental_field
        and inputs.db_incremental_field_last_value is not None
        and inputs.last_synced_at is not None
    ):
        params["start_date"] = inputs.last_synced_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        params["date_field"] = "updated_at"
    return params


def poplar_source(
    access_token: str, inputs: SourceInputs, manager: ResumableSourceManager[PoplarResumeConfig]
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)

    def rows() -> Iterator[list[dict[str, Any]]]:
        client: ClientConfig = {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": access_token},
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            # Mailings carry recipient names and postal addresses that the sample scrubbers cannot spot.
            "capture": False,
        }
        params = request_params(endpoint, inputs)
        if endpoint.fanout is None:
            yield from rest_api_resource(
                {
                    "client": client,
                    "resources": [
                        {
                            "name": endpoint.name,
                            "endpoint": {**endpoint_config(endpoint), "params": params},
                            "table_format": "delta",
                        }
                    ],
                },
                inputs.team_id,
                inputs.job_id,
                None,
            )
            return

        resume = manager.load_state() if manager.can_resume() else None
        yield from build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint.name,
            fanout=endpoint.fanout,
            client_config=client,
            path_format_values={},
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=endpoint_config(ENDPOINTS[endpoint.fanout.parent_name]),
            child_endpoint_extra=endpoint_config(endpoint),
            child_params_extra=params,
            page_size_param=None,
            resume_hook=lambda state: manager.save_state(PoplarResumeConfig(paginator_state=state)),
            initial_paginator_state=resume.paginator_state if resume else None,
        )

    return SourceResponse(
        name=endpoint.name,
        items=rows,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        # Rows arrive campaign by campaign and the order inside a campaign is not documented.
        # "desc" makes the pipeline commit the cursor only after the whole sync completes.
        sort_mode="desc" if endpoint.incremental_fields else None,
        supports_resume=endpoint.fanout is not None,
    )
