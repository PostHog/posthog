import re
from typing import Any

from requests import HTTPError, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientNonRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.testdino import (
    TestDinoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.settings import (
    API_BASE_URL,
    CASE_LIMIT_ERROR,
    ENDPOINTS,
    HTTP_ERRORS,
    INVALID_PROJECT,
    MANUAL_CASE_LIMIT,
)


@frozen
class TestDinoResumeConfig:
    page: int


def validate_project_id(project_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
        raise ValueError(INVALID_PROJECT)


class TestDinoRunPaginator(PageNumberPaginator):
    def __init__(self) -> None:
        super().__init__(base_page=1, stop_after_empty_page=False)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        has_next = response.json().get("pagination", {}).get("hasNext")
        if not isinstance(has_next, bool):
            raise RESTClientNonRetryableError("TestDino did not return pagination.hasNext.")
        super().update_state(response, data)
        self._has_next_page = has_next


class TestDinoCasePaginator(SinglePagePaginator):
    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if data is not None and len(data) >= MANUAL_CASE_LIMIT:
            raise RESTClientNonRetryableError(CASE_LIMIT_ERROR)
        super().update_state(response, data)


def validate_credentials(config: TestDinoSourceConfig) -> tuple[bool, str | None]:
    try:
        validate_project_id(config.project_id)
    except ValueError:
        return False, INVALID_PROJECT

    client = RESTClient(
        base_url=API_BASE_URL,
        auth=BearerTokenAuth(token=config.personal_access_token),
        paginator=SinglePagePaginator(),
        allow_redirects=False,
        request_timeout=30,
    )
    try:
        next(client.paginate(f"{config.project_id}/token-info", data_selector="data", data_selector_required=True))
    except HTTPError as error:
        if error.response is not None and error.response.status_code in HTTP_ERRORS:
            return False, HTTP_ERRORS[error.response.status_code]
        raise
    return True, None


def testdino_source(
    config: TestDinoSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[TestDinoResumeConfig],
) -> SourceResponse:
    validate_project_id(config.project_id)
    settings = schema_for_resource(ENDPOINTS, inputs.schema_name)
    endpoint: Endpoint = {
        "path": f"{config.project_id}/{settings.path}",
        "data_selector": "data",
        "data_selector_required": True,
        "paginator": "single_page",
    }
    initial_state: dict[str, Any] | None = None
    resumable = inputs.schema_name == "test_runs"
    if resumable:
        endpoint["paginator"] = TestDinoRunPaginator()
        endpoint["params"] = {"limit": 100, "sort": "counter_asc"}
        if manager.can_resume():
            saved = manager.load_state()
            if saved is not None:
                initial_state = {"page": saved.page}
    elif inputs.schema_name == "manual_cases":
        endpoint["paginator"] = TestDinoCasePaginator()
        endpoint["params"] = {"limit": MANUAL_CASE_LIMIT}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(TestDinoResumeConfig(page=int(state["page"])))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": API_BASE_URL,
            "auth": {"type": "bearer", "token": config.personal_access_token},
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resources": [{"name": inputs.schema_name, "endpoint": endpoint}],
    }
    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint if resumable else None,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=[settings.primary_key],
        sort_mode=None,
        supports_resume=resumable,
        on_complete=manager.clear_state if resumable else None,
    )
