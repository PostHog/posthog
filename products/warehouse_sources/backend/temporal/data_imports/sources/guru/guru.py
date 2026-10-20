import json
import hashlib
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import quote

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.settings import (
    GURU_ENDPOINTS,
    GuruEndpointConfig,
)

GURU_BASE_URL = "https://api.getguru.com/api/v1"
GURU_API_HOST = "api.getguru.com"


@dataclasses.dataclass
class GuruResumeConfig:
    # Guru pagination follows a `Link: <url>; rel="next-page"` header whose URL is
    # self-contained (opaque continuation token), so the URL is all we persist.
    next_url: str


def _format_last_modified(value: Any) -> str:
    """Format an incremental cursor for a Guru Query Language date filter.

    GQL absolute dates require an ISO 8601 value with an explicit timezone
    (e.g. 2016-01-01T00:00:00+00:00)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _format_from_date(value: Any) -> str:
    # The analytics `fromDate` param accepts at most millisecond precision.
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat(timespec="milliseconds")
    return _format_last_modified(value)


def _build_params(
    config: GuruEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)

    if not config.incremental_fields:
        return params

    if config.date_filter_param:
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            params[config.date_filter_param] = _format_from_date(db_incremental_field_last_value)
        return params

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cursor_field = incremental_field or config.incremental_fields[0]["field"]
        params["q"] = f"{cursor_field} >= {_format_last_modified(db_incremental_field_last_value)}"
        # Ascending order on the cursor field so the incremental watermark advances
        # monotonically as pages are consumed.
        params["sortField"] = cursor_field
        params["sortOrder"] = "asc"
    else:
        # Full refresh: sort on the stable creation date so rows modified mid-sync
        # don't move across page boundaries (lastModified is Guru's default sort).
        params["sortField"] = "dateCreated"
        params["sortOrder"] = "asc"

    return params


def _normalize_member(item: dict[str, Any]) -> dict[str, Any]:
    # Team member rows nest the identifying email under `user`; copy it to the top
    # level so it can serve as the primary key. Use direct access so a member missing
    # the email surfaces a fast KeyError instead of a row with a null primary key.
    if "email" not in item and isinstance(item.get("user"), dict):
        return {**item, "email": item["user"]["email"]}
    return item


def _ensure_event_id(event: dict[str, Any]) -> dict[str, Any]:
    # The OpenAPI schema documents an event `id`, but the analytics guide's sample omits it.
    # Fall back to a content hash so the merge key is never null and overlapping `fromDate`
    # windows still dedupe.
    if event.get("id"):
        return event
    digest = hashlib.sha256(json.dumps(event, sort_keys=True, default=str).encode()).hexdigest()
    return {**event, "id": digest}


def _flatten_tag_category(category: dict[str, Any]) -> list[dict[str, Any]]:
    # Tags nested in a category omit their category reference, so carry it onto each row.
    return [
        {"categoryId": category["id"], "categoryName": category.get("name"), **tag}
        for tag in category.get("tags") or []
    ]


def _client_config(username: str, api_token: str) -> ClientConfig:
    return {
        "base_url": GURU_BASE_URL,
        "auth": {"type": "http_basic", "username": username, "password": api_token},
        # Guru paginates via `Link: <url>; rel="next-page"` with an opaque continuation token.
        "paginator": HeaderLinkPaginator(links_next_key="next-page"),
        # The next-page/resume URLs are server-controlled; pin them to the Guru API host and
        # refuse redirects so a tampered link can't move the credentialed request off-host and
        # leak the Basic auth credentials (SSRF). Empty list => same host as base_url only.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _get_team_id(username: str, api_token: str) -> str:
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
    response = session.get(f"{GURU_BASE_URL}/whoami", auth=HTTPBasicAuth(username, api_token), timeout=30)
    response.raise_for_status()
    return response.json()["team"]["id"]


def _primary_keys(config: GuruEndpointConfig) -> list[str]:
    return config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]


def validate_credentials(username: str, api_token: str) -> bool:
    """Confirm the user token is valid. /whoami is a cheap authenticated probe."""
    ok, _status = validate_via_probe(
        # Redirects pinned off on the session so a 3xx can't carry the Basic-auth credential off-host.
        lambda: make_tracked_session(redact_values=(api_token,), allow_redirects=False),
        f"{GURU_BASE_URL}/whoami",
        auth=HTTPBasicAuth(username, api_token),
    )
    return ok


def _fanout_source(
    username: str,
    api_token: str,
    config: GuruEndpointConfig,
    fanout: DependentEndpointConfig,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    resource = build_dependent_resource(
        endpoint_configs=GURU_ENDPOINTS,
        child_endpoint=config.name,
        fanout=fanout,
        client_config=_client_config(username, api_token),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        # Guru child endpoints have no server-side time filter, so fan-out is always full refresh.
        db_incremental_field_last_value=None,
        parent_endpoint_extra={"data_selector_required": True},
        child_endpoint_extra={"data_selector_required": True},
        page_size_param=None,
    )
    child = cast(Resource, resource)
    if config.name == "group_members":
        child = child.add_map(_normalize_member)

    return SourceResponse(
        name=config.name,
        items=lambda: child,
        primary_keys=_primary_keys(config),
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def guru_source(
    username: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GuruResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = GURU_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(username, api_token, config, config.fanout, team_id, job_id)

    path = config.path
    if "{team_id}" in path:
        path = path.replace("{team_id}", quote(_get_team_id(username, api_token), safe=""))

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        # Guru returns a bare JSON array; a non-list 200 body means the response shape
        # changed — fail loud instead of wrapping the stray object as a single row.
        "data_selector_required": True,
    }
    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": endpoint_config,
    }
    if endpoint == "members":
        resource_config["data_map"] = _normalize_member
    elif endpoint == "tags":
        resource_config["data_map"] = _flatten_tag_category
    elif endpoint == "analytics_events":
        resource_config["data_map"] = _ensure_event_id

    rest_config: RESTAPIConfig = {
        "client": _client_config(username, api_token),
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(GuruResumeConfig(next_url=state["next_url"]))

    # Incremental filtering is server-side and already baked into `params` above, so the
    # framework's incremental injection is unused here.
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=_primary_keys(config),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Guru documents no order for the analytics export, so "desc" defers the watermark
        # commit to the end of the run instead of checkpointing it after each batch.
        sort_mode="desc" if config.date_filter_param else "asc",
        column_hints=resource.column_hints,
    )
