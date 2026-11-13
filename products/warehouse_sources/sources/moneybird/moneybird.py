from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.sources.moneybird.settings import (
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    SYNC_BATCH_SIZE,
    MoneybirdEndpoint,
)
from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    ClientConfig,
    EndpointResource,
    PageNumberPaginator,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceInputs,
    SourceResponse,
    frozen,
    parse_datetime_value,
    rest_api_resource,
    schema_for_resource,
)


@frozen
class MoneybirdResumeConfig:
    # The next page of a paged endpoint.
    page: Optional[int] = None
    # The highest id whose record a synchronization endpoint already returned. Ids are read in
    # ascending order, so a resumed run continues after it.
    last_synchronized_id: Optional[int] = None


class MoneybirdPaginator(PageNumberPaginator):
    """Moneybird's `page`/`per_page` pagination.

    A page shorter than `per_page`, or a `Link` header without a `next` link, is the last page.
    This saves the empty-page request that the base paginator makes, which counts against the
    150 requests in 5 minutes that Moneybird allows.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        last_page = (
            not data or len(data) < PAGE_SIZE or (bool(response.headers.get("Link")) and "next" not in response.links)
        )
        if last_page:
            self._has_next_page = False
            return
        super().update_state(response, data)


def _base_url(administration_id: str) -> str:
    return f"{BASE_URL}/{administration_id}"


def _client(api_token: str, base_url: str) -> RESTClient:
    return RESTClient(
        base_url=base_url,
        auth=BearerTokenAuth(api_token),
        headers={"Accept": "application/json"},
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT,
    )


def updated_after_filter(endpoint: MoneybirdEndpoint, last_value: Any) -> Optional[str]:
    """Return the `filter` param for an incremental read of an `updated_after` endpoint."""
    watermark = parse_datetime_value(last_value)
    if watermark is None:
        return endpoint.base_filter
    # `updated_after` is exclusive and has second precision. Step back one second so a record
    # changed in the same second as the watermark is read again. The merge removes the duplicate.
    term = f"updated_after:{(watermark - timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    return f"{endpoint.base_filter},{term}" if endpoint.base_filter else term


def _list_resource(name: str, endpoint: MoneybirdEndpoint, use_incremental: bool, last_value: Any) -> EndpointResource:
    params: dict[str, Any] = dict(endpoint.params)
    request_filter = updated_after_filter(endpoint, last_value) if use_incremental else endpoint.base_filter
    if request_filter:
        params["filter"] = request_filter
    if endpoint.fetch_mode == "paged":
        params["per_page"] = PAGE_SIZE

    return {
        "name": name,
        "table_name": name,
        "primary_key": ["id"],
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": {
            "path": f"{endpoint.path}.json",
            "params": params,
            "paginator": MoneybirdPaginator() if endpoint.fetch_mode == "paged" else SinglePagePaginator(),
            "data_selector_required": True,
        },
        "table_format": "delta",
    }


def _list_rows(
    name: str,
    endpoint: MoneybirdEndpoint,
    api_token: str,
    base_url: str,
    inputs: SourceInputs,
    use_incremental: bool,
    resumable_source_manager: ResumableSourceManager[MoneybirdResumeConfig],
) -> Any:
    client_config: ClientConfig = {
        "base_url": base_url,
        "auth": {"type": "bearer", "token": api_token},
        "headers": {"Accept": "application/json"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT,
    }
    config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            _list_resource(name, endpoint, use_incremental, inputs.db_incremental_field_last_value),
        ],
    }

    initial_state: Optional[dict[str, Any]] = None
    if endpoint.fetch_mode == "paged" and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page is not None:
            initial_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(MoneybirdResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )


def _synchronized_rows(
    endpoint: MoneybirdEndpoint,
    client: RESTClient,
    min_version: Optional[int],
    resumable_source_manager: ResumableSourceManager[MoneybirdResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    sync_path = f"{endpoint.path}/synchronization.json"
    versions: dict[int, int] = {}
    for sync_filter in endpoint.sync_filters:
        for page in client.paginate(
            path=sync_path,
            params={"filter": sync_filter},
            paginator=SinglePagePaginator(),
            data_selector_required=True,
        ):
            for item in page:
                versions[int(item["id"])] = int(item["version"])
        resumable_source_manager.safe_point()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after_id = resume.last_synchronized_id if resume is not None else None

    # `>=` reads records that changed in the same second as the watermark again. The merge
    # removes the duplicates.
    pending = sorted(
        record_id
        for record_id, version in versions.items()
        if (min_version is None or version >= min_version) and (after_id is None or record_id > after_id)
    )

    for start in range(0, len(pending), SYNC_BATCH_SIZE):
        batch = pending[start : start + SYNC_BATCH_SIZE]
        rows: list[dict[str, Any]] = []
        for page in client.paginate(
            path=sync_path,
            method="post",
            json={"ids": [str(record_id) for record_id in batch]},
            paginator=SinglePagePaginator(),
            data_selector_required=True,
        ):
            rows.extend(page)
        resumable_source_manager.save_state(MoneybirdResumeConfig(last_synchronized_id=batch[-1]))
        if rows:
            yield rows
        else:
            # Every record of the batch was deleted after the id list was read.
            resumable_source_manager.safe_point()


def moneybird_source(
    api_token: str,
    administration_id: str,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[MoneybirdResumeConfig],
) -> SourceResponse:
    name = inputs.schema_name
    endpoint = schema_for_resource(ENDPOINTS, name)
    use_incremental = inputs.should_use_incremental_field
    base_url = _base_url(administration_id)

    items: Callable[[], Any]
    if endpoint.fetch_mode == "synchronization":
        last_value = inputs.db_incremental_field_last_value if use_incremental else None
        min_version = int(last_value) if last_value is not None else None
        client = _client(api_token, base_url)
        items = lambda: _synchronized_rows(endpoint, client, min_version, resumable_source_manager)
    else:
        resource = _list_rows(name, endpoint, api_token, base_url, inputs, use_incremental, resumable_source_manager)
        items = lambda: resource

    return SourceResponse(
        name=name,
        items=items,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        sort_mode=None,
    )


def list_administration_ids(api_token: str) -> set[str]:
    """Return the ids of the administrations the token can read. Raises `HTTPError` on a refusal."""
    client = _client(api_token, BASE_URL)
    administration_ids: set[str] = set()
    for page in client.paginate(
        path="administrations.json",
        paginator=SinglePagePaginator(),
        data_selector_required=True,
    ):
        administration_ids.update(str(item["id"]) for item in page)
    return administration_ids
