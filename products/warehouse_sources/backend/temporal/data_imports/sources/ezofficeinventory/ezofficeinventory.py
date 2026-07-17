import re
import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import (
    EZOFFICEINVENTORY_ENDPOINTS,
    EZOfficeInventoryEndpointConfig,
)

# EZOfficeInventory enforces a per-account hostname, so only the subdomain label is user-supplied.
# Restricting it to host-safe characters keeps the request pinned to *.ezofficeinventory.com.
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")


@dataclasses.dataclass
class EZOfficeInventoryResumeConfig:
    # Next page (1-indexed) to fetch when resuming an interrupted sync.
    next_page: int


def base_url(subdomain: str) -> str:
    return f"https://{subdomain}.ezofficeinventory.com"


def _make_unwrap_map(unwrap_key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Some list endpoints wrap each record in a single-key object (e.g. groups returns
    `{"groups": [{"group": {...}}]}`); unwrap it, falling back to the row untouched when the
    inner key is absent (a row already shaped like the unwrapped object)."""

    def _unwrap(item: dict[str, Any]) -> dict[str, Any]:
        if isinstance(item, dict) and unwrap_key in item:
            return item[unwrap_key]
        return item

    return _unwrap


def _rest_config(subdomain: str, api_key: str, config: EZOfficeInventoryEndpointConfig) -> RESTAPIConfig:
    endpoint: dict[str, Any] = {
        "path": config.path,
        "params": dict(config.extra_params),
        "data_selector": config.data_selector,
        # `total_pages` is the total number of PAGES; the paginator stops after it. When the API
        # omits it, an empty page terminates instead (stop_after_empty_page).
        "paginator": PageNumberPaginator(base_page=1, page=1, page_param="page", total_path="total_pages"),
    }
    resource: dict[str, Any] = {"name": config.name, "endpoint": endpoint}
    if config.unwrap_key:
        resource["data_map"] = _make_unwrap_map(config.unwrap_key)

    return {
        "client": {
            "base_url": base_url(subdomain),
            # Auth (token header) is supplied via the framework auth config so its value is redacted
            # from logs and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "token", "location": "header"},
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
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = EZOFFICEINVENTORY_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the page we just emitted rather than skipping it — merge dedupes the re-yielded rows.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(EZOfficeInventoryResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        _rest_config(subdomain, api_key, config),
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


def validate_credentials(api_key: str, subdomain: str) -> tuple[bool, str | None]:
    """Return (is_valid, error_message). A non-None message overrides the generic
    "invalid credentials" error so transient failures (e.g. rate limiting) aren't
    misreported as bad credentials."""
    if not SUBDOMAIN_REGEX.match(subdomain):
        return False, None

    ok, status = validate_via_probe(
        # Redirects pinned off and urllib3 retries disabled so the token can't be replayed to a
        # cross-host redirect target during a single-shot probe.
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0)),
        f"{base_url(subdomain)}/assets.api?page=1",
        headers={"token": api_key, "Accept": "application/json"},
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
