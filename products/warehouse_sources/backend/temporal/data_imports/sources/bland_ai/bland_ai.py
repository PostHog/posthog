import json
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from jsonpath_ng import DatumInContext, JSONPath

from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.settings import BLAND_AI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import TJsonPath
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BASE_URL = "https://api.bland.ai"

# GET /v1/calls default (and documented maximum) page size.
PAGE_SIZE = 1000

# GET /v1/sms/conversations pages default to 25 and document no maximum. 100 keeps the request
# count down, and the paginator terminates on the response's own `totalPages`, so a server-side
# clamp to a smaller page still paginates correctly.
SMS_PAGE_SIZE = 100

# GET /v1/personas documented maximum page size (the default is 20).
PERSONAS_PAGE_SIZE = 100


@dataclasses.dataclass(frozen=True)
class BlandAIResumeConfig:
    # Index offset into the call list (`from` query param) of the next unfetched page.
    offset: int = 0
    # Page number (`page` query param) of the next unfetched page of SMS conversations.
    page: int | None = None
    # The exact creation-time filter the interrupted run used — `start_date` on the call
    # endpoints, the `created_at` `gte` filter entry on the SMS endpoints. The pipeline
    # checkpoints the incremental watermark per batch, so on resume
    # `db_incremental_field_last_value` may already have advanced past the value we filtered by —
    # reusing the original filter keeps the saved cursor pointing into the same result set.
    start_date: str | None = None
    # Framework fan-out checkpoint for call_transcripts and sms_messages (completed/current child
    # paths plus the in-progress child paginator state). Optional so state saved before this field
    # existed (offset-only) still parses; such state restarts the fan-out fresh under the saved
    # filter.
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


# Endpoints that return their whole collection in one unpaginated body, keyed to the path and the
# selector that picks the rows out of it. All three are small account-level collections with no
# timestamp filters, so they are full refresh only.
SINGLE_PAGE_ENDPOINTS: dict[str, tuple[str, TJsonPath]] = {
    "pathways": ("v1/pathway", _PathwaysBodySelector()),
    "inbound_numbers": ("v1/inbound", "inbound_numbers"),
    "voices": ("v1/voices", "voices"),
}


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


def _adopt_parent_conversation_fields(row: dict[str, Any]) -> dict[str, Any]:
    # Rename the injected parent fields onto the message row: `conversation_id` (part of the
    # composite primary key) and `conversation_created_at`, the parent conversation's creation
    # time. Message `created_at`s aren't monotonic across conversations (a long-running
    # conversation's messages postdate the next conversation's creation), so
    # `conversation_created_at` is the field the incremental cursor and partitioning key off.
    # `pop` without a default on purpose: a silent None here would corrupt partitions and stall
    # the incremental watermark.
    row["conversation_id"] = row.pop("_sms_conversations_id")
    row["conversation_created_at"] = row.pop("_sms_conversations_created_at")
    return row


def _sms_list_params(created_at_floor: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "pageSize": SMS_PAGE_SIZE,
        # The endpoint defaults to newest-first; ascending creation order lets the pipeline's
        # incremental watermark checkpoint after every batch.
        "sortBy": "created_at",
        "sortDir": "asc",
    }
    if created_at_floor:
        # `filters` is a JSON-encoded array of {field, operator, value} objects. `gte` is
        # inclusive; the boundary row is re-fetched and deduped by merge.
        params["filters"] = json.dumps([{"field": "created_at", "operator": "gte", "value": created_at_floor}])
    return params


def _sms_conversations_list_resource(params: dict[str, Any]) -> EndpointResource:
    return {
        "name": "sms_conversations",
        "endpoint": {
            "path": "v1/sms/conversations",
            "params": params,
            "data_selector": "data",
            # Page-number pagination starting at 1, with the page count in the response body.
            "paginator": PageNumberPaginator(
                base_page=1,
                page_param="page",
                total_path="extra.pagination.totalPages",
            ),
        },
    }


def _sms_resource(
    rest_config: RESTAPIConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BlandAIResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        created_at_floor = resume.start_date
    else:
        created_at_floor = _format_start_date(db_incremental_field_last_value) if should_use_incremental_field else None

    list_params = _sms_list_params(created_at_floor)

    if endpoint == "sms_conversations":
        initial_paginator_state = {"page": resume.page} if resume is not None and resume.page is not None else None

        def save_conversations_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; the hook fires AFTER a page is yielded so a
            # crash re-yields the last page (merge dedupes) rather than skipping it. The exact
            # filter is saved alongside so a resume continues the same result set.
            if state and state.get("page") is not None:
                resumable_source_manager.save_state(
                    BlandAIResumeConfig(page=int(state["page"]), start_date=created_at_floor)
                )

        rest_config["resources"] = [_sms_conversations_list_resource(list_params)]
        return rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_conversations_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    # sms_messages: the conversation list carries only a message count and the last message body,
    # so list conversations (same pagination/filtering as `sms_conversations`) and hydrate each via
    # GET /v1/sms/conversations/{id}, emitting one row per message.
    def save_messages_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(BlandAIResumeConfig(start_date=created_at_floor, fanout_state=state))

    rest_config["resources"] = [
        _sms_conversations_list_resource(list_params),
        {
            "name": "sms_messages",
            "include_from_parent": ["id", "created_at"],
            "data_map": _adopt_parent_conversation_fields,
            "endpoint": {
                "path": "v1/sms/conversations/{id}",
                "params": {"id": {"type": "resolve", "resource": "sms_conversations", "field": "id"}},
                # A conversation with no messages yet is a legit zero-row detail.
                "data_selector": "data.messages",
                "paginator": SinglePagePaginator(),
            },
        },
    ]
    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_messages_checkpoint,
        initial_paginator_state=resume.fanout_state if resume is not None else None,
    )
    return next(r for r in resources if r.name == "sms_messages")


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
    if endpoint in SINGLE_PAGE_ENDPOINTS:
        path, data_selector = SINGLE_PAGE_ENDPOINTS[endpoint]
        rest_config["resources"] = [
            {
                "name": endpoint,
                "endpoint": {
                    "path": path,
                    "data_selector": data_selector,
                    "paginator": SinglePagePaginator(),
                },
            }
        ]
        resource = rest_api_resource(rest_config, team_id, job_id, None)
    elif endpoint == "personas":
        rest_config["resources"] = [
            {
                "name": "personas",
                "endpoint": {
                    "path": "v1/personas",
                    "params": {"limit": PERSONAS_PAGE_SIZE},
                    "data_selector": "data",
                    # The body carries no page count, so pagination stops on the first empty page.
                    "paginator": PageNumberPaginator(base_page=1, page_param="page"),
                },
            }
        ]
        resource = rest_api_resource(rest_config, team_id, job_id, None)
    elif endpoint in ("sms_conversations", "sms_messages"):
        resource = _sms_resource(
            rest_config,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
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
        # Call endpoints request `ascending=true&sort_by=created_at` and the SMS endpoints
        # `sortBy=created_at&sortDir=asc`; the lookup endpoints are single unordered pages on
        # full-refresh-only tables, so the value never drives a watermark for them.
        sort_mode="asc",
    )
