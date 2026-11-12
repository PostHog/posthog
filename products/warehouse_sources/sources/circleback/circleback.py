from collections.abc import Callable, Iterable
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlencode, urlparse

from requests import Response

from products.warehouse_sources.sources.circleback.settings import CIRCLEBACK_ENDPOINTS, CirclebackEndpointConfig
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    EndpointResource,
    HeaderLinkPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

CIRCLEBACK_BASE_URL = "https://circleback.ai/api"


@frozen
class CirclebackResumeConfig:
    next_url: str | None = None
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


class CirclebackStatusPassPaginator(HeaderLinkPaginator):
    def __init__(self, next_pass_urls: dict[str, str]) -> None:
        super().__init__()
        self._next_pass_urls = next_pass_urls

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page:
            return
        status = parse_qs(urlparse(response.url).query).get("status", [""])[0]
        next_pass_url = self._next_pass_urls.get(status)
        if next_pass_url:
            self._advance_to(next_pass_url)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CIRCLEBACK_BASE_URL}{CIRCLEBACK_ENDPOINTS['tags'].path}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )

    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Circleback didn't accept this API key. Create a new key in Circleback under Settings > API keys."
    if status is None:
        return False, "Couldn't reach the Circleback API. Try again in a few minutes."

    return False, f"The Circleback API returned an unexpected status code ({status}). Try again in a few minutes."


def _client_config(api_key: str, config: CirclebackEndpointConfig) -> ClientConfig:
    return {
        "base_url": CIRCLEBACK_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": HeaderLinkPaginator(),
        "allowed_hosts": [],
        "allow_redirects": False,
        "capture": config.capture,
    }


def _initial_params(config: CirclebackEndpointConfig) -> dict[str, Any]:
    if not config.status_passes:
        return config.params
    return {**config.params, "status": config.status_passes[0]}


def _paginator(config: CirclebackEndpointConfig) -> BasePaginator:
    if not config.status_passes:
        return HeaderLinkPaginator()
    passes = config.status_passes
    return CirclebackStatusPassPaginator(
        {
            current: f"{CIRCLEBACK_BASE_URL}{config.path}?{urlencode({**config.params, 'status': following})}"
            for current, following in zip(passes, passes[1:])
        }
    )


def _drop_fields(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def drop(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in fields}

    return drop


def _source_response(config: CirclebackEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _fanout_source(
    config: CirclebackEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CirclebackResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                CirclebackResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=CIRCLEBACK_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key, config),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    return _source_response(config, lambda: resource)


def circleback_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CirclebackResumeConfig],
) -> SourceResponse:
    config = CIRCLEBACK_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(config, api_key, team_id, job_id, resumable_source_manager)

    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": _initial_params(config),
            "paginator": _paginator(config),
            "data_selector_required": True,
        },
    }
    if config.excluded_fields:
        resource_config["data_map"] = _drop_fields(config.excluded_fields)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, config),
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("next_url"):
            resumable_source_manager.save_state(CirclebackResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, lambda: resource)
