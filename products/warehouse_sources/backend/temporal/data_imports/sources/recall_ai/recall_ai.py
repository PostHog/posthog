from datetime import UTC, date, datetime
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.settings import RECALL_AI_ENDPOINTS

# API keys are region-scoped and each region is its own host. The allowlist pins outbound
# traffic to *.recall.ai even if a stored config carries an unexpected region value.
REGIONS = ("us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1")


@frozen
class RecallAIResumeConfig:
    next_url: str


def base_url_for_region(region: str) -> str:
    if region not in REGIONS:
        raise ValueError(f"Unknown Recall.ai region: {region}")
    return f"https://{region}.recall.ai"


def _to_iso8601(value: Any) -> Optional[str]:
    """Format the incremental watermark for Recall.ai's ISO 8601 datetime filters.
    Truncating to whole seconds only widens the window, so a boundary row is re-fetched
    and deduped on merge rather than skipped."""
    if value is None:
        return None
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _scrub_fields(fields: tuple[str, ...]):
    def scrub(item: dict[str, Any]) -> dict[str, Any]:
        for field in fields:
            item.pop(field, None)
        return item

    return scrub


def get_resource(
    endpoint: str, should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any]
) -> EndpointResource:
    config = RECALL_AI_ENDPOINTS[endpoint]

    params: dict[str, Any] = dict(config.extra_params)
    # Only send the lower-bound filter once a real watermark exists; the first incremental
    # sync goes out unfiltered and still advances the watermark from the synced rows.
    if should_use_incremental_field and db_incremental_field_last_value is not None and config.incremental_param:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": config.incremental_field,
            "initial_value": None,
            "convert": _to_iso8601,
        }

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": "results",
            "path": config.path,
            "params": params,
            # Every list response carries an absolute next-page URL in its body, which also
            # keeps any filter params on later pages.
            "paginator": JSONResponsePaginator(next_url_path="next"),
        },
        "table_format": "delta",
    }


def recall_ai_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RecallAIResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    endpoint_config = RECALL_AI_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url_for_region(region),
            # Recall.ai requires the literal "Token " prefix, not "Bearer ".
            "auth": {
                "type": "api_key",
                "api_key": f"Token {api_key}",
                "name": "Authorization",
                "location": "header",
            },
            "headers": {"Accept": "application/json"},
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, db_incremental_field_last_value)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"next_url": resume_config.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("next_url"):
            resumable_source_manager.save_state(RecallAIResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    if endpoint_config.scrub_fields:
        resource = resource.add_map(_scrub_fields(endpoint_config.scrub_fields))

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
        # The API documents no ordering and its cursor pagination accepts no sort param, so
        # assume nothing: "desc" commits the incremental watermark only when the sync
        # completes, which is correct whatever order rows actually arrive in.
        sort_mode="desc",
    )


def validate_credentials(api_key: str, region: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url_for_region(region)}/api/v1/bot/",
        headers={"Authorization": f"Token {api_key}"},
    )
