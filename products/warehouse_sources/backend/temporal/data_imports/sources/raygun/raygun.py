import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.settings import (
    PAGE_SIZE,
    RAYGUN_BASE_URL,
    RAYGUN_ENDPOINTS,
)

# The `applications` response carries `apiKey` — the ingestion key for that application — which
# anyone with warehouse viewer access could otherwise read and use to submit forged crash/APM/RUM
# data. It is never needed downstream, so strip it at the source.
_APPLICATIONS_SENSITIVE_FIELDS = frozenset({"apiKey"})


@dataclasses.dataclass
class RaygunResumeConfig:
    # Offset (rows to skip) for the next page of a top-level list endpoint.
    offset: int = 0
    # Retained so resume state saved before the rest_source migration still parses; the fan-out
    # bookmark now lives in `fanout_state`. Never written by the current code.
    application_identifier: str | None = None
    # Framework dependent-resource resume state for fan-out endpoints, of the shape
    # ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``.
    fanout_state: dict[str, Any] | None = None


def _strip_application_api_key(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in _APPLICATIONS_SENSITIVE_FIELDS}


def _make_session(personal_access_token: str) -> Any:
    # `capture=False`: customer and session rows carry end-user PII (externalIdentifier, names,
    # IP addresses) and application rows carry ingestion API keys — fields the name-based sample
    # scrubbers can't recognise, so keep response bodies out of HTTP sample storage entirely.
    # Requests are still metered and logged (status + url). `redact_values` masks the token as
    # defense in depth (the framework auth also scrubs it from raised errors).
    return make_tracked_session(redact_values=(personal_access_token,), capture=False)


def _client_config(personal_access_token: str) -> dict[str, Any]:
    return {
        "base_url": RAYGUN_BASE_URL,
        # Auth (Bearer) goes through the framework auth config so its value is redacted from raised
        # errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": personal_access_token},
        "session": _make_session(personal_access_token),
        # Raygun list endpoints return a bare JSON array with no `total`; termination is the
        # short/empty page (OffsetPaginator default). `count` is Raygun's page-size param.
        "paginator": OffsetPaginator(limit=PAGE_SIZE, limit_param="count", total_path=None),
    }


def validate_token(personal_access_token: str) -> tuple[bool, int | None]:
    """Probe the token against the cheapest scoped endpoint. Returns (is_valid, status_code).

    A 200 confirms the token is genuine and carries `applications:read`. The status code lets the
    caller distinguish a bad token (401) from a valid token missing a scope (403)."""
    return validate_via_probe(
        lambda: _make_session(personal_access_token),
        f"{RAYGUN_BASE_URL}/applications?count=1",
        headers={"Authorization": f"Bearer {personal_access_token}", "Accept": "application/json"},
    )


def _top_level_source(
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
    db_incremental_field_last_value: Optional[Any],
):
    config = RAYGUN_ENDPOINTS[endpoint]

    resource_config: dict[str, Any] = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": {"orderby": config.orderby},
        },
    }
    if endpoint == "applications":
        resource_config["data_map"] = _strip_application_api_key

    rest_config: RESTAPIConfig = {
        "client": _client_config(personal_access_token),
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only seed from a top-level (offset) checkpoint; a fan-out checkpoint has no meaning here.
        if resume is not None and resume.fanout_state is None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(RaygunResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_source(
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
    db_incremental_field_last_value: Optional[Any],
):
    config = RAYGUN_ENDPOINTS[endpoint]
    parent_config = RAYGUN_ENDPOINTS["applications"]

    rest_config: RESTAPIConfig = {
        "client": _client_config(personal_access_token),
        "resources": [
            {
                "name": "applications",
                "endpoint": {
                    "path": parent_config.path,
                    "params": {"orderby": parent_config.orderby},
                },
            },
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {
                        # Resolve the per-application child path from each application's identifier.
                        "application_identifier": {
                            "type": "resolve",
                            "resource": "applications",
                            "field": "identifier",
                        },
                        "orderby": config.orderby,
                    },
                },
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only seed from a fan-out checkpoint. State saved before the migration (old-shape offset/
        # application_identifier, no fanout_state) can't drive the framework's per-parent resume, so
        # that part starts fresh — the parent list is re-enumerated and merge dedupes re-pulled rows.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(RaygunResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if resource.name == endpoint)


def raygun_source(
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RAYGUN_ENDPOINTS[endpoint]

    if config.fan_out_over_applications:
        resource = _fan_out_source(
            personal_access_token,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            db_incremental_field_last_value,
        )
    else:
        resource = _top_level_source(
            personal_access_token,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
