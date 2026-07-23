import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from jsonpath_ng import DatumInContext, JSONPath

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.settings import BLAND_AI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BASE_URL = "https://api.bland.ai"

# GET /v1/calls default (and documented maximum) page size.
PAGE_SIZE = 1000


@dataclasses.dataclass
class BlandAIResumeConfig:
    # Index offset into the call list (`from` query param) of the next unfetched page.
    offset: int = 0
    # The exact `start_date` filter the interrupted run used. The pipeline checkpoints the
    # incremental watermark per batch, so on resume `db_incremental_field_last_value` may already
    # have advanced past the value we filtered by — reusing the original filter keeps the saved
    # cursor pointing into the same result set.
    start_date: str | None = None
    # Framework fan-out checkpoint for call_transcripts (completed/current child paths plus the
    # in-progress child paginator state). Optional so state saved before this field existed
    # (offset-only) still parses; such state restarts the fan-out fresh under the saved filter.
    fanout_state: dict[str, Any] | None = None


def validate_credentials(api_key: str) -> bool:
    # Cheapest probe that exercises the token: list a single call. A bad key returns
    # 401 {"errors": [{"error": "AUTH_FAILURE", ...}]}.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BASE_URL}/v1/calls?limit=1",
        # Bland expects the raw key in the authorization header (no "Bearer" prefix).
        headers={"authorization": api_key, "Accept": "application/json"},
    )
    return ok


def _format_start_date(value: Any) -> str | None:
    """Format the incremental watermark as the ISO 8601 value `start_date` accepts.

    A naive datetime is stamped UTC — Bland interprets offset-less values as UTC anyway, and an
    explicit offset guards against that default changing.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


class _PathwaysBodySelector(JSONPath):
    """Data selector normalizing GET /v1/pathway's response body.

    The docs' response example shows a single pathway object without an explicit list wrapper,
    and we couldn't verify the live shape without account credentials — accept a bare list,
    common list wrappers, or a single object.
    """

    def find(self, data: Any) -> list[DatumInContext]:
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            wrapped = next((data[key] for key in ("pathways", "data") if isinstance(data.get(key), list)), None)
            rows = wrapped if wrapped is not None else [data]
        else:
            rows = []
        return [DatumInContext(rows)]


def _adopt_parent_call_fields(row: dict[str, Any]) -> dict[str, Any]:
    # Rename the injected parent fields onto the utterance row: `call_id` (part of the composite
    # primary key) and `call_created_at`, the parent call's creation time. Utterance `created_at`s
    # aren't monotonic across calls (a long call's utterances postdate the next call's creation),
    # so `call_created_at` is the field the incremental cursor and partitioning key off.
    # `pop` without a default on purpose: a silent None here would corrupt partitions and stall
    # the incremental watermark.
    row["call_id"] = row.pop("_calls_call_id")
    row["call_created_at"] = row.pop("_calls_created_at")
    return row


def _calls_list_resource(params: dict[str, Any]) -> EndpointResource:
    return {
        "name": "calls",
        "endpoint": {
            "path": "v1/calls",
            "params": params,
            "data_selector": "calls",
            # Index-offset pagination (`from` + `limit`) with `total_count` in the response body.
            "paginator": OffsetPaginator(
                limit=PAGE_SIZE,
                offset_param="from",
                limit_param="limit",
                total_path="total_count",
            ),
        },
    }


def bland_ai_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BlandAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = BLAND_AI_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            # Auth is supplied via the framework auth config so its value is redacted from logs;
            # Bland expects the raw API key (no "Bearer" prefix) in the authorization header.
            "auth": {"type": "api_key", "api_key": api_key, "name": "authorization", "location": "header"},
            "headers": {"Accept": "application/json"},
        },
        "resources": [],
    }

    resource: Resource
    if endpoint == "pathways":
        # Small (name/description/nodes/edges per pathway), no timestamp filters — a single
        # unordered page on a full-refresh-only endpoint.
        rest_config["resources"] = [
            {
                "name": "pathways",
                "endpoint": {
                    "path": "v1/pathway",
                    "data_selector": _PathwaysBodySelector(),
                    "paginator": SinglePagePaginator(),
                },
            }
        ]
        resource = rest_api_resource(rest_config, team_id, job_id, None)
    else:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        if resume is not None:
            start_date = resume.start_date
        else:
            start_date = _format_start_date(db_incremental_field_last_value) if should_use_incremental_field else None

        list_params: dict[str, Any] = {
            # Ascending creation order so the pipeline's incremental watermark can checkpoint
            # after every batch, and so index offsets stay stable while new calls append.
            "ascending": "true",
            "sort_by": "created_at",
        }
        if start_date:
            # `start_date` is inclusive; the boundary row is re-fetched and deduped by merge.
            list_params["start_date"] = start_date

        if endpoint == "calls":
            initial_paginator_state = {"offset": resume.offset} if resume is not None else None

            def save_calls_checkpoint(state: Optional[dict[str, Any]]) -> None:
                # Persist only when a next page remains; the hook fires AFTER a page is yielded so
                # a crash re-yields the last page (merge dedupes) rather than skipping it. The
                # exact filter is saved alongside so a resume continues the same result set.
                if state and state.get("offset") is not None:
                    resumable_source_manager.save_state(
                        BlandAIResumeConfig(offset=int(state["offset"]), start_date=start_date)
                    )

            rest_config["resources"] = [_calls_list_resource(list_params)]
            resource = rest_api_resource(
                rest_config,
                team_id,
                job_id,
                None,
                resume_hook=save_calls_checkpoint,
                initial_paginator_state=initial_paginator_state,
            )
        else:  # call_transcripts
            # Transcripts are excluded from the list endpoint for size reasons, so this endpoint
            # lists calls (same pagination/filtering as `calls`) and hydrates each via
            # GET /v1/calls/{call_id}, emitting one row per transcript utterance.
            def save_transcripts_checkpoint(state: Optional[dict[str, Any]]) -> None:
                if state is not None:
                    resumable_source_manager.save_state(BlandAIResumeConfig(start_date=start_date, fanout_state=state))

            rest_config["resources"] = [
                _calls_list_resource(list_params),
                {
                    "name": "call_transcripts",
                    "include_from_parent": ["call_id", "created_at"],
                    "data_map": _adopt_parent_call_fields,
                    "endpoint": {
                        "path": "v1/calls/{call_id}",
                        "params": {"call_id": {"type": "resolve", "resource": "calls", "field": "call_id"}},
                        # A call with no transcripts (e.g. unanswered) is a legit zero-row detail.
                        "data_selector": "transcripts",
                        "paginator": SinglePagePaginator(),
                    },
                },
            ]
            resources = rest_api_resources(
                rest_config,
                team_id,
                job_id,
                None,
                resume_hook=save_transcripts_checkpoint,
                initial_paginator_state=resume.fanout_state if resume is not None else None,
            )
            resource = next(r for r in resources if r.name == "call_transcripts")

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # Call endpoints request `ascending=true&sort_by=created_at`; pathways is a single
        # unordered page on a full-refresh-only endpoint, so the value never drives a watermark.
        sort_mode="asc",
    )
