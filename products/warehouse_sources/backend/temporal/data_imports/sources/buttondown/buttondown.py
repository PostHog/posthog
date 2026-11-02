from datetime import date, datetime, timedelta
from typing import Any, Optional, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.settings import (
    BUTTONDOWN_ENDPOINTS,
    ButtondownEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BUTTONDOWN_BASE_URL = "https://api.buttondown.com/v1"
# Buttondown's API is date-versioned. Unpinned requests get whatever version is newest, so send the
# version this code was written against on every request.
BUTTONDOWN_API_VERSION = "2026-04-01"


@frozen
class ButtondownResumeConfig:
    # Absolute URL of the next unfetched page. Buttondown paginates DRF-style: each page body carries
    # a fully-formed `next` link (or null on the last page).
    next_url: Optional[str] = None
    # Per-subscriber endpoints checkpoint the fan-out instead: the subscribers already done and the
    # child page of the one in progress.
    fanout_state: Optional[dict[str, Any]] = None


def _headers(api_version: str) -> dict[str, str]:
    # Auth rides the framework's api_key auth so its value is redacted from logs and samples; only
    # the non-secret version/accept headers are set here.
    return {"X-API-Version": api_version, "Accept": "application/json"}


def _to_start_date(value: Any) -> Optional[str]:
    """Format an incremental watermark as the `YYYY-MM-DD` Buttondown's date filters expect.

    The filters take a date, not a timestamp, and the docs word some of them as "after the given
    date" without saying whether that bound is inclusive. Stepping back a day makes the request
    overlap instead of risking a same-day gap; the extra rows merge away on primary key.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        day = value.date()
    elif isinstance(value, date):
        day = value
    else:
        try:
            day = datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            # An unparseable watermark drops the filter, which costs a full scan but never skips rows.
            return None

    return (day - timedelta(days=1)).isoformat()


def _client_config(api_key: str, api_version: str) -> ClientConfig:
    return {
        "base_url": BUTTONDOWN_BASE_URL,
        "headers": _headers(api_version),
        "auth": {
            "type": "api_key",
            "name": "Authorization",
            # Buttondown requires the literal "Token " prefix, not "Bearer ".
            "api_key": f"Token {api_key}",
            "location": "header",
        },
        "paginator": JSONResponsePaginator(next_url_path="next"),
        # Pagination follows absolute `next` links straight out of the response body, so pin
        # them to the API host: a spoofed link would otherwise replay the API key elsewhere.
        "allowed_hosts": [],
    }


def _top_level_resource(
    config: ButtondownEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ButtondownResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
) -> Resource:
    params: dict[str, Any] = {}
    if config.ordering is not None:
        params["ordering"] = config.ordering
    if should_use_incremental_field and config.incremental_start_param is not None:
        params[config.incremental_start_param] = {
            "type": "incremental",
            "cursor_path": "creation_date",
            "initial_value": None,
            "convert": _to_start_date,
        }

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                if should_use_incremental_field
                else "replace",
                "table_format": "delta",
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "results",
                    # A 200 without `results` means the envelope changed — fail loud rather than
                    # silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Saved after a page is yielded, so a crash re-yields the last page (merge dedupes) instead
        # of skipping it. No state means no next page.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(ButtondownResumeConfig(next_url=str(state["next_url"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_resource(
    config: ButtondownEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ButtondownResumeConfig],
) -> Resource:
    assert config.fanout is not None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(ButtondownResumeConfig(fanout_state=state))

    results_selector: Endpoint = {"data_selector": "results", "data_selector_required": True}
    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=BUTTONDOWN_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
            parent_endpoint_extra=results_selector,
            child_endpoint_extra=results_selector,
        ),
    )


def buttondown_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ButtondownResumeConfig],
    api_version: str = BUTTONDOWN_API_VERSION,
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    config = BUTTONDOWN_ENDPOINTS[endpoint]
    client_config = _client_config(api_key, api_version)

    if config.fanout is not None:
        resource = _fanout_resource(config, client_config, team_id, job_id, resumable_source_manager)
    else:
        resource = _top_level_resource(
            config,
            client_config,
            team_id,
            job_id,
            resumable_source_manager,
            db_incremental_field_last_value,
            should_use_incremental_field,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, api_version: str = BUTTONDOWN_API_VERSION) -> tuple[bool, int | None]:
    # /accounts/me is the cheapest authenticated endpoint: it returns the account the key belongs to
    # and 401s on a bad key, without paging any newsletter data.
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BUTTONDOWN_BASE_URL}/accounts/me",
        headers={"Authorization": f"Token {api_key}", **_headers(api_version)},
    )
