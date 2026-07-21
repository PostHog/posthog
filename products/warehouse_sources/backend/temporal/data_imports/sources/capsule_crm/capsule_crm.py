import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit

from requests import Response
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.settings import CAPSULE_CRM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

CAPSULE_CRM_BASE_URL = "https://api.capsulecrm.com/api/v2"
CAPSULE_CRM_HOST = "api.capsulecrm.com"
CAPSULE_CRM_PATH_PREFIX = "/api/v2/"

# Capsule caps perPage at 100; always request the max to minimize round-trips.
PAGE_SIZE = 100


class CapsuleCRMUntrustedURLError(Exception):
    """A pagination URL (resumed or upstream) pointed somewhere other than the Capsule CRM API."""


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Capsule CRM API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `Link` header URLs are followed
    verbatim with the customer's bearer token. Validating the scheme, host, and `/api/v2/` path prefix
    keeps a poisoned resume state or a hostile upstream response from retargeting the request at another
    host and leaking the token (SSRF). Returns the URL unchanged when it is trusted.
    """
    parts = urlsplit(url)
    is_trusted = (
        parts.scheme == "https" and parts.netloc == CAPSULE_CRM_HOST and parts.path.startswith(CAPSULE_CRM_PATH_PREFIX)
    )
    if not is_trusted:
        raise CapsuleCRMUntrustedURLError(f"Refusing to follow pagination URL outside {CAPSULE_CRM_BASE_URL}/")
    return url


class CapsuleCRMLinkPaginator(HeaderLinkPaginator):
    """`HeaderLinkPaginator` that pins every followed or resumed next-page URL to the Capsule API.

    Rejecting the URL in `update_state` (before the page is yielded) also keeps a poisoned URL from
    ever reaching the resume checkpoint.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url:
            _validate_pagination_url(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None:
            # Resume state comes from Redis — validate before sending the token to it.
            _validate_pagination_url(next_url)
        super().set_resume_state(state)


@dataclasses.dataclass
class CapsuleCRMResumeConfig:
    # Absolute URL of the next page (from the RFC 5988 Link header). Capsule echoes the original
    # query params — perPage, embed and `since` — into this URL, so resuming from it preserves the
    # incremental window without recomputing it. None means "start from the first page".
    next_url: str | None = None


def _format_since_value(value: Any) -> str:
    """Format a cursor value as the ISO 8601 `Z`-suffixed UTC string Capsule's `since` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now.

    If bad source data pushes the `updatedAt` cursor past now, every later sync would ask Capsule
    for changes since a future date and get nothing back, wedging the table until real data catches
    up. Asking for changes newer than now is a no-op anyway, so clamping lets the sync self-heal.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def capsule_crm_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CapsuleCRMResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CAPSULE_CRM_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"perPage": PAGE_SIZE}
    if config.embed:
        params["embed"] = config.embed
    if config.supports_since and should_use_incremental_field and db_incremental_field_last_value is not None:
        params["since"] = _format_since_value(_clamp_future_value_to_now(db_incremental_field_last_value))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CAPSULE_CRM_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": access_token},
            # A custom session pins `allow_redirects` off so a redirect response can't send the
            # bearer token to another host; `redact_values` masks the token in logged URLs and
            # captured request samples.
            "session": make_tracked_session(redact_values=(access_token,), allow_redirects=False),
            # Capsule signals pagination via the RFC 5988 `Link` header (rel="next"), not the body.
            "paginator": CapsuleCRMLinkPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A missing wrapper key is tolerated as a zero-row page (Capsule omits it on
                    # some empty responses), so the selector is not required.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework calls this AFTER a page is yielded so
        # a crash re-yields the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(CapsuleCRMResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
        # Capsule does not document an ordering guarantee for `since`, but the ResumableSource
        # next-URL state (not the watermark) drives mid-sync resume, so the dominant interruption
        # path is order-independent. `asc` matches the framework's default incremental checkpointing.
        sort_mode="asc",
    )


def validate_credentials(access_token: str) -> bool:
    """Probe a cheap, always-available endpoint to confirm the access token is genuine."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,), allow_redirects=False, retry=Retry(total=0)),
        f"{CAPSULE_CRM_BASE_URL}/users?perPage=1",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    return ok
