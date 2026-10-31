import sqlite3
from typing import Any, cast
from urllib.parse import urlsplit

from requests import Request
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.braintrust.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    PAGE_SIZE,
    S3_HOST_PATTERN,
    BraintrustEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
    set_json_param,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braintrust import (
    BraintrustSourceConfig,
)


@frozen
class BraintrustResumeConfig:
    cursor: str | None = None
    fanout: dict[str, Any] | None = None


class FetchCursorPaginator(JSONResponseCursorPaginator):
    # Fan-out child requests carry no endpoint body, so the page size rides in with the cursor.
    def __init__(self, limit: int) -> None:
        super().__init__(
            cursor_path="cursor", cursor_param="cursor", param_location="json", raise_on_repeated_cursor=True
        )
        self.limit = limit

    def init_request(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        set_json_param(request.json, "limit", self.limit)
        super().init_request(request)


class LatestEventVersionFilter:
    """Keep the first row seen per event id within each parent object.

    Fetch pages walk the version history newest-first, so a repeated id is an outdated version.
    The seen ids live in a private temporary SQLite database, which spills to disk, so a parent with
    a long history does not hold every id in worker memory.
    """

    def __init__(self, parent_key: str) -> None:
        self._parent_key = parent_key
        self._parent: Any = None
        self._seen: sqlite3.Connection | None = None

    def _reset(self) -> None:
        if self._seen is not None:
            self._seen.close()
        # An empty filename opens a private on-disk database that SQLite deletes on close.
        self._seen = sqlite3.connect("", isolation_level=None, check_same_thread=False)
        self._seen.execute("PRAGMA journal_mode = OFF")
        self._seen.execute("PRAGMA synchronous = OFF")
        self._seen.execute("CREATE TABLE seen (id TEXT PRIMARY KEY) WITHOUT ROWID")

    def __call__(self, row: dict[str, Any]) -> bool:
        parent = row.get(self._parent_key)
        if self._seen is None or parent != self._parent:
            self._parent = parent
            self._reset()
        assert self._seen is not None
        inserted = self._seen.execute("INSERT OR IGNORE INTO seen (id) VALUES (?)", (str(row.get("id")),))
        return inserted.rowcount == 1


def validated_api_url(api_url: str, team_id: int) -> str:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (  # noqa: PLC0415 -- Keep Django models off the config import path.
        ValidateDatabaseHostMixin,
    )

    error = "Enter an HTTPS API URL without a path, query, or credentials."
    try:
        parsed = urlsplit(api_url.strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise ValueError(error)
    except ValueError:
        raise ValueError(error) from None
    valid, _ = ValidateDatabaseHostMixin().is_database_host_valid(parsed.hostname, team_id)
    if not valid:
        raise ValueError("The Braintrust API host must resolve to a public IP address.")
    return f"https://{parsed.netloc}"


def validate_credentials(config: BraintrustSourceConfig, team_id: int) -> tuple[bool, str | None]:
    if not config.api_key.strip():
        return False, AUTH_ERRORS[401]
    try:
        base_url = validated_api_url(config.api_url, team_id)
    except ValueError as error:
        return False, str(error)
    client = RESTClient(
        base_url=base_url,
        auth=BearerTokenAuth(config.api_key),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10, 60),
    )
    try:
        list(
            client.paginate(
                path="v1/project",
                params={"limit": 1},
                paginator=SinglePagePaginator(),
                data_selector="objects",
                data_selector_required=True,
                data_selector_malformed_retryable=True,
            )
        )
    except HTTPError as error:
        if error.response is not None and error.response.status_code in AUTH_ERRORS:
            return False, AUTH_ERRORS[error.response.status_code]
        raise
    return True, None


def _client_config(config: BraintrustSourceConfig, team_id: int) -> ClientConfig:
    return {
        "base_url": validated_api_url(config.api_url, team_id),
        "auth": {"type": "bearer", "token": config.api_key},
        "allowed_hosts": [],
        "allow_redirects": False,
        # A response over the API's size limit comes back as a 303 to a presigned S3 object. Only S3
        # hosts match: other `amazonaws.com` names, like EC2 ones, can resolve to private addresses.
        "presigned_redirect_host_pattern": S3_HOST_PATTERN,
        "request_timeout": (10, 60),
        "paginator": {
            "type": "cursor",
            "cursor_path": "objects[-1].id",
            "cursor_param": "starting_after",
            "raise_on_repeated_cursor": True,
        },
    }


def _list_resource(
    settings: BraintrustEndpoint,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BraintrustResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": settings.name,
                "endpoint": {
                    "path": settings.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "objects",
                    "data_selector_required": True,
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(BraintrustResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume and resume.cursor else None,
    )


def _events_resource(
    settings: BraintrustEndpoint,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BraintrustResumeConfig],
) -> Resource:
    assert settings.fanout is not None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state:
            resumable_source_manager.save_state(BraintrustResumeConfig(fanout=state))

    resource = build_dependent_resource(
        endpoint_configs=ENDPOINTS,
        child_endpoint=settings.name,
        fanout=settings.fanout,
        client_config=client_config,
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        parent_endpoint_extra={
            "data_selector": "objects",
            "data_selector_required": True,
            "data_selector_malformed_retryable": True,
        },
        # The GET form of fetch takes no cursor, so pages are read through the POST form.
        child_endpoint_extra={
            "method": "POST",
            "data_selector": "events",
            "data_selector_required": True,
            "data_selector_malformed_retryable": True,
            "paginator": FetchCursorPaginator(settings.page_size),
        },
        page_size_param=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.fanout if resume else None,
    )
    return cast(Resource, resource).add_filter(LatestEventVersionFilter(settings.fanout.resolve_param))


def braintrust_source(
    config: BraintrustSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BraintrustResumeConfig],
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    client_config = _client_config(config, team_id)
    if settings.fanout is not None:
        resource = _events_resource(settings, client_config, team_id, job_id, resumable_source_manager)
    else:
        resource = _list_resource(settings, client_config, team_id, job_id, resumable_source_manager)
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(settings.primary_keys),
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
        sort_mode="desc",
        on_complete=resumable_source_manager.clear_state,
    )
