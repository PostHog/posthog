from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote, urlsplit

import structlog
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.pinecone.settings import BASE_URL, ENDPOINTS, PineconeEndpoint
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    JSONResponseCursorPaginator,
    PartitionFormat,
    RESTAPIConfig,
    RESTClient,
    SinglePagePaginator,
    SourceResponse,
    create_auth,
    frozen,
    rest_api_resource,
    schema_for_resource,
)

if TYPE_CHECKING:
    from products.warehouse_sources.sources.sdk import ClientConfig, Endpoint, EndpointResource, ResumableSourceManager

logger = structlog.get_logger(__name__)

# Index and assistant hosts come from the control plane; the API key is only ever sent to Pinecone's domain.
DATA_PLANE_HOST_SUFFIX = ".pinecone.io"
# A file listing can carry a signed URL that grants anyone read access to the file contents.
DROPPED_FILE_FIELDS = ("signed_url",)


@frozen
class PineconeResumeConfig:
    cursor: str


def get_client_config(api_key: str, api_version: str) -> "ClientConfig":
    return {
        "base_url": BASE_URL,
        "auth": {"type": "api_key", "api_key": api_key, "name": "Api-Key", "location": "header"},
        "headers": {"X-Pinecone-Api-Version": api_version},
        "request_timeout": (10, 60),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def get_resource(endpoint: str) -> "EndpointResource":
    settings = schema_for_resource(ENDPOINTS, endpoint)
    endpoint_config: Endpoint = {
        "path": settings.path,
        "data_selector": settings.data_selector,
        "data_selector_required": True,
        "paginator": {
            "type": "cursor",
            "cursor_path": "pagination.next",
            "cursor_param": settings.cursor_param,
        }
        if settings.paginated
        else "single_page",
    }
    if settings.paginated:
        endpoint_config["params"] = {"limit": 100}
    return {
        "name": endpoint,
        "table_name": endpoint,
        "primary_key": settings.primary_key,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
    }


def _client(api_key: str, api_version: str, base_url: str = BASE_URL) -> RESTClient:
    config = get_client_config(api_key, api_version)
    return RESTClient(
        base_url=base_url,
        auth=create_auth(config["auth"]),
        headers=config["headers"],
        request_timeout=config["request_timeout"],
        allowed_hosts=config["allowed_hosts"],
        allow_redirects=False,
    )


def _paginator(settings: PineconeEndpoint) -> BasePaginator:
    if settings.paginated:
        return JSONResponseCursorPaginator(cursor_path="pagination.next", cursor_param=settings.cursor_param)
    return SinglePagePaginator()


def _data_plane_url(parent: str, row: dict[str, Any]) -> str | None:
    if parent == "indexes":
        deployment = row.get("deployment") or {}
        status = row.get("status") or {}
        # Pinecone lists namespaces only on serverless and BYOC indexes that are ready.
        if deployment.get("deployment_type") == "pod" or not status.get("ready"):
            return None
    elif row.get("status") != "Ready":
        return None
    host = row.get("host")
    if not isinstance(host, str) or not host:
        return None
    split = urlsplit(host if "://" in host else f"https://{host}")
    hostname = split.hostname
    if split.scheme != "https" or not hostname or not hostname.endswith(DATA_PLANE_HOST_SUFFIX):
        logger.warning("pinecone_data_plane_host_skipped", parent=parent, name=row.get("name"))
        return None
    return f"https://{hostname}"


def _control_plane_url(parent: str, row: dict[str, Any]) -> str | None:
    # Backup schedules exist only on serverless and BYOC indexes.
    if parent == "indexes" and (row.get("deployment") or {}).get("deployment_type") == "pod":
        return None
    return BASE_URL


def _child_row(settings: PineconeEndpoint, parent_value: str, row: dict[str, Any]) -> dict[str, Any]:
    assert settings.parent_key is not None
    return {
        settings.parent_key: parent_value,
        **{key: value for key, value in row.items() if key not in DROPPED_FILE_FIELDS},
    }


def _endpoint_pages(
    api_key: str,
    api_version: str,
    endpoint: str,
    control_client: RESTClient,
    resumable_source_manager: "ResumableSourceManager[PineconeResumeConfig]",
) -> Iterator[list[dict[str, Any]]]:
    settings = ENDPOINTS[endpoint]
    if settings.parent is not None:
        yield from _fan_out_pages(api_key, api_version, settings, control_client, resumable_source_manager)
        return
    yield from control_client.paginate(
        path=settings.path,
        params={"limit": 100} if settings.paginated else {},
        paginator=_paginator(settings),
        data_selector=settings.data_selector,
        data_selector_required=True,
    )


def _fan_out_pages(
    api_key: str,
    api_version: str,
    settings: PineconeEndpoint,
    control_client: RESTClient,
    resumable_source_manager: "ResumableSourceManager[PineconeResumeConfig]",
) -> Iterator[list[dict[str, Any]]]:
    assert settings.parent is not None and settings.parent_key is not None
    for parents in _endpoint_pages(api_key, api_version, settings.parent, control_client, resumable_source_manager):
        for parent in parents:
            if settings.data_plane:
                base_url = _data_plane_url(settings.parent, parent)
            else:
                base_url = _control_plane_url(settings.parent, parent)
            if base_url is None or parent.get(settings.parent_field) is None:
                continue
            parent_value = str(parent[settings.parent_field])
            path = settings.path.format(**{settings.parent_key: quote(parent_value, safe="")})
            client = _client(api_key, api_version, base_url) if settings.data_plane else control_client
            try:
                # A data plane listing can omit an empty list, so a missing selector means zero rows.
                for rows in client.paginate(
                    path=path,
                    params={"limit": 100},
                    paginator=_paginator(settings),
                    data_selector=settings.data_selector,
                ):
                    if rows:
                        yield [_child_row(settings, parent_value, row) for row in rows]
                    else:
                        resumable_source_manager.safe_point()
            except HTTPError as error:
                # The parent was deleted after the parent listing.
                if error.response is None or error.response.status_code != 404:
                    raise
                resumable_source_manager.safe_point()
            finally:
                if client is not control_client:
                    client.session.close()
        resumable_source_manager.safe_point()


def fan_out_rows(
    api_key: str,
    api_version: str,
    settings: PineconeEndpoint,
    resumable_source_manager: "ResumableSourceManager[PineconeResumeConfig]",
) -> Iterator[list[dict[str, Any]]]:
    control_client = _client(api_key, api_version)
    try:
        yield from _fan_out_pages(api_key, api_version, settings, control_client, resumable_source_manager)
    finally:
        control_client.session.close()


def validate_credentials(api_key: str, api_version: str, endpoint: str) -> None:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    # A fan-out table needs a reachable top-level parent listing; child paths are only known per parent.
    while settings.parent is not None:
        settings = ENDPOINTS[settings.parent]
    client = _client(api_key, api_version)
    pages = cast(
        "Generator[list[object]]",
        client.paginate(
            path=settings.path,
            params={"limit": 1} if settings.paginated else {},
            data_selector=settings.data_selector,
            data_selector_required=True,
        ),
    )
    try:
        next(pages, None)
    finally:
        pages.close()
        client.session.close()


def pinecone_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: "ResumableSourceManager[PineconeResumeConfig]",
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    partition_count = 1 if settings.partition_mode == "md5" else None
    partition_format: PartitionFormat | None = "month" if settings.partition_mode == "datetime" else None

    if settings.parent is not None:
        return SourceResponse(
            name=endpoint,
            items=lambda: fan_out_rows(api_key, api_version, settings, resumable_source_manager),
            primary_keys=[settings.parent_key, settings.primary_key] if settings.parent_key else None,
            partition_count=partition_count,
            partition_keys=[settings.partition_key],
            partition_mode=settings.partition_mode,
            partition_format=partition_format,
            sort_mode=None,
            supports_resume=False,
        )

    config: RESTAPIConfig = {
        "client": get_client_config(api_key, api_version),
        "resources": [get_resource(endpoint)],
    }
    initial_state: dict[str, str] | None = None
    if settings.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = {"cursor": resume.cursor}

    def save_checkpoint(state: dict[str, object] | None) -> None:
        if state and isinstance(state.get("cursor"), str):
            resumable_source_manager.save_state(PineconeResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        initial_paginator_state=initial_state,
        resume_hook=save_checkpoint if settings.paginated else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[settings.primary_key],
        partition_count=partition_count,
        partition_keys=[settings.partition_key],
        partition_mode=settings.partition_mode,
        partition_format=partition_format,
        sort_mode=None,
        supports_resume=settings.paginated,
    )
