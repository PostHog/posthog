import dataclasses
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.settings import SAVVYCAL_ENDPOINTS

SAVVYCAL_BASE_URL = "https://api.savvycal.com/v1"
# List endpoints accept a `limit` of up to 100; the largest page minimises round trips.
PAGE_SIZE = 100
# Cheap single-object endpoint used to confirm a token is genuine. Personal access tokens carry
# the account's full read access, so one probe validates every list endpoint.
DEFAULT_PROBE_PATH = "/me"


@dataclasses.dataclass
class SavvyCalResumeConfig:
    # Cursor for the next page, taken verbatim from the API's `metadata.after`. `None` means start
    # from the first page. A crashed sync resumes from the page after the last one yielded; merge
    # dedupes the re-pulled page on `id`.
    after: str | None = None
    # The `from` date bound the interrupted run was started with (events incremental only). Reused
    # verbatim on resume so the saved cursor stays paired with the query it was minted under, even
    # if the watermark advanced between attempts.
    from_date: str | None = None


def _format_from_date(value: Any) -> str:
    """Format an incremental cursor for the events `from` filter (YYYY-MM-DD).

    `from` is an inclusive lower bound on the event *start date*, so truncating a datetime
    watermark to its date re-fetches the watermark day; merge dedupes on `id`.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _build_params(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resumed_from_date: str | None,
) -> dict[str, Any]:
    config = SAVVYCAL_ENDPOINTS[endpoint]
    params: dict[str, Any] = {"limit": PAGE_SIZE, **config.params}

    if endpoint == "events":
        from_date = resumed_from_date
        if from_date is None and should_use_incremental_field and db_incremental_field_last_value is not None:
            from_date = _format_from_date(db_incremental_field_last_value)

        if from_date is not None:
            # `from` only applies with period=fixed. The spec marks `until` independently optional,
            # so we leave the window open-ended; unverifiable without live credentials.
            params["period"] = "fixed"
            params["from"] = from_date
        else:
            params["period"] = "all"

    return params


def savvycal_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SavvyCalResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SAVVYCAL_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    params = _build_params(
        endpoint,
        should_use_incremental_field,
        db_incremental_field_last_value,
        resumed_from_date=resume.from_date if resume else None,
    )
    # The `from` bound the saved cursor is paired with — persisted alongside every checkpoint so a
    # resumed run keeps the cursor and its query in lockstep.
    saved_from_date = params.get("from")

    endpoint_resource: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": params,
            # List endpoints wrap records in {"entries": [...], "metadata": {"after": ...}}.
            "data_selector": "entries",
            # A 200 whose body isn't the {"entries": [...]} shape is treated as transient (a
            # truncating proxy / partial read) and retried, matching the old defensive handling.
            "data_selector_malformed_retryable": True,
        },
    }

    if config.redact_fields:
        redact_fields = config.redact_fields

        def drop_secrets(item: dict[str, Any]) -> dict[str, Any]:
            # Strip secret-bearing fields (e.g. a webhook signing secret) before a row lands in a
            # table any project member can query.
            return {k: v for k, v in item.items() if k not in redact_fields}

        endpoint_resource["data_map"] = drop_secrets

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SAVVYCAL_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and error messages; only the non-secret accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # A null `metadata.after` cursor means the end of the collection.
            "paginator": JSONResponseCursorPaginator(cursor_path="metadata.after", cursor_param="after"),
        },
        "resource_defaults": {},
        "resources": [endpoint_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.after is not None:
        initial_paginator_state = {"cursor": resume.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next cursor (already-yielded pages persist) rather than skipping it. The saved
        # `from_date` carries the original bound forward, never a recomputed (advanced) watermark.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(SavvyCalResumeConfig(after=state["cursor"], from_date=saved_from_date))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Events are requested with direction=asc on start time, matching the incremental cursor;
        # other endpoints are full refresh, where the watermark is unused.
        sort_mode="asc",
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe `/me` to validate the personal access token, preserving per-status messages."""
    session_factory: Callable[[], Any] = lambda: make_tracked_session(redact_values=(api_key,))
    ok, status = validate_via_probe(
        session_factory,
        f"{SAVVYCAL_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid SavvyCal personal access token"
    if status is None:
        return False, "Could not validate SavvyCal personal access token"
    return False, f"SavvyCal returned HTTP {status}"
