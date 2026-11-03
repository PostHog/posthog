from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from requests import RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.plane.settings import (
    API_PATH,
    DEFAULT_BASE_URL,
    ENDPOINTS,
)

INVALID_KEY_MESSAGE = "Plane rejected your API key. Create a new personal access token in Plane and reconnect."
WORKSPACE_MESSAGE = (
    "Plane couldn't find that workspace. Check the workspace slug, the part after the domain in your Plane URL."
)
PERMISSION_MESSAGE = "Your Plane API key can't read this workspace. Use a key from a member of the workspace."
INVALID_URL_MESSAGE = "Enter your Plane instance URL as https://plane.example.com, or leave it blank for Plane Cloud."
SLUG_MESSAGE = "Enter the workspace slug only, without a URL or slashes."

# A self-hosted instance answers far below the vendor's 5 minute ceiling; keep a stalled one from
# holding the worker.
REQUEST_TIMEOUT = (10, 60)


@frozen
class PlaneResumeConfig:
    paginator_state: dict[str, Any]


def normalize_base_url(base_url: str | None) -> str:
    """Return the instance origin, https only, with nothing that could aim the key elsewhere."""
    value = (base_url or "").strip() or DEFAULT_BASE_URL
    if "://" not in value:
        value = f"https://{value}"
    value = value.rstrip("/")
    lowered = value.lower()
    # A backslash or an encoded authority delimiter makes urlparse and requests disagree on the host.
    if "\\" in value or "%5c" in lowered or "%40" in lowered or "@" in value:
        raise ValueError(INVALID_URL_MESSAGE)
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        raise ValueError(INVALID_URL_MESSAGE)
    if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError(INVALID_URL_MESSAGE)
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"https://{host}{f':{port}' if port else ''}{parsed.path}"


def hostname_of(base_url: str | None) -> str:
    return urlparse(normalize_base_url(base_url)).hostname or ""


def validate_slug(slug: str) -> str:
    stripped = slug.strip()
    if not stripped or not all(char.isalnum() or char in "-_" for char in stripped):
        raise ValueError(SLUG_MESSAGE)
    return stripped


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        moment = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return moment.isoformat().replace("+00:00", "Z")
    return str(value)


def _client_config(base_url: str | None, api_key: str) -> ClientConfig:
    return {
        "base_url": f"{normalize_base_url(base_url)}{API_PATH}",
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-Api-Key", "location": "header"},
        "headers": {"Accept": "application/json"},
        # The base URL is customer-chosen, so a redirect must not carry the key to another host.
        "allow_redirects": False,
        "allowed_hosts": [],
        "request_timeout": REQUEST_TIMEOUT,
    }


def _paginator() -> BasePaginator:
    # A server that keeps answering with the cursor it was sent would otherwise loop until the
    # activity times out.
    return JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor", raise_on_repeated_cursor=True)


def get_resource(
    base_url: str | None,
    api_key: str,
    workspace_slug: str,
    endpoint_name: str,
    team_id: int,
    job_id: str,
    incremental_field: str | None = None,
    db_incremental_field_last_value: Any = None,
    resume_hook: Callable[[dict[str, Any] | None], None] | None = None,
    initial_paginator_state: dict[str, Any] | None = None,
) -> Iterable[Any]:
    slug = validate_slug(workspace_slug)
    endpoint = ENDPOINTS[endpoint_name]
    client = _client_config(base_url, api_key)

    if endpoint.fanout is not None:
        return build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint_name,
            fanout=endpoint.fanout,
            client_config=client,
            path_format_values={"slug": slug},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param="per_page",
            parent_endpoint_extra={"data_selector": "data", "data_selector_required": True, "paginator": _paginator()},
            child_endpoint_extra={"data_selector": "data", "data_selector_required": True, "paginator": _paginator()},
            resume_hook=resume_hook,
            initial_paginator_state=initial_paginator_state,
        )

    params: dict[str, Any] = {**endpoint.params, "per_page": endpoint.page_size}
    endpoint_config: Endpoint = {
        "path": endpoint.path.replace("{slug}", slug),
        "params": params,
        "data_selector": "data",
        "data_selector_required": True,
        "paginator": _paginator(),
    }
    if incremental_field is not None:
        # An incremental walk climbs the field it filters on; both fields are cursor-eligible.
        params["order_by"] = incremental_field
    if incremental_field is not None and db_incremental_field_last_value is not None:
        incremental: IncrementalConfig = {
            "cursor_path": incremental_field,
            "start_param": f"{incremental_field}__gte",
            "convert": _to_iso,
        }
        endpoint_config["incremental"] = incremental

    config: RESTAPIConfig = {
        "client": client,
        "resources": [
            {
                "name": endpoint_name,
                "endpoint": endpoint_config,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental_field else "replace",
                "table_format": "delta",
            }
        ],
    }
    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )


def plane_source(
    base_url: str | None,
    api_key: str,
    workspace_slug: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[PlaneResumeConfig],
) -> SourceResponse:
    endpoint = ENDPOINTS[inputs.schema_name]
    incremental_field = None
    if inputs.should_use_incremental_field and endpoint.incremental_fields:
        incremental_field = inputs.incremental_field or endpoint.default_incremental_field
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state:
            manager.save_state(PlaneResumeConfig(paginator_state=state))

    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: get_resource(
            base_url,
            api_key,
            workspace_slug,
            inputs.schema_name,
            inputs.team_id,
            inputs.job_id,
            incremental_field=incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value if incremental_field else None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        ),
        primary_keys=endpoint.primary_keys,
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        sort_mode="asc",
    )


def probe_workspace(base_url: str | None, api_key: str, workspace_slug: str) -> int | None:
    """Status of checking the key, then the workspace, with one cheap request each.

    Plane looks the workspace up before it checks the key, so a wrong key on a wrong slug answers
    404. Asking for the key's own user first keeps the two mistakes apart.
    """
    origin = f"{normalize_base_url(base_url)}{API_PATH}"
    slug = validate_slug(workspace_slug)
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    try:
        # Only the status matters; stream so a customer-chosen host can't make us buffer a large body.
        with session.get(f"{origin}/users/me/", headers=headers, timeout=REQUEST_TIMEOUT, stream=True) as me:
            if me.status_code != 200:
                return me.status_code
        with session.get(
            f"{origin}/workspaces/{slug}/projects/",
            params={"per_page": "1", "count": "false"},
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            stream=True,
        ) as projects:
            return projects.status_code
    except RequestException:
        return None
