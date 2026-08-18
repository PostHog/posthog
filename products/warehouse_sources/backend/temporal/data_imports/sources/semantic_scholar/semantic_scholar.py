import datetime
import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.settings import (
    AUTHOR_FIELDS,
    AUTHOR_SEARCH_PAGE_SIZE,
    AUTHORS_ENDPOINT,
    PAPER_FIELDS,
    PAPERS_ENDPOINT,
    SEMANTIC_SCHOLAR_BASE_URL,
)

REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class SemanticScholarResumeConfig:
    # Only one of these is ever populated per run, depending on which endpoint the manager was
    # created for: `token` for the Papers continuation cursor, `offset` for Authors' offset paging.
    token: Optional[str] = None
    offset: Optional[int] = None


def utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.UTC).date()


def _as_date(value: Any) -> Optional[datetime.date]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        # Not a date we can reason about, so drop the bound rather than send Semantic Scholar
        # something it will 400 on. Worst case the run re-reads rows the merge dedupes.
        return None


def build_date_window(from_value: Any, cap: datetime.date) -> Optional[str]:
    """Build a `publicationDateOrYear` range, capped so the watermark never lands in the future.

    Semantic Scholar carries forthcoming and ahead-of-print papers with future publication
    dates. The pipeline checkpoints the largest incremental value it sees, so reading one of
    those would pin the watermark ahead of today and silently skip every paper published
    between now and then, permanently (nothing ever lowers a watermark). Capping the window at
    `cap` keeps the checkpoint at or before today.
    """
    from_date = _as_date(from_value)
    if from_date is not None and from_date > cap:
        from_date = cap
    start = from_date.isoformat() if from_date is not None else ""
    return f"{start}:{cap.isoformat()}"


def get_papers_resource(query: str, should_use_incremental_field: bool) -> EndpointResource:
    params: dict[str, Any] = {
        "query": query,
        "fields": PAPER_FIELDS,
        # publicationDate is the only field with a documented sort guarantee; required so the
        # incremental watermark advances in the order rows actually arrive.
        "sort": "publicationDate:asc",
    }

    if should_use_incremental_field:
        cap = utc_today()
        params["publicationDateOrYear"] = {
            "type": "incremental",
            "cursor_path": "publicationDate",
            "initial_value": None,
            "convert": lambda last_value: build_date_window(last_value, cap),
        }

    return {
        "name": PAPERS_ENDPOINT,
        "table_name": PAPERS_ENDPOINT,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": "/paper/search/bulk",
            "data_selector": "data",
            "data_selector_required": True,
            "params": params,
        },
        "table_format": "delta",
    }


def get_authors_resource(author_query: str) -> EndpointResource:
    return {
        "name": AUTHORS_ENDPOINT,
        "table_name": AUTHORS_ENDPOINT,
        "write_disposition": "replace",
        "endpoint": {
            "path": "/author/search",
            "data_selector": "data",
            "data_selector_required": True,
            "params": {
                "query": author_query,
                "fields": AUTHOR_FIELDS,
                "limit": AUTHOR_SEARCH_PAGE_SIZE,
            },
        },
        "table_format": "delta",
    }


def _client_config(api_key: str, endpoint: str) -> ClientConfig:
    config: ClientConfig = {"base_url": SEMANTIC_SCHOLAR_BASE_URL}
    if api_key:
        config["auth"] = {"type": "api_key", "name": "x-api-key", "api_key": api_key, "location": "header"}

    if endpoint == PAPERS_ENDPOINT:
        # The continuation token is opaque and returned under `token` in the response body;
        # resending it (alongside the original query params) as `token` fetches the next page.
        config["paginator"] = JSONResponseCursorPaginator(cursor_path="token", cursor_param="token")
    else:
        # `total` in the response is an approximate hit count the docs warn against relying on,
        # so termination is left to the default empty-page / short-page check.
        config["paginator"] = OffsetPaginator(limit=AUTHOR_SEARCH_PAGE_SIZE, total_path=None)

    return config


def semantic_scholar_source(
    api_key: str,
    query: str,
    author_query: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SemanticScholarResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    if endpoint == PAPERS_ENDPOINT:
        resource = get_papers_resource(query, should_use_incremental_field)
    elif endpoint == AUTHORS_ENDPOINT:
        resource = get_authors_resource(author_query or "")
    else:
        raise ValueError(f"Unknown Semantic Scholar endpoint: {endpoint}")

    config: RESTAPIConfig = {
        "client": _client_config(api_key, endpoint),
        "resources": [resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            if endpoint == PAPERS_ENDPOINT and resume_config.token is not None:
                initial_paginator_state = {"cursor": resume_config.token}
            elif endpoint == AUTHORS_ENDPOINT and resume_config.offset is not None:
                initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if not state:
            return
        if endpoint == PAPERS_ENDPOINT and state.get("cursor"):
            resumable_source_manager.save_state(SemanticScholarResumeConfig(token=str(state["cursor"])))
        elif endpoint == AUTHORS_ENDPOINT and state.get("offset") is not None:
            resumable_source_manager.save_state(SemanticScholarResumeConfig(offset=int(state["offset"])))

    result = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    if endpoint == PAPERS_ENDPOINT:
        return SourceResponse(
            name=PAPERS_ENDPOINT,
            items=lambda: result,
            primary_keys=["paperId"],
            column_hints=result.column_hints,
            sort_mode="asc",
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="month",
            partition_keys=["publicationDate"],
        )

    return SourceResponse(
        name=AUTHORS_ENDPOINT,
        items=lambda: result,
        primary_keys=["authorId"],
        column_hints=result.column_hints,
        # Author search has no documented sort guarantee, so no ordering can be asserted.
        sort_mode=None,
    )


def _error_detail(response: Response) -> Optional[str]:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        detail = body.get("error") or body.get("message")
        if isinstance(detail, str) and detail:
            return detail
    return None


def _probe_error(response: Response, field_label: str) -> Optional[str]:
    if response.status_code == 403:
        return "Your Semantic Scholar API key is invalid. Check the key and try again."
    if response.status_code == 429:
        return "Semantic Scholar rate-limited this request. Add an API key, or wait a moment and try again."
    if response.status_code == 400:
        detail = _error_detail(response)
        message = f"Semantic Scholar rejected the {field_label}"
        return f"{message}: {detail}" if detail else f"{message}."
    if not response.ok:
        return f"Semantic Scholar API returned {response.status_code}."
    return None


def _probe(api_key: str, path: str, params: dict[str, Any], field_label: str) -> tuple[bool, Optional[str]]:
    session = make_tracked_session(redact_values=(api_key,) if api_key else ())
    headers = {"x-api-key": api_key} if api_key else {}

    response = session.get(
        f"{SEMANTIC_SCHOLAR_BASE_URL}{path}",
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    error = _probe_error(response, field_label)
    if error:
        return False, error
    return True, None


def validate_paper_search(api_key: str, query: str) -> tuple[bool, Optional[str]]:
    return _probe(api_key, "/paper/search/bulk", {"query": query, "fields": "title"}, "search query")


def validate_author_search(api_key: str, author_query: str) -> tuple[bool, Optional[str]]:
    return _probe(
        api_key,
        "/author/search",
        {"query": author_query, "fields": "name", "limit": 1},
        "author search query",
    )
