import re
import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponsePaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ApiKeyAuthConfig,
    AuthConfig,
    BearerTokenAuthConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import (
    EZOFFICEINVENTORY_API_VERSION_V2,
    EZOfficeInventoryEndpointConfig,
    endpoints_for_version,
)

# EZOfficeInventory enforces a per-account hostname, so only the subdomain label is user-supplied.
# Restricting it to host-safe characters keeps the request pinned to *.ezofficeinventory.com.
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")


@dataclasses.dataclass
class EZOfficeInventoryResumeConfig:
    # v1 page-number paginator: next page (1-indexed) to fetch when resuming an interrupted sync.
    next_page: Optional[int] = None
    # v2 next-URL paginator: absolute URL of the next page to fetch when resuming.
    next_url: Optional[str] = None


def base_url(subdomain: str) -> str:
    return f"https://{subdomain}.ezofficeinventory.com"


def _auth_config(api_version: str, api_key: str) -> AuthConfig:
    # v2 authenticates with `Authorization: Bearer <token>`; v1 sends the token in a `token`
    # header. Either way the value is supplied via the framework auth config so it's redacted
    # from logs and raised error messages.
    if api_version == EZOFFICEINVENTORY_API_VERSION_V2:
        return BearerTokenAuthConfig(type="bearer", token=api_key)
    return ApiKeyAuthConfig(type="api_key", api_key=api_key, name="token", location="header")


def _paginator(api_version: str) -> BasePaginator:
    if api_version == EZOFFICEINVENTORY_API_VERSION_V2:
        # v2 returns a self-contained absolute URL for the next page under `metadata.next_page`
        # (null on the last page); follow it. `allowed_hosts=[]` still pins it to the subdomain.
        return JSONResponsePaginator(next_url_path="metadata.next_page")
    # `total_pages` is the total number of PAGES; the paginator stops after it. When the API
    # omits it, an empty page terminates instead (stop_after_empty_page).
    return PageNumberPaginator(base_page=1, page=1, page_param="page", total_path="total_pages")


def _make_unwrap_map(unwrap_key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Some list endpoints wrap each record in a single-key object (e.g. groups returns
    `{"groups": [{"group": {...}}]}`); unwrap it, falling back to the row untouched when the
    inner key is absent (a row already shaped like the unwrapped object)."""

    def _unwrap(item: dict[str, Any]) -> dict[str, Any]:
        if isinstance(item, dict) and unwrap_key in item:
            return item[unwrap_key]
        return item

    return _unwrap


def _rest_config(
    subdomain: str, api_key: str, config: EZOfficeInventoryEndpointConfig, api_version: str
) -> RESTAPIConfig:
    endpoint: Endpoint = {
        "path": config.path,
        "params": dict(config.extra_params),
        "data_selector": config.data_selector,
        "paginator": _paginator(api_version),
    }
    resource: EndpointResource = {"name": config.name, "endpoint": endpoint}
    if config.unwrap_key:
        resource["data_map"] = _make_unwrap_map(config.unwrap_key)

    return {
        "client": {
            "base_url": base_url(subdomain),
            # Only the non-secret Accept header is set here; the token goes through the auth config.
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(api_version, api_key),
            # Pin every request (including paginator/resume URLs) to the subdomain host and reject
            # cross-host redirects — the user-supplied token must not be replayable off-host
            # (SSRF / credential-exfiltration defense-in-depth). `allowed_hosts=[]` means
            # "same host as base_url only".
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [resource],
    }


def ezofficeinventory_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EZOfficeInventoryResumeConfig],
    api_version: str,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = endpoints_for_version(api_version)[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if resume.next_url is not None:
                initial_paginator_state = {"next_url": resume.next_url}
            elif resume.next_page is not None:
                initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the page we just emitted rather than skipping it — merge dedupes the re-yielded rows. The
        # paginator dictates the checkpoint shape: v2 carries a next-URL, v1 a page number.
        if not state:
            return
        if state.get("next_url"):
            resumable_source_manager.save_state(EZOfficeInventoryResumeConfig(next_url=str(state["next_url"])))
        elif state.get("page") is not None:
            resumable_source_manager.save_state(EZOfficeInventoryResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        _rest_config(subdomain, api_key, config, api_version),
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, subdomain: str, api_version: str) -> tuple[bool, str | None]:
    """Return (is_valid, error_message). A non-None message overrides the generic
    "invalid credentials" error so transient failures (e.g. rate limiting) aren't
    misreported as bad credentials."""
    if not SUBDOMAIN_REGEX.match(subdomain):
        return False, None

    # Probe the assets list under the resolved version so a passing probe reflects the same
    # base path and auth scheme the sync will use, not just that the token is well-formed.
    if api_version == EZOFFICEINVENTORY_API_VERSION_V2:
        probe_url = f"{base_url(subdomain)}/api/v2/assets"
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    else:
        probe_url = f"{base_url(subdomain)}/assets.api?page=1"
        headers = {"token": api_key, "Accept": "application/json"}

    ok, status = validate_via_probe(
        # Redirects pinned off and urllib3 retries disabled so the token can't be replayed to a
        # cross-host redirect target during a single-shot probe.
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0)),
        probe_url,
        headers=headers,
    )
    if ok:
        return True, None

    # The fair-use cap is ~60 req/min; a 429 here means we couldn't verify the token, not that it's
    # wrong. Surface that distinctly so the user isn't told their credentials are invalid.
    if status == 429:
        return (
            False,
            "EZOfficeInventory rate limit reached while validating credentials. Please wait a minute and try again.",
        )

    return False, None
