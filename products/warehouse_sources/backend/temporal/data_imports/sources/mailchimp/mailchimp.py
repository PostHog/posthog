import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

from requests import Request, Response, Session
from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.settings import (
    MAILCHIMP_ENDPOINTS,
    MAX_PAGE_SIZE,
    MailchimpEndpointConfig,
    MailchimpPagination,
    MailchimpParentConfig,
)

REQUEST_TIMEOUT_SECONDS = 120


@dataclasses.dataclass
class MailchimpResumeConfig:
    """Resume state for Mailchimp endpoints.

    - ``contacts`` fans out over audience lists and paginates members within
      each; its checkpoint is ``(list_id, offset)``.
    - ``lists``/``campaigns``/``reports`` go through the shared ``rest_api_resource``
      path using ``MailchimpPaginator`` (offset/count); their checkpoint is just
      ``offset`` and ``list_id`` is ``None``.
    - Fan-out endpoints (report/list/campaign sub-resources) checkpoint the ordered
      chain of parent ids alongside the offset, so a resume picks the same parent
      back up rather than restarting the whole fan-out.

    On resume we re-request the saved page; duplicates are deduped by the
    primary key.
    """

    offset: int
    list_id: Optional[str] = None
    parent_ids: Optional[list[str]] = None


def extract_data_center(api_key: str) -> str:
    """Extract data center from Mailchimp API key.

    Mailchimp API keys are in format: key-dc (e.g., "0123456789abcdef-us6")
    The data center suffix determines the API subdomain.
    """
    if "-" not in api_key:
        raise ValueError("Invalid Mailchimp API key format. Expected format: key-dc")
    dc = api_key.split("-")[-1]
    if not dc.isalnum():
        raise ValueError("Invalid Mailchimp API key format. Expected format: key-dc")
    return dc


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value as ISO string for Mailchimp API filters."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return str(value)


class MailchimpPaginator(BasePaginator):
    """Paginator for Mailchimp API using offset/count pagination."""

    def __init__(self, page_size: int = 1000) -> None:
        super().__init__()
        self._page_size = page_size
        self._offset = 0
        self._total_items: int | None = None

    def init_request(self, request: Request) -> None:
        # Always set offset/count so that (a) a seeded resume offset is honoured
        # on the first request, and (b) fresh runs start from offset=0 explicitly.
        if request.params is None:
            request.params = {}
        request.params["offset"] = self._offset
        request.params["count"] = self._page_size

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        self._total_items = res.get("total_items", 0)
        self._offset += self._page_size
        self._has_next_page = self._offset < self._total_items

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        request.params["offset"] = self._offset
        request.params["count"] = self._page_size

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # rest_client only calls this when has_next_page is True, so ``_offset``
        # already points at the page we still need to fetch.
        return {"offset": self._offset}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self._offset = int(offset)
            self._has_next_page = True


