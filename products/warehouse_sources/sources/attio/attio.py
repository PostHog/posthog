from collections.abc import Iterator
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.sources.attio.settings import ATTIO_ENDPOINTS, AttioEndpointConfig, FanoutTarget
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    BearerTokenAuth,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SortMode,
    SourceResponse,
    create_response_hooks,
    frozen,
    lift_nested,
    make_tracked_session,
    rest_api_resource,
)

BASE_URL = "https://api.attio.com"


@frozen
class AttioResumeConfig:
    # Position of the next page to fetch: a row offset, or an Attio cursor for cursor-paginated
    # endpoints. The Redis key is per job, so one job never reads another endpoint's position.
    offset: int | None = None
    cursor: str | None = None
    # Fan-out tables only: the key of a child read (`<target>/<parent id>[/<attribute id>]`). With
    # `offset` set, the child is read up to that offset. Without it, the child is read completely.
    fanout_key: str | None = None


@frozen
class _FanoutChild:
    # `<target>/<parent id>[/<attribute id>]`. Children are read in ascending key order.
    key: str
    target: FanoutTarget
    path: str


# An object, list or attribute can be deleted between the parent listing and the child request.
_IGNORE_NOT_FOUND = create_response_hooks([{"status_code": 404, "action": "ignore"}], resource_name="attio")


