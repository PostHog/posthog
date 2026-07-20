import dataclasses
from datetime import UTC, date, datetime, time
from typing import Any, Optional

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.settings import (
    DEFAULT_PAGE_SIZE,
    SURVEYMONKEY_ENDPOINTS,
)

# SurveyMonkey lists wrap rows in a `data` array and expose the next page as a full URL under
# `links.next`; the client walks that URL until it's absent.
_SURVEYS_INCLUDE = "date_created,date_modified,response_count,question_count"


@dataclasses.dataclass
class SurveyMonkeyResumeConfig:
    # Legacy fields from the pre-framework implementation, kept (with defaults) so a checkpoint
    # written by the old code still parses via ``dataclass(**saved)``. They are no longer written; a
    # loaded state carrying only these starts fresh (a full re-read, deduped on the primary key).
    next_url: Optional[str] = None
    remaining_survey_ids: Optional[list[str]] = None
    # Simple-resource (``surveys``) paginator snapshot: ``{"next_url": <next page to fetch>}``.
    paginator_state: Optional[dict[str, Any]] = None
    # Single-hop fan-out snapshot for a survey-scoped endpoint:
    # ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``.
    fanout_state: Optional[dict[str, Any]] = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """SurveyMonkey expects `YYYY-MM-DDTHH:MM:SS` (UTC, no offset) for its date filters."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo is not None else value
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, time.min).strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


def _cutoff_param_name(incremental_field: str | None, default_incremental_field: str | None) -> str:
    """Map the chosen cursor field to its server-side filter param."""
    chosen = incremental_field or default_incremental_field
    if chosen == "date_created":
        return "start_created_at"
    return "start_modified_at"


def _incremental_config(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> IncrementalConfig | None:
    """Server-side date filter (`start_modified_at` / `start_created_at`), only when we have a cursor.

    Mirrors the old behaviour: no filter on a first (full) sync, and the persisted watermark is
    formatted the way SurveyMonkey's date filters expect. Sorting ascending on the cursor keeps the
    watermark advancing monotonically.
    """
    config = SURVEYMONKEY_ENDPOINTS[endpoint]
    if not should_use_incremental_field or db_incremental_field_last_value is None or not config.incremental_fields:
        return None
    chosen = incremental_field or config.default_incremental_field
    return {
        "start_param": _cutoff_param_name(incremental_field, config.default_incremental_field),
        "cursor_path": chosen or "date_modified",
        "convert": _format_incremental_value,
    }


def _promote_survey_id(row: dict[str, Any]) -> dict[str, Any]:
    # include_from_parent injects the parent survey's id as ``_surveys_id``; expose it under the
    # ``survey_id`` column the child rows have always carried.
    if "_surveys_id" in row:
        row["survey_id"] = row.pop("_surveys_id")
    return row


def _explode_questions(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten one page of a `/surveys/{id}/details` payload into one row per question.

    The ``pages`` array is the data_selector, so each item here is a single page carrying its
    ``questions`` and the parent survey id (injected as ``_surveys_id``). An empty list drops the
    page — matching the old loop, which yielded no rows for a page without questions.
    """
    survey_id = page.get("_surveys_id")
    page_id = page.get("id")
    rows: list[dict[str, Any]] = []
    for question in page.get("questions", []) or []:
        row = dict(question)
        row["survey_id"] = survey_id
        row["page_id"] = page_id
        rows.append(row)
    return rows


def _client_config(access_token: str, base_url: str) -> ClientConfig:
    return {
        "base_url": base_url,
        # Auth (the Bearer token) is supplied via the framework auth config so its value is redacted
        # from every raised error and log sample; only the non-secret content headers are set here.
        "headers": {"Content-Type": "application/json", "Accept": "application/json"},
        "auth": {"type": "bearer", "token": access_token},
        # Every list endpoint returns its next page as a full URL under `links.next`.
        "paginator": JSONResponsePaginator(next_url_path="links.next"),
    }


