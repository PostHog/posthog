import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.settings import (
    CRUNCHBASE_ENDPOINTS,
    CrunchbaseEndpointConfig,
)

CRUNCHBASE_BASE_URL = "https://api.crunchbase.com/v4/data"
# Search pages cap at 1000 entities.
PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 120


@dataclasses.dataclass
class CrunchbaseResumeConfig:
    # Keyset pagination: `after_id` is the uuid of the last entity of the
    # previous page; static body parts are rebuilt from job inputs on resume.
    after_id: str


def _format_updated_at(value: Any) -> str:
    """Format an incremental cursor for an updated_at gte predicate (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _build_body(
    config: CrunchbaseEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Base search body sent on every page. The keyset `after_id` cursor is
    injected by the paginator, not baked in here."""
    body: dict[str, Any] = {
        "field_ids": config.field_ids,
        "limit": PAGE_SIZE,
        # Ascending updated_at order keeps the incremental watermark monotonic
        # and gives stable pages on full scans too.
        "order": [{"field_id": "updated_at", "sort": "asc"}],
    }

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        body["query"] = [
            {
                "type": "predicate",
                "field_id": "updated_at",
                "operator_id": "gte",
                "values": [_format_updated_at(db_incremental_field_last_value)],
            }
        ]

    return body


def _flatten_entity(entity: dict[str, Any]) -> dict[str, Any]:
    # Search hits nest the requested fields under `properties`; hoist them so
    # the table gets real columns and the uuid is available as the primary key.
    properties = entity.get("properties") or {}
    return {**properties, "uuid": entity["uuid"]}


class CrunchbaseKeysetPaginator(BasePaginator):
    """Keyset pagination over the Search API: each page's next cursor is the
    uuid of its last entity, injected into the POST body as `after_id`. A page
    shorter than the requested limit is the last page (matches the API's own
    end-of-results signal), so we stop without paying an extra empty request."""

    def __init__(self) -> None:
        super().__init__()
        self._after_id: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._after_id is not None:
            self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) < PAGE_SIZE:
            self._has_next_page = False
            return
        # A full page: the last entity's uuid is a safe keyset cursor.
        # `_flatten_entity` asserts uuid presence downstream; read it directly
        # so a missing uuid fails loud here too rather than paginating past it.
        self._after_id = data[-1]["uuid"]
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def _inject(self, request: Request) -> None:
        if self._after_id is None:
            return
        if request.json is None:
            request.json = {}
        request.json["after_id"] = self._after_id

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._after_id is not None:
            return {"after_id": self._after_id}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after_id = state.get("after_id")
        if after_id is not None:
            self._after_id = str(after_id)
            self._has_next_page = True


def crunchbase_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CrunchbaseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CRUNCHBASE_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CRUNCHBASE_BASE_URL,
            # The user key travels in a custom header; framework auth registers it
            # for value-based log redaction.
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-cb-user-key", "location": "header"},
            "paginator": CrunchbaseKeysetPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                # Search hits nest requested fields under `properties`; hoist them so the
                # table gets real columns and the uuid stays available as the primary key.
                "data_map": _flatten_entity,
                "endpoint": {
                    "path": f"/searches/{config.collection}",
                    "method": "post",
                    "json": _build_body(config, should_use_incremental_field, db_incremental_field_last_value),
                    # A 200 body without `entities` is treated as an empty page (matches the
                    # old `data.get("entities", [])`), so the selector is not required.
                    "data_selector": "entities",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"after_id": resume.after_id}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes on uuid) rather than skipping it.
        if state and state.get("after_id"):
            resumable_source_manager.save_state(CrunchbaseResumeConfig(after_id=str(state["after_id"])))

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
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        sort_mode="asc",
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the user key is valid AND licensed — the Search API requires a
    paid Enterprise/Applications license, so only a 200 means syncs can work.

    Uses a hand-rolled POST probe rather than the shared GET-based
    ``validate_via_probe``: the Search API is POST-only and the license check
    needs a real search body."""
    try:
        session = make_tracked_session(headers={"X-cb-user-key": api_key}, redact_values=(api_key,))
        response = session.post(
            f"{CRUNCHBASE_BASE_URL}/searches/organizations",
            json={"field_ids": ["identifier"], "limit": 1},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False
