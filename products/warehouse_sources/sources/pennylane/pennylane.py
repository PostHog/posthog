import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

from requests import HTTPError, Request

from products.warehouse_sources.sources.pennylane.settings import (
    API_BASE_URL,
    AUTH_ERROR,
    CHANGELOG_OVERLAP,
    CHANGELOG_PAGE_SIZE,
    CHANGELOG_WINDOW,
    ENDPOINTS,
    FORBIDDEN_ERROR,
    PAGE_SIZE,
    PennylaneEndpointConfig,
    scope_error,
)
from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    Endpoint,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    frozen,
    parse_datetime_value,
    rest_api_resource,
)


@frozen
class PennylaneResumeConfig:
    cursor: str
    # True when the cursor pages through a changelog, False when it pages through the full list.
    changelog: bool = False


class _ChangelogPaginator(JSONResponseCursorPaginator):
    # Pennylane answers 400 to a changelog request that sends both `start_date` and `cursor`. The
    # cursor already holds the position, so `start_date` goes only on the first request.
    def __init__(self) -> None:
        super().__init__(cursor_path="next_cursor", cursor_param="cursor")

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        _drop_start_date_beside_cursor(request)

    def update_request(self, request: Request) -> None:
        super().update_request(request)
        _drop_start_date_beside_cursor(request)


def _drop_start_date_beside_cursor(request: Request) -> None:
    if request.params and request.params.get("cursor") is not None:
        request.params.pop("start_date", None)


def _list_paginator() -> JSONResponseCursorPaginator:
    return JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")


def _client(api_key: str) -> RESTClient:
    return RESTClient(base_url=API_BASE_URL, auth=BearerTokenAuth(api_key), request_timeout=60)


def validate_credentials(api_key: str, schema_name: str | None = None) -> tuple[bool, str | None]:
    # `/me` needs no scope, so it checks only the token. A table check reads one row of that table.
    endpoint = ENDPOINTS.get(schema_name) if schema_name else None
    client = _client(api_key)
    try:
        next(
            client.paginate(
                endpoint.path if endpoint else "/me",
                params={"limit": 1} if endpoint else None,
                paginator=SinglePagePaginator(),
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return False, scope_error(schema_name) if schema_name and endpoint else FORBIDDEN_ERROR
        raise
    finally:
        client.session.close()
    return True, None


def changelog_start(db_incremental_field_last_value: Any, now: datetime) -> datetime | None:
    """The `start_date` for a changelog read, or None when the changelog can't cover the watermark."""
    watermark = parse_datetime_value(db_incremental_field_last_value)
    if watermark is None or now - watermark > CHANGELOG_WINDOW:
        return None
    return watermark - CHANGELOG_OVERLAP


def _list_params(config: PennylaneEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size}
    if config.sortable:
        params["sort"] = "id"
    return params


def _fetch_by_ids(client: RESTClient, config: PennylaneEndpointConfig, ids: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    id_filter = json.dumps([{"field": "id", "operator": "in", "value": ids}])
    for page in client.paginate(
        config.path,
        params={"filter": id_filter, "limit": PAGE_SIZE},
        paginator=_list_paginator(),
        data_selector="items",
        data_selector_required=True,
    ):
        rows.extend(page)
    return rows


def _changed_rows(
    api_key: str,
    config: PennylaneEndpointConfig,
    start: datetime,
    resume_cursor: str | None,
    manager: ResumableSourceManager[PennylaneResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    assert config.changelog_path is not None
    client = _client(api_key)
    next_page: dict[str, str | None] = {"cursor": None}

    def remember_next_page(state: Optional[dict[str, Any]], has_next_page: bool) -> None:
        next_page["cursor"] = state.get("cursor") if state and has_next_page else None

    changelog_pages = client.paginate(
        config.changelog_path,
        params={"limit": CHANGELOG_PAGE_SIZE, "start_date": start.strftime("%Y-%m-%dT%H:%M:%SZ")},
        paginator=_ChangelogPaginator(),
        data_selector="items",
        data_selector_required=True,
        initial_paginator_state={"cursor": resume_cursor} if resume_cursor else None,
        page_state_hook=remember_next_page,
    )
    for changes in changelog_pages:
        # A deleted record can't be fetched, and a record can change more than once on one page.
        ids = list(dict.fromkeys(change["id"] for change in changes if change.get("operation") != "delete"))
        rows = _fetch_by_ids(client, config, ids) if ids else []
        cursor = next_page["cursor"]
        if cursor is not None:
            manager.save_state(PennylaneResumeConfig(cursor=cursor, changelog=True))
        if rows:
            yield rows
        else:
            manager.safe_point()


def pennylane_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PennylaneResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    config = ENDPOINTS[endpoint]

    start = None
    if should_use_incremental_field and config.changelog_path is not None:
        start = changelog_start(db_incremental_field_last_value, datetime.now(UTC))
    reads_changelog = start is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # A cursor from the other read path is a position in a different listing, so it is not used.
    resume_cursor = resume.cursor if resume is not None and resume.changelog == reads_changelog else None

    if start is not None:
        changelog_start_date = start

        def items() -> Any:
            return _changed_rows(api_key, config, changelog_start_date, resume_cursor, resumable_source_manager)

    else:
        endpoint_config: Endpoint = {
            "path": config.path,
            "params": _list_params(config),
            "data_selector": "items",
            "data_selector_required": True,
            "paginator": _list_paginator(),
        }
        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": API_BASE_URL,
                "auth": {"type": "bearer", "token": api_key},
                "request_timeout": 60,
            },
            "resources": [{"name": endpoint, "endpoint": endpoint_config, "table_format": "delta"}],
        }

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state and state.get("cursor"):
                resumable_source_manager.save_state(PennylaneResumeConfig(cursor=str(state["cursor"])))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"cursor": resume_cursor} if resume_cursor else None,
        )

        def items() -> Any:
            return resource

    partitioned = config.partition_key is not None
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["id"],
        partition_count=1 if partitioned else None,
        partition_size=1 if partitioned else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="month" if partitioned else None,
        partition_keys=[config.partition_key] if config.partition_key is not None else None,
        # Lists are sorted by id and changelog reads fetch records in batches, so neither read
        # arrives in `updated_at` order.
        sort_mode=None,
    )
