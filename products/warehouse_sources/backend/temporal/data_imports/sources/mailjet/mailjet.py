import base64
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import (
    MAILJET_ENDPOINTS,
    MailjetEndpointConfig,
)

MAILJET_BASE_URL = "https://api.mailjet.com/v3/REST"


@dataclasses.dataclass
class MailjetResumeConfig:
    offset: int = 0
    # The schema this offset belongs to. A single job can sync multiple schemas, so we
    # guard against applying one endpoint's offset to another on resume.
    endpoint: Optional[str] = None


def _get_headers(api_key: str, secret_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{api_key}:{secret_key}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


def _to_unix_ts(value: Any) -> Optional[int]:
    """Convert an incremental field value to a Unix timestamp for Mailjet's FromTS filter."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    return None


def _build_base_params(
    config: MailjetEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Build the static query params shared across pages (Sort + optional FromTS window).

    The FromTS value is fixed for the whole sync, so it's a plain static param rather than
    the framework's per-page incremental machinery.
    """
    params: dict[str, Any] = {}
    if config.sort:
        params["Sort"] = config.sort

    if config.from_ts_field and should_use_incremental_field:
        from_ts = _to_unix_ts(db_incremental_field_last_value)
        if from_ts is not None:
            params["FromTS"] = from_ts

    return params


def validate_credentials(api_key: str, secret_key: str) -> bool:
    # /contactmetadata is a small read-only resource — 200 confirms the basic-auth
    # credentials are valid, 401 means they're not.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(secret_key,)),
        f"{MAILJET_BASE_URL}/contactmetadata?Limit=1",
        headers=_get_headers(api_key, secret_key),
    )
    return ok


def mailjet_source(
    api_key: str,
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MailjetResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MAILJET_ENDPOINTS[endpoint]
    limit = config.page_size

    params = _build_base_params(config, should_use_incremental_field, db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MAILJET_BASE_URL,
            # Auth (basic) is supplied via the framework auth config so the secret is redacted
            # from logs and errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "http_basic", "username": api_key, "password": secret_key},
            "paginator": OffsetPaginator(
                limit=limit,
                offset_param="Offset",
                limit_param="Limit",
                total_path="Total",
            ),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A 200 body without `Data` is treated as an empty page (full sync ends),
                    # matching the lenient `data.get("Data") or []` of the previous implementation.
                    "data_selector": "Data",
                },
            }
        ],
    }

    # Resume only if the saved state belongs to this endpoint.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.endpoint == endpoint and resume.offset:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(MailjetResumeConfig(offset=int(state["offset"]), endpoint=endpoint))

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
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
