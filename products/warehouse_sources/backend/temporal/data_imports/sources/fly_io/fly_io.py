from typing import Any
from urllib.parse import quote

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.settings import (
    FLY_IO_ENDPOINTS,
    FlyIoEndpointConfig,
)

FLY_IO_BASE_URL = "https://api.machines.dev/v1"

# Advisory page size for the cursor-paginated org endpoints (the API caps it at 1000).
_PAGE_SIZE = 1000

# A Fly machine's `config` can embed deployment secrets, so we sync only an operational
# allowlist (the "overview" the canonical description promises) rather than the raw object.
# Anything not listed here — notably `env`, `files` (whose entries carry inline file
# contents in `raw_value`), and `secrets` — is dropped before the row reaches the warehouse.
_SAFE_MACHINE_CONFIG_KEYS = frozenset(
    {
        "guest",
        "image",
        "metadata",
        "services",
        "checks",
        "restart",
        "mounts",
        "metrics",
        "init",
        "processes",
        "auto_destroy",
        "schedule",
        "dns",
        "size",
        "standbys",
        "statics",
        "stop_config",
    }
)

# A machine's per-process config entries repeat the same secret vectors as the top level.
_PROCESS_SECRET_KEYS = frozenset({"env", "secrets"})

# `metadata` is a free-form user key/value map, so a value like `metadata.api_token` would
# otherwise reach the warehouse. Only Fly's own platform-set keys are known-safe; everything
# else is dropped.
_SAFE_METADATA_KEYS = frozenset(
    {
        "fly_platform_version",
        "fly_process_group",
        "fly_release_id",
        "fly_release_version",
        "fly_flyctl_version",
        "fly_managed_postgres",
    }
)


def _strip_headers(value: Any) -> Any:
    """Recursively drop every `headers` mapping from a nested structure. Fly service and check
    definitions can carry request headers (e.g. a health-check `Authorization`), a credential
    vector we never want to land in the warehouse."""
    if isinstance(value, dict):
        return {key: _strip_headers(item) for key, item in value.items() if key != "headers"}
    if isinstance(value, list):
        return [_strip_headers(item) for item in value]
    return value


def _sanitize_machine_config(config: dict[str, Any]) -> dict[str, Any]:
    safe = {key: value for key, value in config.items() if key in _SAFE_MACHINE_CONFIG_KEYS}
    # `metadata` is user-defined free-form key/values; keep only Fly's own platform keys so a
    # user-set secret (e.g. `metadata.api_token`) can't slip through the allowlist.
    metadata = safe.get("metadata")
    if isinstance(metadata, dict):
        safe["metadata"] = {key: value for key, value in metadata.items() if key in _SAFE_METADATA_KEYS}
    # `processes` is operational (cmd/entrypoint/guest) but each entry can carry its own
    # `env`/`secrets`, so strip those while keeping the rest of the process definition.
    processes = safe.get("processes")
    if isinstance(processes, list):
        safe["processes"] = [
            {key: value for key, value in process.items() if key not in _PROCESS_SECRET_KEYS}
            if isinstance(process, dict)
            else process
            for process in processes
        ]
    # Final defensive pass: `services`/`checks` (and anything nested under them) can embed
    # request-header maps that carry credentials — drop them wherever they appear.
    return _strip_headers(safe)


def _sanitize_machine(row: dict[str, Any]) -> dict[str, Any]:
    config = row.get("config")
    if isinstance(config, dict):
        return {**row, "config": _sanitize_machine_config(config)}
    return row


def _endpoint_path(config: FlyIoEndpointConfig, org_slug: str) -> str:
    """The org-scoped endpoints carry the org in the path; encode the slug so a reserved
    character (e.g. `/`) can't retarget the request to a different API path than the one
    credential validation checked. The apps endpoint takes org_slug as a query param instead."""
    if "{org_slug}" in config.path:
        return config.path.format(org_slug=quote(org_slug, safe=""))
    return config.path


def _endpoint_params(config: FlyIoEndpointConfig, org_slug: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if "{org_slug}" not in config.path:
        params["org_slug"] = org_slug
    if config.paginated:
        params["limit"] = _PAGE_SIZE
    return params


def validate_credentials(api_token: str, org_slug: str) -> tuple[bool, str | None]:
    """Probe the apps endpoint to confirm the token is genuine and the org is reachable."""
    url = f"{FLY_IO_BASE_URL}/apps?org_slug={quote(org_slug, safe='')}"
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Fly.io API token. Create a new token with `fly tokens create org` and reconnect."
    if status in (403, 404):
        return False, f"Organization '{org_slug}' was not found or is not accessible with this token."
    if status is None:
        return False, "Could not reach the Fly.io API to validate the token."
    return False, f"Fly.io API returned an unexpected status ({status})."


def fly_io_source(
    api_token: str,
    endpoint: str,
    org_slug: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    """Build the rest_source resource for a Fly.io stream. The org machines/volumes endpoints
    paginate with an opaque `next_cursor`; the apps endpoint returns everything in one response.
    Rows are yielded in the shape the API returns them, except the machines stream, whose rows can
    embed deployment secrets: those are reduced to a safe operational allowlist and the stream opts
    out of HTTP sample capture, so secrets reach neither the warehouse nor the sample pipeline."""
    config = FLY_IO_ENDPOINTS[endpoint]

    paginator = (
        JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")
        if config.paginated
        else SinglePagePaginator()
    )

    client_config: dict[str, Any] = {
        "base_url": FLY_IO_BASE_URL,
        # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
        # logs and raised errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
    }
    if config.redact_secrets:
        # A stream whose bodies can carry secrets opts out of HTTP sample capture (still logged
        # and metered) so those secrets never land in the sample-capture pipeline. The token is
        # still masked in whatever remains logged.
        client_config["session"] = make_tracked_session(capture=False, redact_values=(api_token,))

    endpoint_config: dict[str, Any] = {
        "path": _endpoint_path(config, org_slug),
        "params": _endpoint_params(config, org_slug),
        "paginator": paginator,
        "data_selector": config.response_data_path,
        # Every list endpoint wraps its rows in an object ({"apps": [...]} etc.). A 200 body that
        # isn't that shape (a bare list, or the wrapper key gone) means the API changed — fail loud
        # rather than silently syncing zero rows, which would look like a successful-but-empty sync.
        "data_selector_required": True,
    }

    resource_config: dict[str, Any] = {"name": endpoint, "endpoint": endpoint_config}
    if config.redact_secrets:
        resource_config["data_map"] = _sanitize_machine

    rest_config: RESTAPIConfig = {"client": client_config, "resources": [resource_config]}

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
