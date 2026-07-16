import re
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.settings import (
    BAMBOOHR_ENDPOINTS,
    BambooHREndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

# BambooHR's API is served through a single gateway host; the company subdomain is a path segment.
# Confirmed live: the gateway returns 401 (not 404) for the v1 paths below, so the route shape is correct.
BAMBOOHR_API_HOST = "https://api.bamboohr.com/api/gateway.php"
# Basic auth uses the API key as the username and any non-empty string as the password.
BAMBOOHR_BASIC_AUTH_PASSWORD = "x"
# Credential validation is a single cheap probe; keep it snappy so source creation doesn't feel hung.
VALIDATE_TIMEOUT_SECONDS = 10
# Time-off endpoints require an explicit window; widen it enough to capture all history and pending future requests.
TIME_OFF_WINDOW_START = "2000-01-01"
TIME_OFF_FUTURE_DAYS = 730

# A BambooHR company subdomain is the "<company>" slug from <company>.bamboohr.com — letters, digits,
# and hyphens only. It's an editable, non-secret field spliced straight into the request path, so pin
# it to this allowlist before building any URL. Without it a value like "acme/v1/employees/123?" would
# inject extra path segments / query params and redirect the authenticated request (which carries the
# API key in its Basic auth header) at an arbitrary BambooHR endpoint.
SUBDOMAIN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
INVALID_SUBDOMAIN_MESSAGE = (
    "Invalid BambooHR company subdomain. Use only the company name from your BambooHR URL "
    "(letters, digits, and hyphens)."
)


def _validate_subdomain(subdomain: str) -> None:
    if not SUBDOMAIN_PATTERN.fullmatch(subdomain):
        raise ValueError(f"Invalid BambooHR subdomain: {subdomain!r}")


@dataclasses.dataclass
class BambooHRResumeConfig:
    next_url: str


def _base_url(subdomain: str) -> str:
    _validate_subdomain(subdomain)
    return f"{BAMBOOHR_API_HOST}/{subdomain}/v1"


class BambooHRBasicAuth(HttpBasicAuth):
    """Basic auth where the *username* is the secret (the API key), so redact it instead of the password."""

    def secret_values(self) -> tuple[str, ...]:
        return (self.username,) if self.username else ()


def _next_url(payload: Any) -> str | None:
    """Follow BambooHR's cursor pagination if the response advertises a next page.

    Classic endpoints (directory, meta, time off) return everything in a single response with no
    ``_links``, so this yields once. Cursor-paginated endpoints expose a full URL under ``_links.next``.
    """
    if not isinstance(payload, dict):
        return None
    links = payload.get("_links")
    if links is None:
        links = payload.get("links")
    if not isinstance(links, dict):
        return None
    next_link = links.get("next")
    # Only follow pagination URLs that stay on the canonical BambooHR gateway host, so a
    # tampered or compromised API response can't point our authenticated request at an internal
    # address (SSRF) and leak the API key carried in the Basic auth header.
    if isinstance(next_link, str) and next_link.startswith(BAMBOOHR_API_HOST):
        return next_link
    return None


class BambooHRPaginator(BaseNextUrlPaginator):
    """Follows the full next-page URL BambooHR returns under ``_links.next`` (or ``links.next``),
    pinned to the gateway host via ``_next_url``."""

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        next_url = _next_url(payload)
        if next_url:
            self._next_url = next_url
            self._has_next_page = True
        else:
            self._has_next_page = False

    def __str__(self) -> str:
        return "BambooHRPaginator(_links.next|links.next)"


def _selector_for(config: BambooHREndpointConfig) -> tuple[str | None, bool]:
    """Map an endpoint's response layout to a (data_selector, data_selector_required) pair.

    - "dict" shape (e.g. ``meta/users`` — ``{"<id>": {...}}``): the ``*`` wildcard flattens the
      object to its values; not required so an empty account (empty object) is a legit 0-row page.
    - Enveloped list (``data_key``): select the key and fail loudly when it's absent (an API
      change) rather than silently syncing zero rows.
    - Bare list body: no selector; require a list so an unexpected 200 envelope fails loudly
      instead of being wrapped as a garbage row.
    """
    if config.data_shape == "dict":
        return "*", False
    if config.data_key is not None:
        return config.data_key, True
    return None, True


def bamboohr_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BambooHRResumeConfig],
) -> SourceResponse:
    config = BAMBOOHR_ENDPOINTS[endpoint]
    base_url = _base_url(subdomain)

    params: dict[str, Any] = {}
    if config.requires_date_window:
        end = (datetime.now(UTC) + timedelta(days=TIME_OFF_FUTURE_DAYS)).strftime("%Y-%m-%d")
        params = {"start": TIME_OFF_WINDOW_START, "end": end}

    data_selector, data_selector_required = _selector_for(config)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "headers": {"Accept": "application/json"},
            # Auth goes through the framework config so the API key is redacted from logs;
            # only the non-secret Accept header is set on the session.
            "auth": BambooHRBasicAuth(username=api_key, password=BAMBOOHR_BASIC_AUTH_PASSWORD),
            "paginator": BambooHRPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": data_selector,
                    "data_selector_required": data_selector_required,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            # Guard the persisted resume URL too — only ever saved from _next_url (host-pinned),
            # but re-check so a tampered Redis state can't redirect our authenticated request.
            if not resume.next_url.startswith(BAMBOOHR_API_HOST):
                raise ValueError(f"BambooHR resume state contains an unexpected URL: {resume.next_url!r}")
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the hook fires AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on PK) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(BambooHRResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every BambooHR stream is full-refresh (see settings.py)
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
    )


def validate_credentials(subdomain: str, api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Cheap probe against ``meta/fields`` to confirm the subdomain + API key are genuine.

    A 403 means the key is valid but lacks scope for this endpoint — accept it at source-create
    (``schema_name is None``) since users may only grant the scopes they intend to sync.
    """
    try:
        url = f"{_base_url(subdomain)}/meta/fields"
    except ValueError:
        return False, INVALID_SUBDOMAIN_MESSAGE

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Accept": "application/json"},
        auth=BambooHRBasicAuth(username=api_key, password=BAMBOOHR_BASIC_AUTH_PASSWORD),
        timeout=VALIDATE_TIMEOUT_SECONDS,
    )

    if ok:
        return True, None
    if status is None:
        return False, "Could not connect to BambooHR. Check the company subdomain and try again."
    if status == 401:
        return False, "Invalid BambooHR API key."
    if status == 404:
        return False, "BambooHR company subdomain not found. Use the subdomain from your BambooHR URL."
    if status == 403:
        if schema_name is None:
            return True, None
        return False, "Your BambooHR API key does not have permission to access this data."
    return False, f"BambooHR API returned an unexpected status code: {status}"