def _incremental_query_params(
    config: MailchimpEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> dict[str, str]:
    """Map the user's chosen cursor field onto Mailchimp's server-side `since_*` filter.

    Endpoints that expose no such filter return an empty dict and fall back to full refresh.
    """
    if not should_use_incremental_field or not db_incremental_field_last_value:
        return {}

    field = incremental_field or config.default_incremental_field
    param = config.incremental_params.get(field) if field else None
    if param is None:
        return {}

    return {param: _format_incremental_value(db_incremental_field_last_value)}


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    """Build endpoint resource configuration for a Mailchimp endpoint."""
    config = MAILCHIMP_ENDPOINTS[name]

    params: dict[str, Any] = {
        "count": config.page_size,
        **_incremental_query_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        ),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
            "params": params,
        },
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate Mailchimp API credentials by making a test request."""
    try:
        dc = extract_data_center(api_key)
    except ValueError as e:
        return False, str(e)

    url = f"https://{dc}.api.mailchimp.com/3.0/ping"

    try:
        response = _mailchimp_session(api_key).get(url, timeout=10)

        if response.status_code == 200:
            return True, None

        if response.status_code == 401:
            return False, "Invalid API key"

        if response.status_code == 403:
            return False, "API key does not have required permissions"

        try:
            error_data = response.json()
            detail = error_data.get("detail", response.text)
            return False, detail
        except Exception:
            pass

        return False, response.text
    except RequestException:
        return False, "Could not reach the Mailchimp API. Check your network connection and try again."


def _fetch_all_lists(api_key: str, dc: str) -> list[dict[str, Any]]:
    """Fetch all lists/audiences from Mailchimp."""
    lists: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000

    # One session for the whole pagination loop so urllib3's connection
    # pool keeps the TLS connection warm across pages.
    session = _mailchimp_session(api_key)

    while True:
        response = session.get(
            f"https://{dc}.api.mailchimp.com/3.0/lists",
            params={"count": page_size, "offset": offset},
            timeout=120,
        )
        response.raise_for_status()

        data = response.json()
        lists.extend(data.get("lists", []))

        total_items = data.get("total_items", 0)
        offset += page_size

        if offset >= total_items:
            break

    return lists


def _fetch_contacts_for_list(
    api_key: str,
    dc: str,
    list_id: str,
    since_last_changed: str | None,
    resumable_source_manager: ResumableSourceManager[MailchimpResumeConfig],
    start_offset: int = 0,
) -> Iterator[dict[str, Any]]:
    """Fetch all contacts for a specific list with pagination."""
    offset = start_offset
    page_size = 1000

    # One session for the whole pagination loop — see `_fetch_all_lists`.
    session = _mailchimp_session(api_key)

    while True:
        params: dict[str, str | int] = {
            "count": page_size,
            "offset": offset,
        }
        if since_last_changed:
            params["since_last_changed"] = since_last_changed

        response = session.get(
            f"https://{dc}.api.mailchimp.com/3.0/lists/{list_id}/members",
            params=params,
            timeout=120,
        )
        response.raise_for_status()

        data = response.json()
        contacts = data.get("members", [])

        if not contacts:
            break

        # Save the checkpoint for the page we just fetched *before* yielding.
        # On resume we re-fetch this page — duplicates are deduped by (list_id, id).
        resumable_source_manager.save_state(MailchimpResumeConfig(list_id=list_id, offset=offset))

        for contact in contacts:
            contact["list_id"] = list_id
            yield contact

        total_items = data.get("total_items", 0)
        offset += page_size

        if offset >= total_items:
            break


def _get_contacts_iterator(
    api_key: str,
    resumable_source_manager: ResumableSourceManager[MailchimpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[dict[str, Any]]:
    """Fetch contacts from all lists."""
    dc = extract_data_center(api_key)

    since_last_changed: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value:
        since_last_changed = _format_incremental_value(db_incremental_field_last_value)

    lists = _fetch_all_lists(api_key, dc)

    # Only honour the saved checkpoint if its list_id still exists; otherwise fall back to a fresh run.
    resume_config: MailchimpResumeConfig | None = None
    if resumable_source_manager.can_resume():
        loaded = resumable_source_manager.load_state()
        if loaded is not None and any(lst["id"] == loaded.list_id for lst in lists):
            resume_config = loaded

    for lst in lists:
        list_id = lst["id"]

        if resume_config is not None:
            if list_id != resume_config.list_id:
                continue
            start_offset = resume_config.offset
            resume_config = None
        else:
            start_offset = 0

        yield from _fetch_contacts_for_list(
            api_key,
            dc,
            list_id,
            since_last_changed,
            resumable_source_manager,
            start_offset=start_offset,
        )


def _mailchimp_session(api_key: str) -> Session:
    # capture=False keeps requests metered and logged but excludes their bodies from HTTP sample
    # capture: Mailchimp responses carry subscriber PII (email addresses, activity), campaign
    # content, feedback, and ecommerce orders that the name-based scrubbers can't reliably redact.
    return make_tracked_session(
        headers={
            "Authorization": f"apikey {api_key}",
            "Accept": "application/json",
        },
        redact_values=(api_key,),
        capture=False,
    )


def _iter_pages(
    session: Session,
    base_url: str,
    path: str,
    data_selector: str,
    pagination: MailchimpPagination,
    page_size: int,
    extra_params: dict[str, str],
    start_offset: int = 0,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """Yield ``(offset, records)`` for one Mailchimp collection endpoint.

    Only `count`/`offset` endpoints loop; the others return their whole collection in a
    single request, so sending pagination params they don't declare is avoided.
    """
    offset = start_offset

    while True:
        params: dict[str, Any] = dict(extra_params)
        if pagination in ("offset", "count_only"):
            params["count"] = page_size
        if pagination == "offset":
            params["offset"] = offset

        response = session.get(f"{base_url}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()

        data = response.json()
        records = data.get(data_selector) or []

        yield offset, records

        if pagination != "offset" or not records:
            return

        total_items = data.get("total_items", 0)
        offset += page_size

        if offset >= total_items:
            return


def _resolve_parent_id_maps(
    session: Session,
    base_url: str,
    parents: tuple[MailchimpParentConfig, ...],
) -> list[dict[str, str]]:
    """Walk the fan-out chain and return one id map per leaf parent combination.

    Each map is keyed by ``inject_as``, so it both formats the child path and supplies the
    parent columns written onto every child row.
    """
    id_maps: list[dict[str, str]] = [{}]

    for parent in parents:
        next_maps: list[dict[str, str]] = []
        for id_map in id_maps:
            for _, records in _iter_pages(
                session,
                base_url,
                parent.path.format(**id_map),
                parent.data_selector,
                "offset",
                MAX_PAGE_SIZE,
                {},
            ):
                for record in records:
                    parent_id = record.get(parent.id_field)
                    if parent_id is None:
                        continue
                    next_maps.append({**id_map, parent.inject_as: str(parent_id)})
        id_maps = next_maps

    return id_maps


def _fetch_endpoint_rows(
    session: Session,
    base_url: str,
    config: MailchimpEndpointConfig,
    path: str,
    id_map: dict[str, str],
    extra_params: dict[str, str],
    start_offset: int,
    resumable_source_manager: ResumableSourceManager[MailchimpResumeConfig],
    parent_ids: Optional[list[str]],
) -> Iterator[dict[str, Any]]:
    if config.single_object:
        response = session.get(f"{base_url}{path}", params=dict(extra_params), timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        record = response.json()
        if isinstance(record, dict):
            yield {**record, **id_map}
        return

    for offset, records in _iter_pages(
        session,
        base_url,
        path,
        config.data_selector,
        config.pagination,
        config.page_size,
        extra_params,
        start_offset,
    ):
        if not records:
            continue

        if config.pagination == "offset":
            # Checkpoint the page we are about to yield, matching the contacts path: a resume
            # re-fetches it and the primary key dedupes the overlap.
            resumable_source_manager.save_state(MailchimpResumeConfig(offset=offset, parent_ids=parent_ids))

        for record in records:
            yield {**record, **id_map}


def _get_endpoint_iterator(
    api_key: str,
    config: MailchimpEndpointConfig,
    resumable_source_manager: ResumableSourceManager[MailchimpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Fetch an endpoint that the shared `rest_api_resource` path can't express.

    That means anything fanning out over a parent resource, and the handful of collections
    Mailchimp serves without `count`/`offset` pagination.
    """
    dc = extract_data_center(api_key)
    base_url = f"https://{dc}.api.mailchimp.com/3.0"
    session = _mailchimp_session(api_key)

    extra_params = _incremental_query_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    if not config.parents:
        start_offset = 0
        if config.pagination == "offset" and resumable_source_manager.can_resume():
            loaded = resumable_source_manager.load_state()
            if loaded is not None and loaded.parent_ids is None:
                start_offset = loaded.offset

        yield from _fetch_endpoint_rows(
            session,
            base_url,
            config,
            config.path,
            {},
            extra_params,
            start_offset,
            resumable_source_manager,
            parent_ids=None,
        )
        return

    id_maps = _resolve_parent_id_maps(session, base_url, config.parents)
    parent_keys = [parent.inject_as for parent in config.parents]

    # Only honour the saved checkpoint if its parent chain still exists; otherwise fall back
    # to a fresh run rather than silently syncing nothing.
    resume_config: MailchimpResumeConfig | None = None
    if resumable_source_manager.can_resume():
        loaded = resumable_source_manager.load_state()
        if loaded is not None and loaded.parent_ids is not None:
            known_chains = {tuple(id_map[key] for key in parent_keys) for id_map in id_maps}
            if tuple(loaded.parent_ids) in known_chains:
                resume_config = loaded

    for id_map in id_maps:
        parent_ids = [id_map[key] for key in parent_keys]

        if resume_config is not None:
            if parent_ids != list(resume_config.parent_ids or []):
                continue
            start_offset = resume_config.offset
            resume_config = None
        else:
            start_offset = 0

        yield from _fetch_endpoint_rows(
            session,
            base_url,
            config,
            config.path.format(**id_map),
            id_map,
            extra_params,
            start_offset,
            resumable_source_manager,
            parent_ids=parent_ids,
        )


