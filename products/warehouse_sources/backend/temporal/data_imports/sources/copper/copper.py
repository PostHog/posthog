from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response, Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.settings import (
    COPPER_DEFAULT_PAGE_SIZE,
    COPPER_ENDPOINTS,
    DATE_CREATED,
    FIELD_LAYOUT_ENTITIES,
    FIELD_LAYOUT_NO_PIPELINE,
    FIELD_LAYOUT_PIPELINED_ENTITY,
    FIELD_LAYOUTS_ENDPOINT,
    RELATED_ITEM_PARENTS,
    CopperEndpointConfig,
)

COPPER_BASE_URL = "https://api.copper.com/developer_api/v1"
# Copper requires this header on every request; "developer" is the documented value for API-key auth.
COPPER_APPLICATION = "developer"
COPPER_REQUEST_TIMEOUT = 60


@frozen
class CopperResumeConfig:
    page_number: int
    # Which entry of RELATED_ITEM_PARENTS the related-items fan-out was walking. Unused by the
    # single-endpoint searches, which only ever resume a page number.
    parent_index: int = 0


class CopperPageNumberPaginator(BasePaginator):
    """Page-number pagination carried inside the POST search body.

    Copper's `/search` endpoints page via a `page_number` field in the JSON body and return a bare
    array. A page shorter than `page_size` (or an empty page) is the last one, so we stop without
    paying for one extra empty-page request. Resume persists the next page to fetch.
    """

    def __init__(self, page_size: int, page: int = 1) -> None:
        super().__init__()
        self.page_size = page_size
        self.page = page

    def _inject(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["page_number"] = self.page

    def init_request(self, request: Request) -> None:
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # A short or empty page is the last one — Copper has no total count to consult.
        if not data or len(data) < self.page_size:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def _headers(user_email: str) -> dict[str, str]:
    # The secret access token travels via framework `auth` (APIKeyAuth) so its value is redacted from
    # logs; only these non-secret headers are set on the client.
    return {
        "X-PW-Application": COPPER_APPLICATION,
        "X-PW-UserEmail": user_email,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _to_unix_seconds(value: Any) -> int | None:
    """Coerce the stored incremental watermark into the Unix-epoch-seconds Copper expects."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        # Treat naive datetimes as UTC so the epoch cutoff doesn't shift with the host timezone.
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_search_body(
    config: CopperEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
    page_size: int,
) -> dict[str, Any]:
    body: dict[str, Any] = {"page_size": page_size}

    if config.incremental_ceiling_param is not None:
        # Applied on every sync, not just incremental ones, so a future-dated row can never enter
        # the table and become the watermark.
        body[config.incremental_ceiling_param] = int(datetime.now(UTC).timestamp())

    min_param = config.incremental_params.get(incremental_field or "") if should_use_incremental_field else None
    if min_param is not None:
        if config.sortable:
            body["sort_by"] = incremental_field
            body["sort_direction"] = "asc"
        last_value = _to_unix_seconds(db_incremental_field_last_value)
        if last_value is not None:
            # Inclusive bound: the boundary row is re-fetched and deduped by merge on primary key.
            body[min_param] = last_value
    elif config.sortable and config.full_refresh_sort:
        body["sort_by"] = config.full_refresh_sort
        body["sort_direction"] = "asc"

    return body


def validate_credentials(api_key: str, user_email: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{COPPER_BASE_URL}/account",
        headers={"X-PW-AccessToken": api_key, **_headers(user_email)},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Copper credentials. Check your API key and the email it belongs to."
    if status is None:
        return False, "Could not reach Copper to validate credentials. Please try again."
    return False, f"Copper credential check failed with status {status}"


def _copper_session(api_key: str, user_email: str) -> Session:
    return make_tracked_session(
        headers={"X-PW-AccessToken": api_key, **_headers(user_email)},
        redact_values=(api_key,),
    )


def _get_json(session: Session, path: str, params: dict[str, Any] | None = None) -> Any | None:
    """GET a Copper path, answering None when the record or layout is gone."""
    response = session.get(f"{COPPER_BASE_URL}{path}", params=params, timeout=COPPER_REQUEST_TIMEOUT)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


@frozen
class CopperSearchPage:
    number: int
    has_next_page: bool
    records: list[dict[str, Any]]


def _iter_search_pages(session: Session, path: str, page_size: int, start_page: int) -> Iterator[CopperSearchPage]:
    page = start_page
    while True:
        response = session.post(
            f"{COPPER_BASE_URL}{path}",
            json={
                "page_size": page_size,
                "page_number": page,
                "sort_by": DATE_CREATED,
                "sort_direction": "asc",
            },
            timeout=COPPER_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        records = response.json()
        if not isinstance(records, list):
            # Reading a malformed page as empty would end the walk early and silently truncate.
            raise ValueError(f"Copper returned a non-list search page for {path}")
        has_next_page = len(records) >= page_size
        yield CopperSearchPage(number=page, has_next_page=has_next_page, records=records)
        if not has_next_page:
            return
        page += 1


def _iter_field_layouts(session: Session, path_template: str) -> Iterator[list[dict[str, Any]]]:
    pipeline_ids = [
        pipeline["id"] for pipeline in (_get_json(session, "/pipelines") or []) if pipeline.get("id") is not None
    ]

    for entity in FIELD_LAYOUT_ENTITIES:
        targets = pipeline_ids if entity == FIELD_LAYOUT_PIPELINED_ENTITY else [FIELD_LAYOUT_NO_PIPELINE]
        for pipeline_id in targets:
            params = {"pipeline_id": pipeline_id} if pipeline_id != FIELD_LAYOUT_NO_PIPELINE else None
            layout = _get_json(session, path_template.format(entity=entity), params=params)
            if not layout:
                continue
            yield [{"entity_type": entity, "pipeline_id": pipeline_id, **field} for field in layout]


def _iter_related_items(
    session: Session,
    path_template: str,
    resumable_source_manager: ResumableSourceManager[CopperResumeConfig],
    page_size: int,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    first_parent = resume.parent_index if resume else 0
    first_page = resume.page_number if resume else 1

    for parent_index in range(first_parent, len(RELATED_ITEM_PARENTS)):
        parent_type, parent_endpoint = RELATED_ITEM_PARENTS[parent_index]
        start_page = first_page if parent_index == first_parent else 1
        search_path = COPPER_ENDPOINTS[parent_endpoint].path

        for page in _iter_search_pages(session, search_path, page_size, start_page):
            rows: list[dict[str, Any]] = []
            for record in page.records:
                parent_id = record.get("id")
                if parent_id is None:
                    continue
                related = _get_json(session, path_template.format(entity=parent_endpoint, record_id=parent_id))
                if related is None:
                    # Deleted between the parent page and this call.
                    continue
                rows.extend({"parent_type": parent_type, "parent_id": parent_id, **item} for item in related)
            if rows:
                yield rows

            next_parent, next_page = (parent_index, page.number + 1) if page.has_next_page else (parent_index + 1, 1)
            if next_parent < len(RELATED_ITEM_PARENTS):
                # Saved after the page is yielded, so a crash re-walks it rather than skipping it.
                resumable_source_manager.save_state(CopperResumeConfig(page_number=next_page, parent_index=next_parent))

    # The walk finished: leaving the last checkpoint would make a later attempt resume mid-stream.
    resumable_source_manager.clear_state()


def _custom_iterator_source(
    config: CopperEndpointConfig,
    api_key: str,
    user_email: str,
    resumable_source_manager: ResumableSourceManager[CopperResumeConfig],
) -> SourceResponse:
    """Endpoints Copper only exposes per entity, so one schema needs many differently-shaped requests."""

    def items() -> Iterator[list[dict[str, Any]]]:
        session = _copper_session(api_key, user_email)
        if config.name == FIELD_LAYOUTS_ENDPOINT:
            yield from _iter_field_layouts(session, config.path)
        else:
            yield from _iter_related_items(session, config.path, resumable_source_manager, COPPER_DEFAULT_PAGE_SIZE)

    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        sort_mode=config.sort_mode,
    )


def copper_source(
    api_key: str,
    user_email: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CopperResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = COPPER_ENDPOINTS[endpoint]

    if config.custom_iterator:
        return _custom_iterator_source(config, api_key, user_email, resumable_source_manager)

    body: dict[str, Any] | None
    paginator: BasePaginator
    if config.paginated:
        body = _build_search_body(
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
            COPPER_DEFAULT_PAGE_SIZE,
        )
        paginator = CopperPageNumberPaginator(page_size=COPPER_DEFAULT_PAGE_SIZE)
    else:
        # Reference endpoints are plain unpaginated GET collections returned as one array.
        body = None
        paginator = SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": COPPER_BASE_URL,
            "headers": _headers(user_email),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-PW-AccessToken", "location": "header"},
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "method": config.method,
                    # Most Copper responses are bare JSON arrays, so data_selector is usually unset.
                    "json": body,
                    "data_selector": config.data_selector,
                    "paginator": paginator,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page_number}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(CopperResumeConfig(page_number=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if config.paginated else None,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode=config.partition_mode,
        partition_format=config.partition_format,
        partition_keys=config.partition_keys,
        sort_mode=config.sort_mode,
    )