def _surveys_resource(incremental: IncrementalConfig | None) -> EndpointResource:
    config = SURVEYMONKEY_ENDPOINTS["surveys"]
    endpoint: Endpoint = {
        "path": config.path,
        "params": {
            "per_page": config.page_size,
            # Pull the stable/cursor dates and counts that aren't returned on the bare survey object.
            "include": _SURVEYS_INCLUDE,
            # `/surveys` only sorts by date_modified; sort ascending so the watermark advances.
            "sort_by": config.sort_by,
            "sort_order": "ASC",
        },
        "data_selector": "data",
    }
    if incremental is not None:
        endpoint["incremental"] = incremental
    return {"name": "surveys", "endpoint": endpoint}


def _parent_surveys_resource() -> EndpointResource:
    # Fan-out enumerates every survey id via a bare `/surveys` listing (no include/sort/filter) — the
    # child endpoints must fan out over ALL surveys, never only the recently-modified slice.
    return {
        "name": "surveys",
        "endpoint": {
            "path": "/surveys",
            "params": {"per_page": DEFAULT_PAGE_SIZE},
            "data_selector": "data",
        },
    }


def _fanout_child_resource(endpoint: str, incremental: IncrementalConfig | None) -> EndpointResource:
    config = SURVEYMONKEY_ENDPOINTS[endpoint]
    child_endpoint: Endpoint = {
        "path": config.path,
        "params": {
            "survey_id": {"type": "resolve", "resource": "surveys", "field": "id"},
            "per_page": config.page_size,
        },
        "data_selector": "data",
    }
    if incremental is not None:
        child_endpoint["incremental"] = incremental
    return {
        "name": endpoint,
        "include_from_parent": ["id"],
        "endpoint": child_endpoint,
        "data_map": _promote_survey_id,
    }


def _questions_resource() -> EndpointResource:
    config = SURVEYMONKEY_ENDPOINTS["survey_questions"]
    return {
        "name": "survey_questions",
        "include_from_parent": ["id"],
        "endpoint": {
            "path": config.path,
            "params": {"survey_id": {"type": "resolve", "resource": "surveys", "field": "id"}},
            # Select the nested pages[] as items; the data_map explodes each into its questions.
            "data_selector": "pages",
        },
        "data_map": _explode_questions,
    }


def surveymonkey_source(
    access_token: str,
    base_url: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SurveyMonkeyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SURVEYMONKEY_ENDPOINTS[endpoint]
    incremental = _incremental_config(
        endpoint, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    client_config = _client_config(access_token, base_url)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    resource: Resource
    if endpoint == "surveys":
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [_surveys_resource(incremental)],
        }

        def save_simple(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash resumes
            # at the next page rather than re-reading from the top.
            if state is not None:
                resumable_source_manager.save_state(SurveyMonkeyResumeConfig(paginator_state=state))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_simple,
            initial_paginator_state=(resume.paginator_state if resume is not None else None),
        )
    else:
        child_resource = (
            _questions_resource() if endpoint == "survey_questions" else _fanout_child_resource(endpoint, incremental)
        )
        fanout_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [_parent_surveys_resource(), child_resource],
        }

        def save_fanout(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(SurveyMonkeyResumeConfig(fanout_state=state))

        resources = rest_api_resources(
            fanout_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_fanout,
            initial_paginator_state=(resume.fanout_state if resume is not None else None),
        )
        resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(access_token: str, base_url: str) -> tuple[bool, str | None]:
    """Cheap probe against `/users/me` to confirm the token is genuine."""
    url = f"{base_url}/users/me"
    try:
        response = make_tracked_session(redact_values=(access_token,)).get(
            url, headers=_get_headers(access_token), timeout=10
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid SurveyMonkey access token"
    if response.status_code == 403:
        return False, "SurveyMonkey access token is missing required scopes"

    try:
        message = response.json().get("error", {}).get("message")
    except (ValueError, AttributeError):
        message = None
    return False, message or f"SurveyMonkey API returned status {response.status_code}"