def mailchimp_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MailchimpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    """Create a Mailchimp data source for the specified endpoint."""
    endpoint_config = MAILCHIMP_ENDPOINTS[endpoint]

    # Contacts endpoint is special - fetches from all lists
    if endpoint == "contacts":
        return SourceResponse(
            name=endpoint,
            items=lambda: _get_contacts_iterator(
                api_key,
                resumable_source_manager,
                should_use_incremental_field,
                db_incremental_field_last_value,
            ),
            primary_keys=endpoint_config.primary_keys,
            partition_count=1,
            partition_size=1,
            partition_mode="datetime" if endpoint_config.partition_key else None,
            partition_format="week" if endpoint_config.partition_key else None,
            partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        )

    # Fan-out endpoints and the collections Mailchimp serves without offset pagination can't be
    # expressed as a single `rest_api_resource`, so they go through the generic iterator.
    if endpoint_config.parents or endpoint_config.pagination != "offset":
        return SourceResponse(
            name=endpoint,
            items=lambda: _get_endpoint_iterator(
                api_key,
                endpoint_config,
                resumable_source_manager,
                should_use_incremental_field,
                db_incremental_field_last_value,
                incremental_field,
            ),
            primary_keys=endpoint_config.primary_keys,
            partition_count=1,
            partition_size=1,
            partition_mode="datetime" if endpoint_config.partition_key else None,
            partition_format="week" if endpoint_config.partition_key else None,
            partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
            chunk_size=endpoint_config.chunk_size,
            chunk_size_bytes=endpoint_config.chunk_size_bytes,
        )

    dc = extract_data_center(api_key)

    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{dc}.api.mailchimp.com/3.0",
            "auth": {
                "type": "api_key",
                "api_key": f"apikey {api_key}",
                "name": "Authorization",
                "location": "header",
            },
            "headers": {
                "Accept": "application/json",
            },
            "paginator": MailchimpPaginator(page_size=endpoint_config.page_size),
            # capture=False for the same reason as `_mailchimp_session`: account-level endpoints
            # (conversations, ecommerce orders, and the rest) return subscriber PII and free-form
            # content the name-based scrubbers can't reliably redact, so keep it out of samples.
            "session": make_tracked_session(redact_values=(api_key,), capture=False),
        },
        "resource_defaults": {
            "write_disposition": "replace",
            "endpoint": {
                "params": {
                    "count": endpoint_config.page_size,
                },
            },
        },
        "resources": [
            get_resource(
                endpoint,
                should_use_incremental_field,
                db_incremental_field_last_value,
                incremental_field,
            )
        ],
    }

    # ``lists``/``campaigns``/``reports`` all paginate by offset/count and can
    # resume by seeding the paginator with the last un-fetched offset.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.offset > 0:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to — matches the
        # klaviyo/reddit_ads convention; Redis TTL handles cleanup on completion.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(MailchimpResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
