import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.settings import (
    SENDGRID_ENDPOINTS,
    SendGridEndpointConfig,
)

SENDGRID_BASE_URL = "https://api.sendgrid.com/v3"


@dataclasses.dataclass
class SendGridResumeConfig:
    # Full next-page URL to fetch within the current sync. Set by metadata pagination (the API
    # hands us the whole next URL) and by pre-migration saved states (which stored the offset URL
    # for offset pagination too). Optional so old single-field states still parse.
    next_url: Optional[str] = None
    # Row offset of the next unfetched page (offset pagination).
    offset: Optional[int] = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _to_epoch_seconds(value: Any) -> int:
    """Coerce an incremental cursor value to Unix epoch seconds for the `start_time` filter.

    SendGrid's suppression `created` field is already epoch seconds, but the pipeline may hand
    the cursor back as a datetime/date depending on how it round-tripped through storage.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    return int(value)


def _offset_from_url(url: str) -> int:
    """Recover the `offset` query param so a resumed offset-paginated sync keeps advancing."""
    values = parse_qs(urlparse(url).query).get("offset", ["0"])
    try:
        return int(values[0])
    except (ValueError, IndexError):
        return 0


def _is_sendgrid_url(url: Any) -> bool:
    # Only follow URLs that stay on the canonical SendGrid host, so a tampered or compromised API
    # response (or Redis resume state) can't point our authenticated request at an internal address
    # (SSRF) and leak the API key carried in the Authorization header.
    return isinstance(url, str) and url.startswith(SENDGRID_BASE_URL)


def _require_sendgrid_url(url: str) -> None:
    if not _is_sendgrid_url(url):
        raise ValueError(f"SendGrid resume state contains an unexpected URL: {url!r}")


class SendGridMetadataPaginator(JSONResponsePaginator):
    """Follow the absolute `_metadata.next` URL SendGrid returns, dropping any off-host next link
    (stop cleanly) rather than following it — the SSRF guard for marketing/asm metadata endpoints."""

    def __init__(self) -> None:
        super().__init__(next_url_path="_metadata.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._next_url is not None and not _is_sendgrid_url(self._next_url):
            self._next_url = None
            self._has_next_page = False


def _build_paginator(config: SendGridEndpointConfig) -> BasePaginator:
    if config.pagination == "offset":
        # No top-level `total`; termination is a short/empty page (OffsetPaginator default).
        return OffsetPaginator(limit=config.page_size, total_path=None)
    if config.pagination == "metadata":
        return SendGridMetadataPaginator()
    return SinglePagePaginator()


def _build_params(
    config: SendGridEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)

    # Metadata endpoints carry the page size as a query param; offset endpoints get limit/offset
    # from the paginator, single endpoints take no pagination params.
    if config.pagination == "metadata":
        params["page_size"] = config.page_size

    if (
        should_use_incremental_field
        and config.incremental_param
        and incremental_field
        and db_incremental_field_last_value is not None
    ):
        # start_time is inclusive (created >= start_time); the boundary row re-appears but merge
        # dedupes it on the primary key.
        params[config.incremental_param] = _to_epoch_seconds(db_incremental_field_last_value)

    return params


def _initial_paginator_state(
    config: SendGridEndpointConfig,
    resumable_source_manager: ResumableSourceManager[SendGridResumeConfig],
) -> Optional[dict[str, Any]]:
    if not resumable_source_manager.can_resume():
        return None
    resume = resumable_source_manager.load_state()
    if resume is None:
        return None

    if config.pagination == "offset":
        if resume.offset is not None:
            return {"offset": resume.offset}
        if resume.next_url is not None:
            # Pre-migration state stored the offset inside a URL; re-check the host before trusting it.
            _require_sendgrid_url(resume.next_url)
            return {"offset": _offset_from_url(resume.next_url)}
        return None

    if config.pagination == "metadata" and resume.next_url is not None:
        _require_sendgrid_url(resume.next_url)
        return {"next_url": resume.next_url}

    return None


def sendgrid_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SendGridResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = SENDGRID_ENDPOINTS[endpoint]

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SENDGRID_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from logs
            # and raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": _build_paginator(config),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # data_key wraps the array for metadata endpoints ("result"); None means the body
                    # is the array itself (suppression/asm). Fail loud on a shape change instead of
                    # silently syncing 0 rows.
                    "data_selector": config.data_key,
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state = _initial_paginator_state(config, resumable_source_manager)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if not state:
            return
        if state.get("offset") is not None:
            resumable_source_manager.save_state(SendGridResumeConfig(offset=int(state["offset"])))
        elif state.get("next_url"):
            resumable_source_manager.save_state(SendGridResumeConfig(next_url=state["next_url"]))

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def get_status_code(api_key: str, path: str) -> Optional[int]:
    """Probe an endpoint to classify the credentials. Returns the HTTP status, or None on a
    transport error."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SENDGRID_BASE_URL}{path}?limit=1",
        headers=_get_headers(api_key),
    )
    return status
