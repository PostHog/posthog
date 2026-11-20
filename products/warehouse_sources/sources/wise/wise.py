from collections.abc import Iterable
from typing import Any

from requests import Response
from requests.exceptions import RequestException

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    Endpoint,
    IncrementalConfig,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    parse_datetime_value,
    rest_api_resource,
)
from products.warehouse_sources.sources.wise.settings import BASE_URL, ENDPOINTS, WiseEndpoint

INVALID_TOKEN_MESSAGE = "Wise rejected your API token. Create a new personal API token in Wise and reconnect."
FORBIDDEN_MESSAGE = "Your Wise API token can't read this data. Check that the token belongs to a business account."


@frozen
class WiseResumeConfig:
    paginator_state: dict[str, Any] | None = None


class WiseCursorPaginator(JSONResponseCursorPaginator):
    """Stops on an empty page as well as on a missing cursor.

    The docs do not say whether the last page of recipients omits `seekPositionForNext`, so a page with no
    rows ends the walk even when it carries a cursor.
    """

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


def format_wise_datetime(value: Any) -> str | None:
    parsed = parse_datetime_value(value)
    if parsed is None:
        return None if value is None else str(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def _paginator(endpoint: WiseEndpoint) -> BasePaginator:
    if endpoint.pagination == "offset":
        return OffsetPaginator(
            limit=endpoint.page_size,
            limit_param=endpoint.page_size_param or "limit",
            total_path=None,
        )
    if endpoint.pagination == "cursor":
        assert endpoint.cursor_path is not None and endpoint.cursor_param is not None
        return WiseCursorPaginator(
            cursor_path=endpoint.cursor_path,
            cursor_param=endpoint.cursor_param,
            raise_on_repeated_cursor=True,
        )
    return SinglePagePaginator()


def _endpoint_extra(endpoint: WiseEndpoint) -> Endpoint:
    extra: Endpoint = {"paginator": _paginator(endpoint)}
    if endpoint.data_selector is not None:
        extra["data_selector"] = endpoint.data_selector
    return extra


def _child_params(endpoint: WiseEndpoint) -> dict[str, Any]:
    params = dict(endpoint.params)
    # The offset paginator sends its own page size.
    if endpoint.page_size_param is not None and endpoint.pagination != "offset":
        params[endpoint.page_size_param] = endpoint.page_size
    return params


def _client_config(token: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "bearer", "token": token},
        "paginator": SinglePagePaginator(),
    }


def wise_source(
    token: str,
    endpoint_name: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WiseResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    if endpoint_name not in ENDPOINTS:
        raise ValueError(f"Unknown Wise schema: {endpoint_name}")
    endpoint = ENDPOINTS[endpoint_name]
    client = _client_config(token)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_state = resume.paginator_state if resume else None

    def save_state(state: dict[str, Any] | None) -> None:
        resumable_source_manager.save_state(WiseResumeConfig(paginator_state=state))

    def incremental_config(cursor_field: str) -> IncrementalConfig | None:
        # The first sync sends no filter, so it reads the full history. Later syncs filter on the watermark.
        if endpoint.incremental_param is None or db_incremental_field_last_value is None:
            return None
        return {
            "cursor_path": cursor_field,
            "start_param": endpoint.incremental_param,
            "convert": format_wise_datetime,
        }

    resource: Iterable[Any]
    if endpoint.fanout is not None:
        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint.name,
            fanout=endpoint.fanout,
            client_config=client,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            incremental_config_factory=incremental_config,
            child_endpoint_extra=_endpoint_extra(endpoint),
            child_params_extra=_child_params(endpoint),
            # /profiles takes no page size, so the child page sizes go in child_params_extra.
            page_size_param=None,
            resume_hook=save_state,
            initial_paginator_state=initial_state,
        )
    else:
        resource = rest_api_resource(
            {
                "client": client,
                "resources": [
                    {
                        "name": endpoint.name,
                        "table_name": endpoint.name,
                        "write_disposition": "replace",
                        "endpoint": {"path": endpoint.path, **_endpoint_extra(endpoint)},
                        "table_format": "delta",
                    }
                ],
            },
            team_id,
            job_id,
            None,
        )

    return SourceResponse(
        name=endpoint.name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        # Rows arrive per profile, so they are never one ordered series.
        sort_mode=None,
    )


def _get(token: str, path: str, params: dict[str, Any] | None = None) -> Response:
    session = make_tracked_session(redact_values=(token,))
    return session.get(
        f"{BASE_URL}{path}",
        params=params,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30,
    )


def validate_credentials(token: str) -> tuple[bool, str | None]:
    try:
        response = _get(token, "/profiles")
    except RequestException as error:
        return False, f"Could not reach Wise: {error}"

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, INVALID_TOKEN_MESSAGE
    if response.status_code == 403:
        return False, FORBIDDEN_MESSAGE
    return False, f"Wise returned an unexpected response (HTTP {response.status_code})."


def get_endpoint_permissions(token: str, endpoint_names: list[str]) -> dict[str, str | None]:
    """Probe each table with the first profile. Only a 401 or 403 marks a table as unreachable."""
    permissions: dict[str, str | None] = dict.fromkeys(endpoint_names)
    try:
        profiles_response = _get(token, "/profiles")
    except RequestException:
        return permissions
    if profiles_response.status_code != 200:
        return permissions
    profiles = profiles_response.json()
    if not isinstance(profiles, list) or not profiles:
        return permissions
    profile_id = str(profiles[0]["id"])

    for name in endpoint_names:
        endpoint = ENDPOINTS.get(name)
        if endpoint is None or endpoint.fanout is None:
            continue
        path, _, query = endpoint.path.replace("{profile_id}", profile_id).partition("?")
        params: dict[str, Any] = dict(param.split("=", 1) for param in query.split("&") if param)
        params.update(endpoint.params)
        if endpoint.page_size_param is not None:
            params[endpoint.page_size_param] = 1
        try:
            status = _get(token, path, params).status_code
        except RequestException:
            continue
        if status in (401, 403):
            permissions[name] = FORBIDDEN_MESSAGE
    return permissions
