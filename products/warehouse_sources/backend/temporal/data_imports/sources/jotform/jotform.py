import json
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
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
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.settings import (
    JOTFORM_ENDPOINTS,
    JotformEndpointConfig,
)

# Regional API hosts. Enterprise installations live on the org's own domain (see resolve_base_url).
JOTFORM_REGION_BASE_URLS = {
    "us": "https://api.jotform.com",
    "eu": "https://eu-api.jotform.com",
    "hipaa": "https://hipaa-api.jotform.com",
}

# Jotform's `filter` operator for "created/updated after" is `:gt` (strictly greater than).
FILTER_GT_SUFFIX = ":gt"


@dataclasses.dataclass
class JotformResumeConfig:
    # Offset of the page to (re)fetch when resuming a list endpoint. The framework saves the offset
    # of the NEXT page here after each page is committed (merge dedupes on the primary key).
    offset: int = 0
    # Retained for backward-compatible parsing of resume state saved by the pre-rest_source
    # implementation (`dataclass(**saved)` must still load). No longer written.
    form_id: Optional[str] = None
    # Opaque fan-out checkpoint for the questions resource: the rest_source dependent-resource
    # resume state (`{"completed": [...], "current": ..., "child_state": ...}`).
    fanout_state: Optional[dict[str, Any]] = None


def normalize_enterprise_host(enterprise_domain: Optional[str]) -> Optional[str]:
    host = (enterprise_domain or "").strip()
    if not host:
        return None
    host = host.removeprefix("https://").removeprefix("http://").strip("/")
    return host or None


def resolve_base_url(region: Optional[str], enterprise_domain: Optional[str] = None) -> str:
    host = normalize_enterprise_host(enterprise_domain)
    if host is not None:
        # Jotform Enterprise serves its API under `/API` on the organisation's own domain. Couldn't
        # be curl-verified without an Enterprise account, so this path is best-effort.
        return f"https://{host}/API"
    return JOTFORM_REGION_BASE_URLS.get((region or "us").lower(), JOTFORM_REGION_BASE_URLS["us"])


def _headers(api_key: str) -> dict[str, str]:
    # Jotform accepts the API key either as the `APIKEY` header or an `apiKey` query param. The
    # header keeps the secret out of request URLs (and out of logs).
    return {"APIKEY": api_key, "Accept": "application/json"}


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _format_filter_value(value: Any) -> Optional[str]:
    """Format an incremental cursor as Jotform's ``YYYY-MM-DD HH:MM:SS`` filter literal.

    Future-dated cursors are capped at now: a ``<field>:gt <future>`` filter returns nothing and
    would wedge the sync until wall-clock catches up. The watermark and the API's ``created_at`` /
    ``updated_at`` come from the same field round-tripped, so the wall-clock components line up.
    """
    parsed = _coerce_datetime(value)
    if parsed is None:
        return None
    aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    capped = min(aware, datetime.now(UTC))
    return capped.strftime("%Y-%m-%d %H:%M:%S")


def _filter_convert(field_name: str) -> Callable[[Any], Optional[str]]:
    """Build the incremental `convert` that turns a watermark into Jotform's JSON `filter` value.

    Returns ``None`` for an unparseable/absent watermark so the framework drops the `filter` param
    (a `None` param is not sent), matching the hand-rolled "omit filter when it can't be formatted".
    """

    def convert(value: Any) -> Optional[str]:
        formatted = _format_filter_value(value)
        if formatted is None:
            return None
        return json.dumps({f"{field_name}{FILTER_GT_SUFFIX}": formatted}, separators=(",", ":"))

    return convert


def _client_config(api_key: str, base_url: str) -> dict[str, Any]:
    # The key rides in the `APIKEY` header via framework auth so it is redacted from every raised
    # error message; only the non-secret Accept header is set on the client. `enterprise_domain` is
    # user-supplied, so pin redirects off (defense-in-depth on top of the Smokescreen egress proxy)
    # to keep the key-bearing request on the validated host.
    return {
        "base_url": base_url,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "APIKEY", "location": "header"},
        "allow_redirects": False,
    }


