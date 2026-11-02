from collections.abc import Iterator
from datetime import UTC, datetime
from functools import partial
from typing import Any

from requests import PreparedRequest, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.imperva import (
    ImpervaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.settings import (
    AUTH_ERROR,
    BASE_URL,
    DAY_MS,
    HISTORY_DAYS,
    PERMISSION_ERROR,
    PLAN_ERROR,
    PRIMARY_KEYS,
    SITES_BASE_URL,
)


@frozen
class ImpervaResumeConfig:
    page: int


class ImpervaAuth(APIKeyAuth):
    def __init__(self, config: ImpervaSourceConfig) -> None:
        super().__init__(api_key=config.api_key, name="x-API-Key")
        self.api_id_auth = APIKeyAuth(api_key=config.api_id, name="x-API-Id")

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        return self.api_id_auth(super().__call__(request))

    def secret_values(self) -> tuple[str, ...]:
        return (*super().secret_values(), *self.api_id_auth.secret_values())


class ImpervaAPIError(Exception):
    def __init__(self, code: int) -> None:
        self.code = code
        if code == 9411:
            message = AUTH_ERROR
        elif code in (9403, 9413, 9415):
            message = PERMISSION_ERROR
        elif code == 9414:
            message = PLAN_ERROR
        else:
            message = f"Imperva returned API error {code}. Check the account settings or contact Imperva support."
        super().__init__(message)


def check_response(response: Response, *, selector: str, **kwargs: Any) -> Response:
    if response.status_code != 200:
        return response
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Imperva returned an invalid response. Try the sync again.")
    code = body.get("res", 0) if selector == "data" else body.get("res")
    if not isinstance(code, int):
        raise ValueError("Imperva returned an invalid response. Try the sync again.")
    if code in (1, 4):
        raise RESTClientRetryableError("Imperva returned a temporary API error. Try the sync again.")
    if code != 0:
        raise ImpervaAPIError(code)
    if not isinstance(body.get(selector), list):
        raise ValueError("Imperva returned an invalid table response. Try the sync again.")
    return response


def make_resource(
    config: ImpervaSourceConfig,
    name: str,
    *,
    api_version: str,
    team_id: int,
    job_id: str,
    watermark: int | None = None,
    manager: ResumableSourceManager[ImpervaResumeConfig] | None = None,
    probe: bool = False,
) -> Resource:
    if name not in PRIMARY_KEYS:
        raise ValueError(f"Unknown Imperva table: {name}")
    endpoint: Endpoint
    if name == "sites":
        endpoint = {
            "method": "GET",
            "params": {"caid": config.account_id, "size": 1 if probe else 100},
            "path": f"/{api_version}/sites",
            "paginator": "single_page"
            if probe
            else {"type": "page_number", "page_param": "page", "total_path": "meta.totalPages"},
            "data_selector": "data",
            "data_selector_required": True,
        }
    else:
        end = int(datetime.now(UTC).timestamp() * 1000)
        today = end // DAY_MS * DAY_MS
        start = today - HISTORY_DAYS * DAY_MS
        if watermark is not None:
            # Daily buckets can change during the day, so read the previous day again.
            start = max(start, watermark // DAY_MS * DAY_MS - DAY_MS)
        if probe:
            start = today
        endpoint = {
            "method": "POST",
            "params": {
                "account_id": config.account_id,
                "time_range": "custom",
                "start": min(start, today),
                "end": end,
                "granularity": DAY_MS,
                "stats": name,
            },
            # Imperva still exposes traffic statistics through v1 alongside the v3 site API.
            "path": "/api/stats/v1",
            "paginator": "single_page",
            "data_selector": name,
            "data_selector_required": True,
        }

    auth = ImpervaAuth(config)
    session = make_tracked_session(redact_values=auth.secret_values())
    session.hooks["response"].append(partial(check_response, selector="data" if name == "sites" else name))
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SITES_BASE_URL if name == "sites" else BASE_URL,
            "auth": auth,
            "session": session,
            "allowed_hosts": [],
            "request_timeout": (10.0, 60.0),
        },
        "resources": [{"name": name, "endpoint": endpoint}],
    }
    resume = manager.load_state() if manager is not None and name == "sites" and manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if manager is not None:
            manager.safe_point()
            if state is not None:
                manager.save_state(ImpervaResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint if name == "sites" and manager is not None else None,
        initial_paginator_state={"page": resume.page} if resume is not None else None,
    )
    if name != "sites":

        def flatten_series(series: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                {
                    "account_id": config.account_id,
                    "id": series["id"],
                    "name": series.get("name"),
                    "timestamp": int(point[0]),
                    "value": point[1],
                }
                for point in series["data"]
            ]

        resource.add_map(flatten_series)
    return resource


def imperva_source(
    config: ImpervaSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[ImpervaResumeConfig],
    api_version: str,
) -> SourceResponse:
    resource = make_resource(
        config,
        inputs.schema_name,
        api_version=api_version,
        team_id=inputs.team_id,
        job_id=inputs.job_id,
        watermark=int(inputs.db_incremental_field_last_value)
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None
        else None,
        manager=manager,
    )

    def items() -> Iterator[list[dict[str, Any]]]:
        yield from resource

    return SourceResponse(
        name=inputs.schema_name,
        items=items,
        primary_keys=PRIMARY_KEYS[inputs.schema_name],
        sort_mode="desc",
        supports_resume=inputs.schema_name == "sites",
    )
