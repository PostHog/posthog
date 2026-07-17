import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.settings import (
    PAPERFORM_ENDPOINTS,
    PaperformEndpointConfig,
)

PAPERFORM_BASE_URL = "https://api.paperform.co/v1"
# Paginated list endpoints cap `limit` at 100 (default 20); the largest page minimises round trips
# against the 60 req/min rate limit.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates the credential for every Standard API endpoint.
DEFAULT_PROBE_PATH = "/forms"
# The account-level list that every form-scoped endpoint fans out over.
FORMS_ENDPOINT = "forms"

# The Bearer token rides in the Authorization header via the framework auth config, so the client
# redacts it from every raised error message; only these non-secret headers go through client config.
NON_SECRET_HEADERS = {"Accept": "application/json"}


@dataclasses.dataclass
class PaperformResumeConfig:
    # `after_id` cursor for the next page of a top-level list (forms, spaces). None starts at page one.
    cursor: str | None = None
    # Retained for backward compatibility with resume state written before the rest_source migration
    # (which bookmarked a form id). New writes leave it None; the fan-out checkpoint lives in
    # `fanout_state` instead.
    form_id: str | None = None
    # Framework fan-out checkpoint for form-scoped endpoints:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    # None (e.g. an old-shape checkpoint) means start the fan-out fresh — the merge dedupes re-pulls.
    fanout_state: dict[str, Any] | None = None


def _format_after_date(value: Any) -> str:
    """Format the incremental watermark for Paperform's `after_date` filter (UTC ISO 8601).

    Truncates to whole seconds, which rounds the lower bound *down* — so a sync re-fetches at most
    a few boundary rows (the merge dedupes them on the primary key) rather than skipping any.
    """
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%dT%H:%M:%SZ")


class PaperformCursorPaginator(BasePaginator):
    """`after_id` cursor pagination: the next page's cursor is the last row's ``id``.

    Termination is driven by the response's ``has_more`` flag (or an empty page), not by cursor
    absence — the last page still carries rows with ids, so a plain cursor paginator would loop.
    Once the cursor is active it also drops the incremental ``after_date`` param, which Paperform
    ignores in the presence of ``after_id``; this mirrors the hand-rolled transport that only sent
    the watermark on each form's first page.
    """

    def __init__(self, cursor_param: str = "after_id", date_param: str = "after_date") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self.date_param = date_param
        self._cursor: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.cursor_param] = self._cursor
        # after_id supersedes after_date on the server; drop it so later pages advance purely on
        # the id cursor (and so the request shape matches the pre-migration transport).
        request.params.pop(self.date_param, None)

    def init_request(self, request: Request) -> None:
        # Only fires with a seeded resume cursor; the first fresh page keeps after_date untouched.
        if self._cursor is not None:
            self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        has_more = False
        try:
            body = response.json()
            has_more = bool(body.get("has_more")) if isinstance(body, dict) else False
        except Exception:
            has_more = False

        if not has_more or not data:
            self._has_next_page = False
            return

        self._cursor = str(data[-1]["id"])
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._cursor is not None:
            self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"PaperformCursorPaginator(cursor={self._cursor})"


def _data_selector(config: PaperformEndpointConfig) -> str:
    # Quote the key so hyphenated results keys (e.g. `partial-submissions`) aren't parsed as a
    # jsonpath subtraction.
    return f"results.'{config.results_key}'"


def _client_config(api_key: str) -> dict[str, Any]:
    return {
        "base_url": PAPERFORM_BASE_URL,
        "headers": NON_SECRET_HEADERS,
        "auth": {"type": "bearer", "token": api_key},
    }


def _rename_form_id(row: dict[str, Any]) -> dict[str, Any]:
    # `include_from_parent=["id"]` injects the parent form id under `_forms_id`; surface it as
    # `form_id` so the composite ["form_id", ...] key is unique across the whole table. A submission
    # already carries its own form_id (the same value), so overwriting it is a no-op in practice.
    if "_forms_id" in row:
        row["form_id"] = row.pop("_forms_id")
    return row


def _top_level_source(
    api_key: str,
    config: PaperformEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PaperformResumeConfig],
):
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(PaperformResumeConfig(cursor=str(state["cursor"])))

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE, "sort": "ASC"},
                    "data_selector": _data_selector(config),
                    # A 200 body without the expected results key means the response shape changed —
                    # fail loud instead of silently syncing 0 rows.
                    "data_selector_required": True,
                    "paginator": PaperformCursorPaginator(),
                },
            }
        ],
    }

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _form_scoped_source(
    api_key: str,
    config: PaperformEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PaperformResumeConfig],
    db_incremental_field_last_value: Optional[Any],
):
    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The dependent-resource hook always hands back a dict snapshotting fan-out progress
        # (completed parents + the in-flight parent's child cursor); persist each advance.
        resumable_source_manager.save_state(PaperformResumeConfig(fanout_state=state))

    forms_config = PAPERFORM_ENDPOINTS[FORMS_ENDPOINT]
    parent_resource: EndpointResource = {
        "name": FORMS_ENDPOINT,
        "endpoint": {
            "path": forms_config.path,
            "params": {"limit": PAGE_SIZE, "sort": "ASC"},
            "data_selector": _data_selector(forms_config),
            "data_selector_required": True,
            "paginator": PaperformCursorPaginator(),
        },
    }

    child_params: dict[str, Any] = {
        "form_id": {"type": "resolve", "resource": FORMS_ENDPOINT, "field": "id"},
    }
    child_endpoint: Endpoint = {
        "path": config.path,
        "data_selector": _data_selector(config),
        "data_selector_required": True,
    }
    if config.paginated:
        child_params["limit"] = PAGE_SIZE
        child_params["sort"] = "ASC"
        child_endpoint["paginator"] = PaperformCursorPaginator()
    else:
        # Fields, products, and coupons return the whole collection in one response.
        child_endpoint["paginator"] = SinglePagePaginator()

    if config.incremental_fields and db_incremental_field_last_value is not None:
        child_endpoint["incremental"] = {
            "start_param": "after_date",
            "cursor_path": config.incremental_fields[0]["field"],
            "convert": _format_after_date,
        }

    child_endpoint["params"] = child_params
    child_resource: EndpointResource = {
        "name": config.name,
        "include_from_parent": ["id"],
        "data_map": _rename_form_id,
        "endpoint": child_endpoint,
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [parent_resource, child_resource],
    }

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return next(resource for resource in resources if resource.name == config.name)


def paperform_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PaperformResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PAPERFORM_ENDPOINTS[endpoint]

    if config.form_scoped:
        resource = _form_scoped_source(
            api_key, config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
        )
    else:
        resource = _top_level_source(api_key, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # We request `sort=ASC` (creation order) on every paginated endpoint, so rows arrive
        # oldest-first within each form and the ascending watermark bookkeeping is correct.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the account-wide API key.

    Preserves the per-status messaging: 401 means a bad key, 403 means a valid key on a plan that
    gates API access, anything else surfaces the status (or a connection failure).
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{PAPERFORM_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        headers={"Authorization": f"Bearer {api_key}", **NON_SECRET_HEADERS},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Paperform API key"
    if status == 403:
        # The key authenticated but the account can't use the API — Paperform gates API access
        # behind its paid plans.
        return (
            False,
            "Your Paperform plan does not include API access. API access requires a Pro, Business, or Agency plan.",
        )
    if status is None:
        return False, "Could not connect to Paperform to validate the API key"
    return False, f"Paperform returned HTTP {status}"