def _list_params(
    config: JotformEndpointConfig,
    last_value: Optional[Any],
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if not config.incremental_fields:
        # Full-refresh endpoints (reports): no orderby/filter.
        return params

    field_name = incremental_field or config.default_incremental_field
    if not field_name:
        return params

    # Order by the cursor field so pages arrive oldest-first and the asc watermark advances.
    params["orderby"] = field_name
    if last_value is not None:
        params["filter"] = {
            "type": "incremental",
            "cursor_path": field_name,
            "convert": _filter_convert(field_name),
        }
    return params


def _question_row(row: dict[str, Any]) -> dict[str, Any]:
    # `include_from_parent=["id"]` injects the parent form's id under `_forms_id`; expose it as
    # `form_id` (stringified) so the row shape matches the hand-rolled source. `qid` is unique only
    # within a form, so every row carries the form id for a table-wide key.
    form_id = row.pop("_forms_id")
    row["form_id"] = str(form_id)
    return row


def _list_source(
    api_key: str,
    base_url: str,
    endpoint: str,
    config: JotformEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[JotformResumeConfig],
    last_value: Optional[Any],
    incremental_field: Optional[str],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": {
            **_client_config(api_key, base_url),
            # Jotform reports no reliable top-level total; termination is the short/empty page.
            "paginator": OffsetPaginator(limit=config.page_size, total_path=None),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _list_params(config, last_value, incremental_field),
                    "data_selector": "content",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is committed so a crash re-yields the last page (merge dedupes) rather
        # than skipping it; the paginator only reports state while a next page remains.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(JotformResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _questions_source(
    api_key: str,
    base_url: str,
    config: JotformEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[JotformResumeConfig],
) -> Resource:
    forms_config = JOTFORM_ENDPOINTS["forms"]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, base_url),
        "resources": [
            {
                "name": "forms",
                "endpoint": {
                    "path": forms_config.path,
                    "params": {"orderby": "created_at"},
                    "data_selector": "content",
                    "paginator": OffsetPaginator(limit=forms_config.page_size, total_path=None),
                },
            },
            {
                "name": "questions",
                "include_from_parent": ["id"],
                "endpoint": {
                    "path": config.path,
                    "params": {"form_id": {"type": "resolve", "resource": "forms", "field": "id"}},
                    # `/form/{id}/questions` returns an object keyed by question id; `.*` yields the
                    # question objects as rows.
                    "data_selector": "content.*",
                    "paginator": SinglePagePaginator(),
                },
                "data_map": _question_row,
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(JotformResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    forms_resource = next(r for r in resources if r.name == "forms")
    # Skip forms without an id so the fan-out never tries to resolve a form-less path (the
    # hand-rolled source skipped id-less form rows too).
    forms_resource.add_filter(lambda form: form.get("id") is not None)
    return next(r for r in resources if r.name == "questions")


def validate_credentials(api_key: str, region: Optional[str], enterprise_domain: Optional[str] = None) -> bool:
    """Confirm the API key is valid for the target host. ``/user`` is the cheapest authenticated probe."""
    # Same SSRF posture as the sync client: no redirects off the validated host, redact the key.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        f"{resolve_base_url(region, enterprise_domain)}/user",
        headers=_headers(api_key),
    )
    return ok


def jotform_source(
    api_key: str,
    region: Optional[str],
    enterprise_domain: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[JotformResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = JOTFORM_ENDPOINTS[endpoint]
    base_url = resolve_base_url(region, enterprise_domain)
    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    if config.fan_out_over_forms:
        resource = _questions_source(api_key, base_url, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _list_source(
            api_key,
            base_url,
            endpoint,
            config,
            team_id,
            job_id,
            resumable_source_manager,
            last_value,
            incremental_field,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(config.primary_keys),
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
