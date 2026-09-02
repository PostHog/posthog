import re
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.settings import (
    CATALOG_ENDPOINTS,
    DIMENSION_VALUES_ENDPOINT,
    DIMENSIONS_ENDPOINT,
    INDICATOR_DATA_ENDPOINT,
    MAX_INDICATOR_CODES,
    MAX_VALIDATED_INDICATOR_CODES,
    PAGE_SIZE,
    GHOEndpointConfig,
)

BASE_URL = "https://ghoapi.azureedge.net/api"

# Codes may be pasted one per line, comma separated, or semicolon separated.
_CODE_SEPARATORS = re.compile(r"[,;\s]+")


@frozen
class WhoGhoResumeConfig:
    # $skip to resume from within the current resource.
    offset: int = 0
    # Position in the fanned-out list (configured indicator codes, or discovered dimension
    # codes). Only meaningful for indicator_data and dimension_values.
    item_index: int = 0


def parse_indicator_codes(raw: Optional[str]) -> list[str]:
    codes: list[str] = []
    for candidate in _CODE_SEPARATORS.split(raw or ""):
        code = candidate.strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def check_indicator_codes(indicator_codes: list[str]) -> Optional[str]:
    """User-facing error if the configured code list is empty or over the per-source cap.

    Checked both when the source is created and again when a sync starts, so a list saved
    before the cap existed (or through anything but the form) can't fan out unbounded.
    """
    if not indicator_codes:
        return "Enter at least one GHO indicator code, for example WHOSIS_000001."
    if len(indicator_codes) > MAX_INDICATOR_CODES:
        return (
            f"Too many indicator codes ({len(indicator_codes)}); enter at most {MAX_INDICATOR_CODES} distinct codes. "
            "Each code is re-checked for changes on every refresh."
        )
    return None


def _paginator() -> OffsetPaginator:
    # The API has no response field reporting how many rows remain, so pagination stops purely
    # on a short page (fewer rows than $top means the last page).
    return OffsetPaginator(limit=PAGE_SIZE, offset_param="$skip", limit_param="$top", total_path=None)


def _resource(name: str, path: str, params: dict[str, Any], write_disposition: Any = "replace") -> EndpointResource:
    return {
        "name": name,
        "table_name": name,
        "write_disposition": write_disposition,
        "endpoint": {
            "path": path,
            "data_selector": "value",
            "params": params,
        },
        "table_format": "delta",
    }


def _rest_config(resource: EndpointResource) -> RESTAPIConfig:
    return {
        # The GHO API is fully open, so there is no auth block to configure.
        "client": {
            "base_url": BASE_URL,
            "paginator": _paginator(),
        },
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [resource],
    }


