from dataclasses import replace
from typing import Any, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginatorConfig,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_data.settings import (
    ENDPOINTS,
    FANOUT_PARENTS,
)

AUTH_ERROR = "YouTube credentials are invalid or expired. Check your Google API key."
ACCESS_ERROR = "YouTube access was denied. Enable YouTube Data API v3 and check your API key restrictions."
QUOTA_ERROR = "YouTube quota exceeded. Wait for the daily reset or increase the quota in Google Cloud."
REQUEST_ERROR = "YouTube rejected the request. Check your API key and channel ID."
NOT_FOUND_ERROR = "YouTube could not find the requested data. Check that the channel and playlists are public."
COMMENTS_ERROR = "YouTube comments are disabled. Deselect the comment_threads table."

CURSOR_PAGINATOR: JSONResponseCursorPaginatorConfig = {
    "type": "cursor",
    "cursor_path": "nextPageToken",
    "cursor_param": "pageToken",
    "raise_on_repeated_cursor": True,
}

RESPONSE_ACTIONS: list[ResponseAction] = [
    {"status_code": 403, "content": "quotaExceeded", "action": "raise", "message": QUOTA_ERROR},
    {"status_code": 403, "content": "dailyLimitExceeded", "action": "raise", "message": QUOTA_ERROR},
    {"status_code": 403, "content": "commentsDisabled", "action": "raise", "message": COMMENTS_ERROR},
    {"status_code": 400, "action": "raise", "message": REQUEST_ERROR},
    {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
    {"status_code": 403, "action": "raise", "message": ACCESS_ERROR},
    {"status_code": 404, "action": "raise", "message": NOT_FOUND_ERROR},
]


@frozen
class YoutubeDataResumeConfig:
    paginator_state: dict[str, Any]


def client_config(api_key: str, api_version: str) -> ClientConfig:
    return {
        "base_url": f"https://www.googleapis.com/youtube/{api_version}/",
        "auth": {"type": "api_key", "name": "key", "api_key": api_key, "location": "query"},
        "paginator": CURSOR_PAGINATOR,
    }


def resource_config(name: str, channel_id: str) -> EndpointResource:
    settings = ENDPOINTS[name]
    params: dict[str, Any] = {"part": settings.part, **settings.params}
    if name == "channels":
        params["id"] = channel_id
    elif name == "playlists":
        params["channelId"] = channel_id
    elif name == "comment_threads":
        params["allThreadsRelatedToChannelId"] = channel_id

    endpoint: Endpoint = {
        "path": settings.path,
        "params": params,
        "paginator": CURSOR_PAGINATOR,
        "data_selector": "items",
        "data_selector_required": True,
        "response_actions": RESPONSE_ACTIONS,
    }
    return {
        "name": name,
        "table_name": name,
        "primary_key": list(settings.primary_keys),
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": endpoint,
    }


def fetch_channel(api_key: str, channel_id: str, team_id: int, api_version: str) -> dict[str, Any]:
    resource = resource_config("channels", channel_id)
    endpoint = cast(Endpoint, resource["endpoint"])
    endpoint["params"] = {"part": "contentDetails", "id": channel_id}
    endpoint["paginator"] = "single_page"
    config: RESTAPIConfig = {"client": client_config(api_key, api_version), "resources": [resource]}
    for page in rest_api_resource(config, team_id, "youtube_data_channel_probe", None):
        if page:
            return page[0]
    raise ValueError("YouTube channel was not found. Enter a public channel ID, not a handle or URL.")


def youtube_data_source(
    *,
    api_key: str,
    channel_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[YoutubeDataResumeConfig],
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unsupported YouTube table: {endpoint}")

    initial_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        saved = resumable_source_manager.load_state()
        if saved is not None:
            initial_state = saved.paginator_state

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(YoutubeDataResumeConfig(paginator_state=state))

    settings = ENDPOINTS[endpoint]
    fanout = settings.fanout
    if fanout is not None:
        parent = FANOUT_PARENTS[fanout.parent_name]
        parent_params: dict[str, Any] = {"part": parent.part, **parent.params}
        if endpoint == "videos":
            channel = fetch_channel(api_key, channel_id, team_id, api_version)
            resumable_source_manager.safe_point()
            uploads_id = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            if not uploads_id:
                raise ValueError("YouTube uploads playlist was not found. Check that the channel is public.")
            parent_params["playlistId"] = uploads_id
        else:
            parent_params["channelId"] = channel_id
        endpoint_extra: Endpoint = {
            "data_selector": "items",
            "data_selector_required": True,
            "response_actions": RESPONSE_ACTIONS,
            "paginator": CURSOR_PAGINATOR,
        }
        selected = build_dependent_resource(
            endpoint_configs={**FANOUT_PARENTS, **ENDPOINTS},
            child_endpoint=endpoint,
            fanout=replace(fanout, parent_params=parent_params),
            client_config=client_config(api_key, api_version),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=endpoint_extra,
            child_endpoint_extra={**endpoint_extra, "paginator": "single_page"}
            if endpoint == "videos"
            else endpoint_extra,
            child_params_extra={"part": settings.part, **settings.params},
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )
    else:
        config: RESTAPIConfig = {
            "client": client_config(api_key, api_version),
            "resources": [resource_config(endpoint, channel_id)],
        }
        selected = rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )
    return SourceResponse(
        name=endpoint,
        items=lambda: selected,
        primary_keys=list(settings.primary_keys),
        partition_keys=list(settings.partition_keys),
        partition_mode=settings.partition_mode,
        partition_count=settings.partition_count,
        on_complete=resumable_source_manager.clear_state,
    )
