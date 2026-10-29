from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.settings import (
    PAGE_SIZE,
    SCHEMATIC_BASE_URL,
    SCHEMATIC_ENDPOINTS,
    SchematicEndpointConfig,
)

API_KEY_HEADER = "X-Schematic-Api-Key"


@dataclass(frozen=True)
class SchematicResumeConfig:
    offset: int
    # Which `is_active` pass the offset belongs to, for endpoints read in an active and an inactive pass.
    is_active: bool | None = None


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SCHEMATIC_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": API_KEY_HEADER, "location": "header"},
        # `requests` keeps a custom header on a cross-origin redirect, so a redirect would replay the key.
        "allow_redirects": False,
        "allowed_hosts": [],
    }


def _resource(
    api_key: str,
    config: SchematicEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
    is_active: bool | None,
    initial_offset: int | None,
) -> Resource:
    params: dict[str, Any] = dict(config.extra_params)
    if is_active is not None:
        params["is_active"] = "true" if is_active else "false"
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "table_name": config.name,
                "write_disposition": "replace",
                "table_format": "delta",
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # The response carries no total, so the walk ends on the first short page.
                    "data_selector": "data",
                    "data_selector_required": True,
                    "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": None},
                },
            }
        ],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(SchematicResumeConfig(offset=int(state["offset"]), is_active=is_active))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=None if initial_offset is None else {"offset": initial_offset},
    )


def _active_then_inactive(
    build: Callable[[bool, int | None], Resource],
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
    resume: SchematicResumeConfig | None,
) -> Iterator[Any]:
    if resume is None or resume.is_active is not False:
        yield from build(True, resume.offset if resume is not None else None)
        # Every active row is handed on, so a resume from here starts the inactive pass.
        resumable_source_manager.save_state(SchematicResumeConfig(offset=0, is_active=False))
        yield from build(False, None)
    else:
        yield from build(False, resume.offset)


def schematic_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
) -> SourceResponse:
    config = SCHEMATIC_ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.include_inactive:
        build = partial(_resource, api_key, config, team_id, job_id, resumable_source_manager)
        first = build(True, None)
        # The chain hands each page on unchanged and holds no rows, so as a `Resource` it keeps the
        # framework's checkpoints.
        resource = Resource(
            partial(_active_then_inactive, build, resumable_source_manager, resume),
            name=endpoint,
            hints=first._hints,
        )
    else:
        resource = _resource(
            api_key,
            config,
            team_id,
            job_id,
            resumable_source_manager,
            None,
            resume.offset if resume is not None else None,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SCHEMATIC_BASE_URL}/companies?limit=1",
        headers={API_KEY_HEADER: api_key, "Accept": "application/json"},
        timeout=15,
        allow_redirects=False,
    )