def _catalog_pages(
    endpoint: GHOEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WhoGhoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = {"offset": resume.offset} if resume is not None and resume.offset > 0 else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("offset"):
            resumable_source_manager.save_state(WhoGhoResumeConfig(offset=int(state["offset"])))

    yield from rest_api_resource(
        _rest_config(_resource(endpoint.name, endpoint.path, {})),
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fetch_all_dimension_codes() -> list[str]:
    """One-off, unpaginated-by-default catalog: fetched fresh at the start of every
    dimension_values sync rather than hardcoded, since WHO adds dimensions over time."""
    session = make_tracked_session()
    codes: list[str] = []
    skip = 0
    while True:
        response = session.get(
            f"{BASE_URL}{CATALOG_ENDPOINTS[DIMENSIONS_ENDPOINT].path}", params={"$top": PAGE_SIZE, "$skip": skip}
        )
        response.raise_for_status()
        rows = response.json().get("value", [])
        codes.extend(row["Code"] for row in rows if row.get("Code"))
        if len(rows) < PAGE_SIZE:
            break
        skip += PAGE_SIZE
    return codes


def _dimension_values_pages(
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WhoGhoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    dimension_codes = _fetch_all_dimension_codes()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.item_index if resume is not None else 0
    start_offset = resume.offset if resume is not None else 0

    for index, code in enumerate(dimension_codes):
        if index < start_index:
            continue

        initial_paginator_state = {"offset": start_offset} if index == start_index and start_offset > 0 else None

        def save_checkpoint(state: Optional[dict[str, Any]], code_index: int = index) -> None:
            if state and state.get("offset"):
                resumable_source_manager.save_state(
                    WhoGhoResumeConfig(offset=int(state["offset"]), item_index=code_index)
                )
            else:
                # Finished this code's pages: point the checkpoint at the start of the next one
                # so a restart doesn't re-walk codes that already finished.
                resumable_source_manager.save_state(WhoGhoResumeConfig(offset=0, item_index=code_index + 1))

        path = f"/DIMENSION/{quote(code, safe='')}/DimensionValues"
        yield from rest_api_resource(
            _rest_config(_resource(DIMENSION_VALUES_ENDPOINT, path, {})),
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )


def _indicator_data_pages(
    indicator_codes: list[str],
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WhoGhoResumeConfig],
    should_use_incremental_field: bool,
    since: Optional[str],
) -> Iterator[list[dict[str, Any]]]:
    # This is the fan-out point: one full paginated walk per code. Refuse an oversized list here
    # rather than letting a stale config burn capacity indefinitely.
    codes_error = check_indicator_codes(indicator_codes)
    if codes_error:
        raise ValueError(f"WHO GHO source misconfigured: {codes_error}")

    write_disposition: Any = (
        {"disposition": "merge", "strategy": "upsert"} if should_use_incremental_field else "replace"
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.item_index if resume is not None else 0
    start_offset = resume.offset if resume is not None else 0

    for index, indicator_code in enumerate(indicator_codes):
        if index < start_index:
            continue

        initial_paginator_state = {"offset": start_offset} if index == start_index and start_offset > 0 else None

        def save_checkpoint(state: Optional[dict[str, Any]], code_index: int = index) -> None:
            if state and state.get("offset"):
                resumable_source_manager.save_state(
                    WhoGhoResumeConfig(offset=int(state["offset"]), item_index=code_index)
                )
            else:
                resumable_source_manager.save_state(WhoGhoResumeConfig(offset=0, item_index=code_index + 1))

        params: dict[str, Any] = {}
        if should_use_incremental_field and since is not None:
            # `date()` truncates the comparison to a plain date; the API rejects (or, for the
            # bare property, mishandles) a full ISO datetime-with-offset literal here.
            params["$filter"] = f"date(Date) gt {since}"

        yield from rest_api_resource(
            _rest_config(
                _resource(INDICATOR_DATA_ENDPOINT, f"/{quote(indicator_code, safe='')}", params, write_disposition)
            ),
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )


def who_gho_source(
    endpoint: str,
    indicator_codes: list[str],
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WhoGhoResumeConfig],
    should_use_incremental_field: bool = False,
    since: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint == INDICATOR_DATA_ENDPOINT:
        yield from _indicator_data_pages(
            indicator_codes, team_id, job_id, resumable_source_manager, should_use_incremental_field, since
        )
    elif endpoint == DIMENSION_VALUES_ENDPOINT:
        yield from _dimension_values_pages(team_id, job_id, resumable_source_manager)
    else:
        yield from _catalog_pages(CATALOG_ENDPOINTS[endpoint], team_id, job_id, resumable_source_manager)

    # Walked to completion: drop the checkpoint so a later attempt restarts cleanly instead of
    # resuming past the end and syncing nothing.
    resumable_source_manager.clear_state()


def validate_credentials(indicator_codes: list[str]) -> tuple[bool, Optional[str]]:
    """Confirm the API is reachable and every configured indicator code resolves to a series."""
    codes_error = check_indicator_codes(indicator_codes)
    if codes_error:
        return False, codes_error

    session = make_tracked_session()
    unknown_codes: list[str] = []

    for indicator_code in indicator_codes[:MAX_VALIDATED_INDICATOR_CODES]:
        response = session.get(f"{BASE_URL}/{quote(indicator_code, safe='')}", params={"$top": 1})
        if response.status_code == 404:
            unknown_codes.append(indicator_code)
            continue
        if response.status_code != 200:
            return False, "Could not reach the WHO Global Health Observatory API. Please try again."

    if unknown_codes:
        return False, f"These indicator codes were not found: {', '.join(unknown_codes)}."

    return True, None
