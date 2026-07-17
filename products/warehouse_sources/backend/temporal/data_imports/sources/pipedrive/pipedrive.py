import re
import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.settings import (
    PIPEDRIVE_ENDPOINTS,
    PipedriveEndpointConfig,
)

# Pipedrive caps list pages at 500 items (default 100).
PAGE_SIZE = 500

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9-]+$")

# Never reflects the raw input back: it can be a full URL or website domain the user pasted by
# mistake, and echoing it gives no guidance on what a valid value looks like.
_INVALID_COMPANY_DOMAIN_ERROR = (
    "Invalid Pipedrive company domain. Enter just your Pipedrive subdomain — the part before "
    ".pipedrive.com (for example, enter 'acme' for acme.pipedrive.com) — not a full URL or your "
    "website's domain."
)


@dataclasses.dataclass
class PipedriveResumeConfig:
    # Legacy field written by the hand-rolled paginator: the full next-page URL. Kept (optional,
    # defaulted) so previously saved resume state still parses via ``dataclass(**saved)``. No longer
    # written; a resume that carries only this restarts the endpoint from the beginning (merge
    # dedupes any re-yielded rows).
    next_url: Optional[str] = None
    # Framework paginator resume snapshot: ``{"offset": N}`` for v1 offset endpoints or
    # ``{"cursor": "…"}`` for v2 cursor endpoints. Seeds ``initial_paginator_state`` on resume.
    paginator_state: Optional[dict[str, Any]] = None


def normalize_company_domain(raw: str) -> str:
    """Reduce whatever the user typed to the bare Pipedrive subdomain.

    Accepts ``mycompany``, ``mycompany.pipedrive.com`` or ``https://mycompany.pipedrive.com``.
    Raises ``ValueError`` if the result isn't a plain subdomain, which also pins outbound
    traffic to ``*.pipedrive.com`` (no SSRF to arbitrary hosts).
    """
    domain = raw.strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    domain = domain.removesuffix(".pipedrive.com")
    if not _SUBDOMAIN_RE.match(domain):
        raise ValueError(_INVALID_COMPANY_DOMAIN_ERROR)
    return domain


def base_url(company_domain: str) -> str:
    return f"https://{normalize_company_domain(company_domain)}.pipedrive.com"


def _get_headers(api_token: str) -> dict[str, str]:
    return {"x-api-token": api_token, "Accept": "application/json"}


def _build_url(company_domain: str, path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    url = f"{base_url(company_domain)}{path}"
    if not clean_params:
        return url
    return f"{url}?{urlencode(clean_params)}"


def _build_paginator(config: PipedriveEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        # v2 endpoints: opaque cursor in the response body; ``limit`` rides in the endpoint params.
        return JSONResponseCursorPaginator(cursor_path="additional_data.next_cursor", cursor_param="cursor")
    # v1 endpoints: start/limit offset. No top-level total; termination is a short/empty page.
    return OffsetPaginator(
        limit=PAGE_SIZE,
        offset=0,
        offset_param="start",
        limit_param="limit",
        total_path=None,
        stop_after_empty_page=True,
    )


def validate_credentials(company_domain: str, api_token: str) -> Optional[int]:
    """Return the status code of a cheap authenticated probe, or ``None`` on transport error.

    ``/api/v1/users/me`` resolves the token's own user and is reachable by any valid token.
    """
    # Built outside the probe so an invalid-domain `ValueError` from `_build_url` propagates to the
    # caller rather than being swallowed into `None` by the probe's broad transport-error handler.
    url = _build_url(company_domain, "/api/v1/users/me", {})
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers=_get_headers(api_token),
    )
    return status


def pipedrive_source(
    company_domain: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PipedriveResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PIPEDRIVE_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.pagination == "cursor":
        # The cursor paginator only injects ``cursor``; ``limit`` must be a static param.
        params["limit"] = PAGE_SIZE

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(company_domain),
            # Only the non-secret Accept header here; the token travels via framework auth so it's
            # redacted from logged URLs, headers, sampled bodies, and raised error messages.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_token, "name": "x-api-token", "location": "header"},
            "paginator": _build_paginator(config),
            # base_url host (`{subdomain}.pipedrive.com`) is implicitly allowed; `[]` pins every
            # request — including resume URLs — to it, matching the source's SSRF posture.
            "allowed_hosts": [],
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Mirrors the old `data.get("data") or []`: a 200 body without `data` yields an
                    # empty page rather than raising (not required).
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only new-shape paginator state can seed a resume; legacy `next_url`-only state restarts
        # the endpoint from the beginning (merge dedupes the re-yielded rows).
        if resume is not None and resume.paginator_state:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; saved AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state:
            resumable_source_manager.save_state(PipedriveResumeConfig(paginator_state=state))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
