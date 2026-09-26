import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.settings import (
    ANVIL_ENDPOINTS,
    ANVIL_GRAPHQL_URL,
    PAGE_SIZE,
    AnvilEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 60

# GraphQL queries are idempotent reads, so retrying POST is safe. The default retry list
# excludes POST, which would leave the 429s from Anvil's 4 requests/second development-key
# rate limit unretried; Anvil sends Retry-After on 429, which the transport honors.
_ANVIL_RETRY = DEFAULT_RETRY.new(allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"})

_CURRENT_USER_QUERY = "query { currentUser { eid } }"

_ORGANIZATION_EIDS_QUERY = "query { currentUser { organizations { eid } } }"


class AnvilAPIError(Exception):
    """A GraphQL-level error, which Anvil returns in HTTP 200 bodies with an `errors` array."""


@dataclasses.dataclass(frozen=True)
class AnvilResumeConfig:
    # Page number to request next within the bookmarked parent's page walk. None means
    # "start the parent at its first page".
    next_offset: int | None = None
    # The parent currently being paged: an organization eid for the per-organization
    # endpoints, a weld eid for the weldDatas fan-out (a job syncs one endpoint, so the
    # kind is unambiguous). A stable eid, not a positional index, so parents created or
    # deleted between a crash and the retry can't resume us into the wrong parent.
    parent_eid: str | None = None


class _NoopLogger:
    def error(self, *args: Any, **kwargs: Any) -> None:
        return None


def _build_organizations_query(item_fields: str) -> str:
    return f"""
query Organizations {{
  currentUser {{
    organizations {{
{item_fields}
    }}
  }}
}}
"""


def _build_organization_page_query(page_field: str, item_fields: str) -> str:
    return f"""
query OrganizationPage($organizationEid: String!, $limit: Int, $offset: Int) {{
  organization(organizationEid: $organizationEid) {{
    {page_field}(limit: $limit, offset: $offset) {{
      page
      pageCount
      items {{
{item_fields}
      }}
    }}
  }}
}}
"""


def _build_weld_datas_query(item_fields: str) -> str:
    return f"""
query WeldDatas($weldEid: String!, $limit: Int, $offset: Int) {{
  weld(eid: $weldEid) {{
    weldDatas(limit: $limit, offset: $offset) {{
      page
      pageCount
      items {{
{item_fields}
      }}
    }}
  }}
}}
"""


def _make_session(api_key: str) -> requests.Session:
    # Anvil authenticates with HTTP Basic auth: the API key as the username, empty password.
    session = make_tracked_session(retry=_ANVIL_RETRY, redact_values=(api_key,))
    session.auth = (api_key, "")
    return session


def _execute(
    session: requests.Session,
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(
        ANVIL_GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=REQUEST_TIMEOUT_SECONDS
    )

    if not response.ok:
        logger.error(f"Anvil API error: status={response.status_code}, body={response.text}")
        response.raise_for_status()

    body = response.json()
    errors = body.get("errors")
    if errors:
        message = "; ".join(str(error.get("message", error)) for error in errors if isinstance(error, dict))
        raise AnvilAPIError(f"Anvil API error: {message}")

    return body.get("data") or {}


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """One cheap probe: `currentUser` resolves only for a genuine API key."""
    session = _make_session(api_key)
    try:
        data = _execute(session, _CURRENT_USER_QUERY, {}, _NoopLogger())  # type: ignore[arg-type]
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            return False, "Anvil rejected the API key"
        return False, "Could not reach the Anvil API"
    except AnvilAPIError as e:
        return False, str(e)
    except Exception:
        return False, "Could not reach the Anvil API"

    if not (data.get("currentUser") or {}).get("eid"):
        return False, "Anvil did not return a user for this API key"
    return True, None


_Execute = Callable[[str, dict[str, Any]], dict[str, Any]]


def _iter_pages(
    execute: _Execute,
    query: str,
    variables: dict[str, Any],
    unwrap: Callable[[dict[str, Any]], dict[str, Any] | None],
    resume_offset: int | None,
    logger: FilteringBoundLogger,
    context: str,
) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
    """Walk one paginated Page field, yielding `(items, next_offset)` per page.

    Anvil's `offset` argument is a page number (the Workflow API guide passes a `$pageNum`
    variable straight into `offset`), and the response's `page`/`pageCount` fields drive
    termination. The first request omits `offset` so the server's own first-page number seeds
    the walk, keeping the arithmetic correct whatever base the numbering starts at.
    `next_offset` is None on the final page so callers don't persist resume state past the
    end of the walk.
    """
    offset = resume_offset
    previous_page: int | None = None
    while True:
        page_variables: dict[str, Any] = {**variables, "limit": PAGE_SIZE}
        if offset is not None:
            page_variables["offset"] = offset
        data = execute(query, page_variables)

        page_obj = unwrap(data)
        if page_obj is None:
            # The parent was deleted between enumeration and this fetch; its rows are gone
            # with it, so skip rather than failing the whole sync.
            logger.warning(f"Anvil: {context} no longer exists, skipping")
            return

        items = page_obj.get("items") or []
        page = page_obj.get("page")
        page_count = page_obj.get("pageCount")

        # A page that does not advance means the server ignored the requested offset;
        # looping on it would re-fetch the same rows forever.
        if previous_page is not None and (not isinstance(page, int) or page <= previous_page):
            raise AnvilAPIError(
                f"Anvil pagination did not advance for {context}: requested offset {offset}, got page {page}"
            )

        next_offset: int | None = None
        if items and isinstance(page, int) and isinstance(page_count, int) and page < page_count:
            next_offset = page + 1

        yield items, next_offset

        if next_offset is None:
            return
        previous_page = page
        offset = next_offset


def _list_organization_eids(execute: _Execute) -> list[str]:
    data = execute(_ORGANIZATION_EIDS_QUERY, {})
    organizations = (data.get("currentUser") or {}).get("organizations") or []
    return [organization["eid"] for organization in organizations if organization.get("eid")]


def _list_weld_eids(execute: _Execute, logger: FilteringBoundLogger) -> list[str]:
    weld_eids: list[str] = []
    for organization_eid in _list_organization_eids(execute):
        pages = _iter_pages(
            execute,
            _build_organization_page_query("welds", "eid"),
            {"organizationEid": organization_eid},
            lambda data: (data.get("organization") or {}).get("welds"),
            None,
            logger,
            f"organization {organization_eid}",
        )
        for items, _ in pages:
            weld_eids.extend(item["eid"] for item in items if item.get("eid"))
    return weld_eids


def _get_parent_paged_rows(
    execute: _Execute,
    query: str,
    parent_eids: list[str],
    # GraphQL variable naming the parent; also the column stamped onto every row.
    variable_name: str,
    unwrap: Callable[[dict[str, Any]], dict[str, Any] | None],
    resumable_source_manager: ResumableSourceManager[AnvilResumeConfig],
    logger: FilteringBoundLogger,
    context_label: str,
) -> Iterator[list[dict[str, Any]]]:
    """Walk one page walk per parent, tagging each row with the parent it came from.

    The bookmark is a stable parent eid. If the bookmarked parent no longer exists, start
    over from the first one; merge dedupes the re-pulled rows on the primary key.
    `resume_offset` is consumed by the bookmarked parent only.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = parent_eids
    resume_offset: int | None = None
    if resume is not None and resume.parent_eid is not None and resume.parent_eid in parent_eids:
        remaining = parent_eids[parent_eids.index(resume.parent_eid) :]
        resume_offset = resume.next_offset
        logger.debug(f"Anvil: resuming {context_label} walk from {resume.parent_eid}, offset={resume_offset}")

    for index, parent_eid in enumerate(remaining):
        for items, next_offset in _iter_pages(
            execute,
            query,
            {variable_name: parent_eid},
            unwrap,
            resume_offset,
            logger,
            f"{context_label} {parent_eid}",
        ):
            rows = [{**item, variable_name: parent_eid} for item in items]
            if rows:
                yield rows
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
            # last page rather than skipping it; merge dedupes on the primary key.
            if next_offset:
                resumable_source_manager.save_state(AnvilResumeConfig(next_offset=next_offset, parent_eid=parent_eid))
        resume_offset = None

        # Advance the bookmark so a crash between parents resumes at the next one.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(AnvilResumeConfig(next_offset=None, parent_eid=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AnvilResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config: AnvilEndpointConfig = schema_for_resource(ANVIL_ENDPOINTS, endpoint)
    session = _make_session(api_key)

    def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return _execute(session, query, variables, logger)

    if config.fan_out_weld_datas:
        yield from _get_parent_paged_rows(
            execute,
            _build_weld_datas_query(config.item_fields),
            _list_weld_eids(execute, logger),
            "weldEid",
            lambda data: (data.get("weld") or {}).get("weldDatas"),
            resumable_source_manager,
            logger,
            "weld",
        )
        return

    if config.organization_page_field is None:
        data = execute(_build_organizations_query(config.item_fields), {})
        rows = (data.get("currentUser") or {}).get("organizations") or []
        if rows:
            yield rows
        return

    page_field = config.organization_page_field
    yield from _get_parent_paged_rows(
        execute,
        _build_organization_page_query(page_field, config.item_fields),
        _list_organization_eids(execute),
        "organizationEid",
        lambda data: (data.get("organization") or {}).get(page_field),
        resumable_source_manager,
        logger,
        "organization",
    )


def anvil_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AnvilResumeConfig],
) -> SourceResponse:
    config: AnvilEndpointConfig = schema_for_resource(ANVIL_ENDPOINTS, endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Anvil doesn't document list ordering guarantees, so the pipeline defers any
        # watermark commit until a run completes.
        sort_mode="desc",
    )
