from typing import Any, Optional

from requests import Response
from requests.exceptions import RequestException

from products.warehouse_sources.sources.creem.settings import (
    CREEM_ENDPOINTS,
    PRODUCTION_BASE_URL,
    TEST_BASE_URL,
    CreemEndpointConfig,
    CreemEnvironment,
    CreemPagination,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    EndpointResource,
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    capture_exception,
    frozen,
    make_tracked_session,
    rest_api_resource,
)

INVALID_KEY_ERROR = (
    "Creem rejected your API key. Check that you copied the whole key and chose the environment it belongs to: "
    "a test mode key works only with Test, and a live key only with Production."
)
UNREACHABLE_ERROR = "PostHog couldn't reach Creem to check your API key. Wait a few minutes, then try again."
UNVERIFIED_KEY_ERROR = "PostHog couldn't verify your Creem API key. Check the key, then try again."

# (connect, read) seconds for the one-request credential probe.
PROBE_TIMEOUT = (10, 30)


@frozen
class CreemResumeConfig:
    # Page-number listings: the next page to fetch.
    page_number: Optional[int] = None
    # Cursor listings: the id of the last row already read.
    starting_after: Optional[str] = None
    # Licenses: the state `build_dependent_resource` checkpoints over the customer listing.
    fanout_state: Optional[dict[str, Any]] = None


def base_url(environment: str) -> str:
    return TEST_BASE_URL if environment == CreemEnvironment.TEST else PRODUCTION_BASE_URL


class CreemPageNumberPaginator(PageNumberPaginator):
    """Follows `pagination.next_page`, which Creem sets to null on the last page."""

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page_number")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except ValueError:
            body = None
        pagination = body.get("pagination") if isinstance(body, dict) else None
        if not isinstance(pagination, dict) or "next_page" not in pagination:
            # No pagination envelope: walk pages until one comes back empty.
            super().update_state(response, data)
            return

        next_page = pagination["next_page"]
        if not data or not isinstance(next_page, int | float) or int(next_page) <= self.page:
            self._has_next_page = False
            return

        self.page = int(next_page)
        self._has_next_page = True


class CreemCursorPaginator(JSONResponseCursorPaginator):
    """Sends the id of the last row as `starting_after` while the response says `has_more`.

    The cursor is not a body field, so only `update_state` differs from the parent paginator.
    """

    def __init__(self) -> None:
        super().__init__(cursor_param="starting_after")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except ValueError:
            body = None
        has_more = isinstance(body, dict) and body.get("has_more") is True
        last_id = data[-1].get("id") if data and isinstance(data[-1], dict) else None
        if not has_more or not last_id or last_id == self._cursor_value:
            self._has_next_page = False
            return

        self._previous_cursor_value = self._cursor_value
        self._cursor_value = str(last_id)
        self._has_next_page = True


def _paginator(config: CreemEndpointConfig) -> BasePaginator:
    if config.pagination == CreemPagination.CURSOR:
        return CreemCursorPaginator()
    return CreemPageNumberPaginator()


def _client_config(api_key: str, environment: str) -> ClientConfig:
    return {
        "base_url": base_url(environment),
        "auth": {
            "type": "api_key",
            "name": "x-api-key",
            "api_key": api_key,
            "location": "header",
        },
        # The `x-api-key` header must never follow a redirect to another host.
        "allowed_hosts": [],
        "allow_redirects": False,
        # License rows carry each license key under `key`, a name the sample scrubber leaves as is,
        # so keep Creem bodies out of HTTP sample capture.
        "capture": False,
    }


def get_resource(config: CreemEndpointConfig) -> EndpointResource:
    return {
        "name": config.name,
        "table_name": config.name.lower(),
        "write_disposition": "replace",
        "endpoint": {
            "path": config.path,
            "params": {config.page_size_param: config.page_size, **config.params},
            "data_selector": config.data_selector,
            "data_selector_required": True,
            "paginator": _paginator(config),
        },
        "table_format": "delta",
    }


def _load_resume_state(manager: ResumableSourceManager[CreemResumeConfig]) -> Optional[CreemResumeConfig]:
    if not manager.can_resume():
        return None
    return manager.load_state()


def _initial_paginator_state(
    config: CreemEndpointConfig, resume_state: Optional[CreemResumeConfig]
) -> Optional[dict[str, Any]]:
    if resume_state is None:
        return None
    if config.pagination == CreemPagination.CURSOR and resume_state.starting_after:
        return {"cursor": resume_state.starting_after}
    if config.pagination == CreemPagination.PAGE_NUMBER and resume_state.page_number:
        return {"page": resume_state.page_number}
    return None


def _save_paginator_state(manager: ResumableSourceManager[CreemResumeConfig], state: Optional[dict[str, Any]]) -> None:
    if not state:
        return
    if state.get("cursor"):
        manager.save_state(CreemResumeConfig(starting_after=str(state["cursor"])))
    elif state.get("page") is not None:
        manager.save_state(CreemResumeConfig(page_number=int(state["page"])))


def _save_fanout_state(manager: ResumableSourceManager[CreemResumeConfig], state: Optional[dict[str, Any]]) -> None:
    if state:
        manager.save_state(CreemResumeConfig(fanout_state=state))


def creem_source(
    api_key: str,
    environment: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CreemResumeConfig],
) -> SourceResponse:
    config = CREEM_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"Unknown Creem endpoint: {endpoint}")

    client_config = _client_config(api_key, environment)
    resume_state = _load_resume_state(resumable_source_manager)

    response_kwargs: dict[str, Any] = {
        "name": config.name,
        "primary_keys": config.primary_keys,
        "partition_mode": "datetime" if config.partition_key else None,
        "partition_format": "month" if config.partition_key else None,
        "partition_keys": [config.partition_key] if config.partition_key else None,
    }

    if config.fanout is not None:
        parent_config = CREEM_ENDPOINTS[config.fanout.parent_name]
        child = build_dependent_resource(
            endpoint_configs=CREEM_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param="page_size",
            parent_endpoint_extra={
                "data_selector": parent_config.data_selector,
                "data_selector_required": True,
                "paginator": _paginator(parent_config),
            },
            child_endpoint_extra={
                "data_selector": config.data_selector,
                "data_selector_required": True,
                "paginator": _paginator(config),
            },
            resume_hook=lambda state: _save_fanout_state(resumable_source_manager, state),
            initial_paginator_state=resume_state.fanout_state if resume_state else None,
            # The customer listing can save its page, so a resume starts there instead of keeping every
            # finished customer in the state.
            resume_parent_pagination=True,
        )
        return SourceResponse(items=lambda: child, **response_kwargs)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [get_resource(config)],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=lambda state: _save_paginator_state(resumable_source_manager, state),
        initial_paginator_state=_initial_paginator_state(config, resume_state),
    )
    return SourceResponse(items=lambda: resource, column_hints=resource.column_hints, **response_kwargs)


def validate_credentials(api_key: str, environment: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_key,))
    try:
        response = session.get(
            f"{base_url(environment)}{CREEM_ENDPOINTS['Products'].path}",
            params={"page_number": 1, "page_size": 1},
            headers={"x-api-key": api_key},
            allow_redirects=False,
            timeout=PROBE_TIMEOUT,
        )
    except RequestException:
        return False, UNREACHABLE_ERROR

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, INVALID_KEY_ERROR
    capture_exception(Exception(f"Unexpected Creem credential validation response ({response.status_code})"))
    return False, UNVERIFIED_KEY_ERROR
