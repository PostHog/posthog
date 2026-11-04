import dataclasses
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    DependentEndpointConfig,
    Endpoint,
    EndpointResource,
    JSONResponsePaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.secoda.settings import SECODA_ENDPOINTS, SecodaEndpointConfig

# US cloud host. EU (eapi.secoda.co), APAC (aapi.secoda.co) and self-hosted domains are not yet
# selectable — see the region caveat in the source docs.
SECODA_BASE_URL = "https://api.secoda.co"
# Cheap list endpoint used to confirm an API key is genuine. The key inherits its creator's
# workspace permissions, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/api/v1/user"

# Secoda uses DRF-style cursor pagination: the follow link is a full URL nested under ``links.next``,
# though a couple of endpoints expose it top-level under ``next``. Accept either; ``links.next`` wins.
NEXT_URL_PATH = "(links.next) | next"

# A 200 whose body isn't the expected ``{"results": [...]}`` shape (bare list, dict without
# ``results``, or ``results`` not a list) is treated as transient and reissued.
LIST_ENDPOINT_SELECTOR: Endpoint = {"data_selector": "results", "data_selector_malformed_retryable": True}


@dataclasses.dataclass(frozen=False)
class SecodaResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the API's ``links.next``. Secoda uses
    # DRF-style cursor pagination, so a crashed full-refresh sync resumes from the page after the
    # last one yielded; merge dedupes the re-pulled page on ``id``.
    next_url: str | None = None


def _drop_fields(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in fields}


def secoda_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SecodaResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SECODA_ENDPOINTS[endpoint]
    client_config = _client_config(api_key)

    if config.fanout is not None:
        return _fanout_source(config, config.fanout, client_config, team_id, job_id)

    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": {"path": config.path, **LIST_ENDPOINT_SELECTOR},
    }
    if config.drop_fields:
        resource_config["data_map"] = lambda row: _drop_fields(row, config.drop_fields)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next cursor remains; save AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes on ``id``) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(SecodaResumeConfig(next_url=state["next_url"]))

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
    )


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SECODA_BASE_URL,
        # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
        # logs and raised errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        # The bearer key must not follow a server-supplied `links.next` (or persisted resume
        # URL) or a 3xx to another host. `allowed_hosts=[]` pins requests to SECODA_BASE_URL's host.
        "allowed_hosts": [],
        "allow_redirects": False,
        "paginator": JSONResponsePaginator(next_url_path=NEXT_URL_PATH),
    }


def _fanout_source(
    config: SecodaEndpointConfig,
    fanout: DependentEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    # Not resumable: the dependent-resource resume state lists every completed parent, which would
    # grow with the monitor count and be rewritten after each monitor.
    resource = build_dependent_resource(
        endpoint_configs=SECODA_ENDPOINTS,
        child_endpoint=config.name,
        fanout=fanout,
        client_config=client_config,
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        page_size_param=None,
        parent_endpoint_extra=LIST_ENDPOINT_SELECTOR,
        # The framework reads a path that ends in a placeholder as a single-entity endpoint and
        # defaults it to one page, so the child names its paginator explicitly.
        child_endpoint_extra={
            **LIST_ENDPOINT_SELECTOR,
            "paginator": JSONResponsePaginator(next_url_path=NEXT_URL_PATH),
        },
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        supports_resume=False,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a single list endpoint to validate the workspace API key.

    The key inherits its creator's workspace permissions, so one probe validates access to every
    list endpoint. Returns ``(is_valid, message)`` with a distinct message for an auth failure.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SECODA_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Secoda API key"
    if status is not None:
        return False, f"Secoda returned HTTP {status}"
    return False, "Could not validate Secoda API key"
