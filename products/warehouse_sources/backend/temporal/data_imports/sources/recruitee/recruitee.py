import re
import dataclasses
from typing import Any, Optional

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
    OffsetPaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.settings import (
    PAGE_SIZE,
    RECRUITEE_ENDPOINTS,
    RecruiteeEndpointConfig,
)

RECRUITEE_HOST = "https://api.recruitee.com"
# Cheap probe used to confirm credentials. Departments is the smallest company-level list, and the
# token is company-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/departments"
# The company_id is interpolated into the request path, so restrict it to path-safe characters to
# keep the request pinned to api.recruitee.com/c/<company_id>.
COMPANY_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclasses.dataclass(frozen=True)
class RecruiteeResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0
    # Next page number, for the endpoints that paginate by `page` instead of `offset`.
    page: Optional[int] = None


def base_url(company_id: str) -> str:
    if not COMPANY_ID_REGEX.match(company_id):
        raise ValueError("Recruitee company ID contains invalid characters")
    return f"{RECRUITEE_HOST}/c/{company_id}"


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so the token is redacted from logs and
    # errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _client_config(company_id: str, api_token: str) -> ClientConfig:
    return {
        "base_url": base_url(company_id),
        "headers": _headers(),
        "auth": {"type": "bearer", "token": api_token},
        # The token rides only to api.recruitee.com/c/<company_id>; pin every request (including
        # paginator follow-ups) to that host so a redirect or crafted next-page can't exfiltrate it.
        "allowed_hosts": [],
        # No top-level `total`; termination is a short/empty page (OffsetPaginator default).
        "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
    }


def _paginator(config: RecruiteeEndpointConfig) -> BasePaginator:
    if config.pagination == "page":
        # `meta.total_count` counts records, not pages, so the paginator stops on an empty page.
        return PageNumberPaginator(base_page=1)
    return OffsetPaginator(limit=PAGE_SIZE, total_path=None)


def _candidate_notes_source(
    company_id: str,
    api_token: str,
    config: RecruiteeEndpointConfig,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    assert config.fanout is not None
    resource = build_dependent_resource(
        endpoint_configs=RECRUITEE_ENDPOINTS,
        child_endpoint=config.name,
        fanout=config.fanout,
        client_config=_client_config(company_id, api_token),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        parent_endpoint_extra={
            "data_selector": RECRUITEE_ENDPOINTS[config.fanout.parent_name].data_key,
            "data_selector_malformed_retryable": True,
        },
        child_endpoint_extra={
            # The notes of one candidate come back in a single unpaginated response.
            "paginator": "single_page",
            "data_selector": config.data_key,
            "data_selector_malformed_retryable": True,
        },
        # The client paginator sends `limit` on the candidates listing; the notes call takes none.
        page_size_param=None,
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        # No checkpoints are saved, so a shutdown handoff would repeat every candidate's notes call.
        supports_resume=False,
    )


def recruitee_source(
    company_id: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RecruiteeResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RECRUITEE_ENDPOINTS[endpoint]

    if config.fanout is not None:
        # The fan-out re-lists the candidates each run, so it keeps no resume state.
        return _candidate_notes_source(company_id, api_token, config, team_id, job_id)

    rest_config: RESTAPIConfig = {
        "client": _client_config(company_id, api_token),
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE, **config.params},
                    "paginator": _paginator(config),
                    # Recruitee wraps records under a key named after the resource, e.g.
                    # {"candidates": [...]}. A 200 whose body isn't that list shape is treated as a
                    # transient blip and retried, matching the old defensive retryable classification.
                    "data_selector": config.data_key,
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            # Each paginator reads only its own key, so both are passed.
            initial_paginator_state = {"offset": resume.offset}
            if resume.page is not None:
                initial_paginator_state["page"] = resume.page

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if not state:
            return
        if state.get("page") is not None:
            resumable_source_manager.save_state(RecruiteeResumeConfig(page=int(state["page"])))
        elif state.get("offset") is not None:
            resumable_source_manager.save_state(RecruiteeResumeConfig(offset=int(state["offset"])))

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
        column_hints=resource.column_hints,
    )


def validate_credentials(company_id: str, api_token: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the credentials.

    The token is company-wide, so one probe validates access to every list endpoint. Maps the probe
    result to ``(is_valid, message)``: 401/403 is a bad token, any other non-200 reports the status,
    and an unreachable probe is "not validated".
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{base_url(company_id)}{DEFAULT_PROBE_PATH}?limit=1&offset=0",
        headers={"Authorization": f"Bearer {api_token}", **_headers()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Recruitee company ID or API token"
    if status is not None:
        return False, f"Recruitee returned HTTP {status}"
    return False, "Could not validate Recruitee credentials"