class AttioOffsetPaginator(BasePaginator):
    """Paginator for Attio endpoints using offset-based pagination.

    Supports both POST endpoints (pagination in JSON body) and GET endpoints (pagination in query params).
    """

    def __init__(self, limit: int = 100, use_json_body: bool = False, initial_json: Optional[dict[str, Any]] = None):
        super().__init__()
        self._limit = limit
        self._current_offset = 0
        self._next_offset: Optional[int] = 0
        self._has_next_page = False
        self._use_json_body = use_json_body
        self._initial_json = initial_json or {}

    def init_request(self, request: Request) -> None:
        if self._use_json_body:
            if request.json is None:
                request.json = dict(self._initial_json)
            else:
                for key, value in self._initial_json.items():
                    if key not in request.json:
                        request.json[key] = value
            request.json["offset"] = self._current_offset
            request.json["limit"] = self._limit
        else:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._current_offset
            request.params["limit"] = self._limit

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            response_data = response.json()
            returned_data = response_data.get("data", [])

            if len(returned_data) < self._limit:
                self._has_next_page = False
                self._next_offset = None
            else:
                self._has_next_page = True
                self._next_offset = self._current_offset + self._limit
        except Exception:
            self._has_next_page = False
            self._next_offset = None

    def update_request(self, request: Request) -> None:
        if self._next_offset is not None:
            self._current_offset = self._next_offset

        if self._use_json_body:
            if request.json is None:
                request.json = dict(self._initial_json)
            else:
                for key, value in self._initial_json.items():
                    if key not in request.json:
                        request.json[key] = value
            request.json["offset"] = self._current_offset
            request.json["limit"] = self._limit
        else:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._current_offset
            request.params["limit"] = self._limit

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # update_request has already moved _current_offset to the next page.
        return {"offset": self._current_offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self._current_offset = int(offset)
            self._next_offset = self._current_offset
            self._has_next_page = True


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested 'id' object into the root level."""
    return lift_nested(item, "id", on_clash="nested")


def _parent_id(row: dict[str, Any], target: FanoutTarget) -> str | None:
    ids = row.get("id")
    if not isinstance(ids, dict):
        return None
    value = ids.get("list_id" if target == "lists" else "object_id")
    return str(value) if value else None


def _parent_keys(
    client: RESTClient,
    config: AttioEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AttioResumeConfig],
) -> list[tuple[FanoutTarget, str]]:
    """List the objects and lists to fan out over, in a stable order so resume keys compare."""
    parents: list[tuple[FanoutTarget, str]] = []
    for target in config.fanout_targets:
        for page in client.paginate(path=f"/v2/{target}", paginator=SinglePagePaginator(), data_selector="data"):
            parents.extend(
                (target, parent_id)
                for row in page
                if isinstance(row, dict) and (parent_id := _parent_id(row, target)) is not None
            )
        resumable_source_manager.safe_point()
    return sorted(parents)


def _attribute_ids(
    client: RESTClient,
    target: FanoutTarget,
    parent_id: str,
    attribute_type: str,
    resumable_source_manager: ResumableSourceManager[AttioResumeConfig],
) -> list[str]:
    attribute_ids: list[str] = []
    for page in client.paginate(
        path=f"/v2/{target}/{parent_id}/attributes",
        params={"show_archived": "true"},
        paginator=AttioOffsetPaginator(limit=ATTIO_ENDPOINTS["attributes"].page_size),
        data_selector="data",
        hooks=_IGNORE_NOT_FOUND,
    ):
        for row in page:
            if not isinstance(row, dict) or row.get("type") != attribute_type:
                continue
            ids = row.get("id")
            if isinstance(ids, dict) and ids.get("attribute_id"):
                attribute_ids.append(str(ids["attribute_id"]))
        resumable_source_manager.safe_point()
    return sorted(attribute_ids)


def _fanout_children(
    client: RESTClient,
    config: AttioEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AttioResumeConfig],
    resume_key: str | None,
) -> Iterator[_FanoutChild]:
    """Yield each child read, in ascending key order."""
    for target, parent_id in _parent_keys(client, config, resumable_source_manager):
        parent_key = f"{target}/{parent_id}"
        path = config.path.replace("{target}", target).replace("{identifier}", parent_id)
        if config.fanout == "parent":
            yield _FanoutChild(key=parent_key, target=target, path=path)
            continue
        # Every child key of this parent sorts before the resume key, so skip the attribute listing.
        if resume_key is not None and parent_key < resume_key[: len(parent_key)]:
            continue
        assert config.attribute_type is not None
        for attribute_id in _attribute_ids(client, target, parent_id, config.attribute_type, resumable_source_manager):
            yield _FanoutChild(
                key=f"{parent_key}/{attribute_id}", target=target, path=path.replace("{attribute}", attribute_id)
            )


def _fanout_rows(
    client: RESTClient,
    config: AttioEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AttioResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Read the child endpoint for each object or list, in ascending order of the child key.

    The resume state is the key of the last child read, so it stays small however many objects,
    lists and attributes a workspace has.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_key = resume.fanout_key if resume else None
    resume_offset = resume.offset if resume else None
    next_page_state: Optional[dict[str, Any]] = None

    def track_child_page(state: Optional[dict[str, Any]], _has_next_page: bool) -> None:
        nonlocal next_page_state
        next_page_state = state

    for child in _fanout_children(client, config, resumable_source_manager, resume_key):
        key = child.key
        if resume_key is not None and (key < resume_key or (key == resume_key and resume_offset is None)):
            continue
        start_offset = resume_offset if key == resume_key else None

        paginator: BasePaginator
        if config.pagination == "single":
            paginator = SinglePagePaginator()
        else:
            paginator = AttioOffsetPaginator(limit=config.page_size, use_json_body=config.method == "POST")

        yielded = False
        for page in client.paginate(
            path=child.path,
            method=config.method,
            params=dict(config.params) or None,
            paginator=paginator,
            data_selector="data",
            hooks=_IGNORE_NOT_FOUND,
            initial_paginator_state={"offset": start_offset} if start_offset is not None else None,
            page_state_hook=track_child_page,
        ):
            rows = [_shape_fanout_row(row, config, child.target) for row in page if isinstance(row, dict)]
            if not rows:
                continue
            offset = next_page_state.get("offset") if next_page_state else None
            resumable_source_manager.save_state(
                AttioResumeConfig(fanout_key=key, offset=int(offset) if offset is not None else None)
            )
            yield rows
            yielded = True

        if not yielded:
            resumable_source_manager.safe_point()


def _shape_fanout_row(row: dict[str, Any], config: AttioEndpointConfig, target: FanoutTarget) -> dict[str, Any]:
    shaped = _flatten_item(row)
    if len(config.fanout_targets) > 1:
        # `object_id` holds the id of an object or a list, so name which one it is.
        shaped["target"] = target
    return shaped


def get_resource(name: str) -> EndpointResource:
    """Build an EndpointResource from the endpoint configuration.

    Attio API doesn't support updatedAt filtering, so only full refresh is supported.
    """
    config = ATTIO_ENDPOINTS[name]

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": "data",
    }

    if config.method == "POST":
        endpoint_config["method"] = "POST"
        json_body: dict[str, Any] = {"sorts": [{"attribute": "created_at", "direction": "asc"}]}
        endpoint_config["json"] = json_body
        endpoint_config["paginator"] = AttioOffsetPaginator(
            limit=config.page_size, use_json_body=True, initial_json=json_body
        )
    elif config.pagination == "single":
        endpoint_config["paginator"] = SinglePagePaginator()
    elif config.pagination == "cursor":
        endpoint_config["params"] = {"limit": config.page_size}
        endpoint_config["paginator"] = JSONResponseCursorPaginator(
            cursor_path="pagination.next_cursor", cursor_param="cursor"
        )
    else:
        endpoint_config["paginator"] = AttioOffsetPaginator(limit=config.page_size)

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate Attio API credentials by making a test request."""
    # A non-ASCII key can't be encoded into the Authorization header (requests uses latin-1),
    # which would otherwise surface a raw UnicodeEncodeError to the user.
    if not api_key.isascii():
        return (
            False,
            "Your Attio API key contains an unsupported character (for example an invisible one pasted "
            "from another app). Retype it by hand and try again.",
        )
    try:
        res = make_tracked_session().get(
            "https://api.attio.com/v2/self",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=10,
        )
        if res.status_code == 200:
            return True, None

        try:
            error_data = res.json()
            if error_data.get("code") == "missing_value":
                return (
                    False,
                    "Attio rejected your API key. Create a new API key in your Attio workspace settings, then reconnect.",
                )
        except Exception:
            pass
        return False, f"HTTP {res.status_code}: {res.text}"
    except Exception as e:
        return False, str(e)


def attio_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AttioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    """Main source function for Attio data import.

    Attio API doesn't support updatedAt filtering, so only full refresh is supported.
    The incremental parameters are kept for interface compatibility but are not used.
    """
    endpoint_config = ATTIO_ENDPOINTS[endpoint]

    if endpoint_config.fanout is not None:
        client = RESTClient(
            base_url=BASE_URL,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            auth=BearerTokenAuth(token=api_key),
        )
        return _source_response(
            endpoint_config, lambda: _fanout_rows(client, endpoint_config, resumable_source_manager), sort_mode=None
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    # The GET endpoints take no sort order, so a row deleted during the walk moves every later
    # offset down by one and the walk misses one live row. A resumed attempt has the same exposure
    # as one long attempt, because it continues at the offset after the last written page. Without
    # resume, a walk of a large workspace cannot move to another worker, and a restart reads every
    # page again.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset, "cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The offset points at the page after the one that carries this state, so a resume never
        # skips a page that the pipeline has not written.
        if not state:
            return
        if state.get("cursor") is not None:
            resumable_source_manager.save_state(AttioResumeConfig(cursor=str(state["cursor"])))
        elif state.get("offset") is not None:
            resumable_source_manager.save_state(AttioResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    ).add_map(_flatten_item)

    return _source_response(endpoint_config, lambda: resource, sort_mode="asc")


def _source_response(config: AttioEndpointConfig, items: Any, sort_mode: Optional[SortMode]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=list(config.primary_keys),
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=sort_mode,
    )
