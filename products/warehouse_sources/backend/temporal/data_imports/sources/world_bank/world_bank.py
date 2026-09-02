import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.settings import (
    CATALOG_ENDPOINTS,
    INDICATOR_DATA_ENDPOINT,
    PER_PAGE,
    WorldBankEndpointConfig,
)

BASE_URL_TEMPLATE = "https://api.worldbank.org/{api_version}"

# Every response is a two-element array: a metadata object followed by the rows. XML is the
# API default, so `format=json` has to ride on every request for this to hold.
DATA_SELECTOR = "[1]"
PAGE_COUNT_PATH = "[0].pages"

# Every configured code costs its own paginated, full-history walk on every refresh (~17k
# observations, ~17 requests each), so the list has to be bounded or a single source can pull the
# whole 16,000-series catalog and consume worker, network, and storage capacity indefinitely.
MAX_INDICATOR_CODES = 50

# Source-create probes one request per indicator code, so cap how many are checked to keep the
# form responsive. Codes beyond the cap are still synced; a bad one surfaces as a sync error.
MAX_VALIDATED_INDICATOR_CODES = 20

# Codes may be pasted one per line, comma separated, or semicolon separated (the API's own
# multi-indicator delimiter).
_CODE_SEPARATORS = re.compile(r"[,;\s]+")


@dataclasses.dataclass
class WorldBankResumeConfig:
    # Page to resume from, 1-based like the API's own `page` param.
    page: int = 1
    # Position in the configured indicator code list. Only meaningful for `indicator_data`,
    # which walks one paginated request per code.
    indicator_index: int = 0


def parse_indicator_codes(raw: Optional[str]) -> list[str]:
    codes: list[str] = []
    for candidate in _CODE_SEPARATORS.split(raw or ""):
        code = candidate.strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def check_indicator_codes(indicator_codes: list[str]) -> Optional[str]:
    """User-facing error if the configured code list is empty or over the per-source cap.

    Checked both when the source is created and again when a sync starts, so a list that was
    saved before the cap existed (or through anything but the form) can't fan out unbounded.
    """
    if not indicator_codes:
        return "Enter at least one World Bank indicator code, for example SP.POP.TOTL."
    if len(indicator_codes) > MAX_INDICATOR_CODES:
        return (
            f"Too many indicator codes ({len(indicator_codes)}); enter at most {MAX_INDICATOR_CODES} distinct codes. "
            "Each code is re-synced in full on every refresh."
        )
    return None


def _page_count(response: Response) -> Optional[int]:
    """Total page count from the response metadata object, or None when unreadable.

    Some endpoints (`/source`, `/region`, `/incomeLevel`, `/lendingType`) report it as a string
    while others report it as a number, so it always goes through int().
    """
    try:
        values = find_values(PAGE_COUNT_PATH, response.json())
    except Exception:
        return None
    if not values:
        return None
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


class WorldBankPaginator(PageNumberPaginator):
    """1-based `page` / `per_page` pagination driven by the metadata object's page count."""

    def __init__(self, page: int = 1) -> None:
        super().__init__(base_page=1, page=page, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        self.page += 1
        page_count = _page_count(response)
        # Requesting a page past the end returns an empty row list rather than an error, so an
        # unreadable page count just costs one extra request.
        self._has_next_page = page_count is None or self.page <= page_count

    def __str__(self) -> str:
        return f"WorldBankPaginator(page={self.page})"


def flatten_observation(row: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested indicator and country ids to the row root.

    Observations carry no id of their own, so the primary key is built from them.
    """
    indicator = row.get("indicator") or {}
    country = row.get("country") or {}
    return {
        **row,
        "indicator_id": indicator.get("id"),
        "indicator_name": indicator.get("value"),
        "country_id": country.get("id"),
        "country_name": country.get("value"),
    }


def _rest_config(api_version: str, resource: EndpointResource) -> RESTAPIConfig:
    return {
        # The Indicators API is fully open, so there is no auth block to configure.
        "client": {
            "base_url": BASE_URL_TEMPLATE.format(api_version=api_version),
            "paginator": WorldBankPaginator(),
        },
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [resource],
    }


def _endpoint_resource(name: str, path: str) -> EndpointResource:
    return {
        "name": name,
        "table_name": name,
        "write_disposition": "replace",
        "endpoint": {
            "path": path,
            "data_selector": DATA_SELECTOR,
            # An unknown indicator code or a malformed request comes back as HTTP 200 with a
            # `[{"message": [...]}]` body, which matches nothing — fail loud instead of
            # recording an empty table.
            "data_selector_required": True,
            "params": {"format": "json", "per_page": PER_PAGE},
        },
        "table_format": "delta",
    }


def _indicator_data_resource(indicator_code: str) -> EndpointResource:
    resource = _endpoint_resource(
        INDICATOR_DATA_ENDPOINT,
        f"/country/all/indicator/{quote(indicator_code, safe='')}",
    )
    resource["data_map"] = flatten_observation
    return resource


def _catalog_pages(
    endpoint: WorldBankEndpointConfig,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorldBankResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = {"page": resume.page} if resume is not None and resume.page > 1 else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page"):
            resumable_source_manager.save_state(WorldBankResumeConfig(page=int(state["page"])))

    yield from rest_api_resource(
        _rest_config(api_version, _endpoint_resource(endpoint.name, endpoint.path)),
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _indicator_data_pages(
    indicator_codes: list[str],
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorldBankResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # This is the fan-out point: one full paginated walk per code. Refuse an oversized list here
    # rather than letting a stale config burn capacity indefinitely.
    codes_error = check_indicator_codes(indicator_codes)
    if codes_error:
        raise ValueError(f"World Bank source misconfigured: {codes_error}")

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.indicator_index if resume is not None else 0
    start_page = resume.page if resume is not None else 1

    for index, indicator_code in enumerate(indicator_codes):
        if index < start_index:
            continue

        initial_paginator_state = {"page": start_page} if index == start_index and start_page > 1 else None

        def save_checkpoint(state: Optional[dict[str, Any]], code_index: int = index) -> None:
            if state and state.get("page"):
                resumable_source_manager.save_state(
                    WorldBankResumeConfig(page=int(state["page"]), indicator_index=code_index)
                )
            else:
                # Last page of this code: point the checkpoint at the start of the next one so a
                # restart doesn't re-walk codes that already finished.
                resumable_source_manager.save_state(WorldBankResumeConfig(page=1, indicator_index=code_index + 1))

        yield from rest_api_resource(
            _rest_config(api_version, _indicator_data_resource(indicator_code)),
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )


def world_bank_source(
    endpoint: str,
    indicator_codes: list[str],
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorldBankResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    if endpoint == INDICATOR_DATA_ENDPOINT:
        yield from _indicator_data_pages(indicator_codes, api_version, team_id, job_id, resumable_source_manager)
    else:
        yield from _catalog_pages(CATALOG_ENDPOINTS[endpoint], api_version, team_id, job_id, resumable_source_manager)

    # Walked to completion: drop the checkpoint so a later attempt restarts cleanly instead of
    # resuming past the end and syncing nothing.
    resumable_source_manager.clear_state()


def validate_credentials(indicator_codes: list[str], api_version: str) -> tuple[bool, Optional[str]]:
    """Confirm the API is reachable and every configured indicator code resolves to a series."""
    codes_error = check_indicator_codes(indicator_codes)
    if codes_error:
        return False, codes_error

    base_url = BASE_URL_TEMPLATE.format(api_version=api_version)
    session = make_tracked_session()
    unknown_codes: list[str] = []

    for indicator_code in indicator_codes[:MAX_VALIDATED_INDICATOR_CODES]:
        response = session.get(
            f"{base_url}/indicator/{quote(indicator_code, safe='')}",
            params={"format": "json", "per_page": "1"},
        )
        if response.status_code != 200:
            return False, "Could not reach the World Bank Indicators API. Please try again."

        try:
            body = response.json()
        except ValueError:
            return False, "The World Bank Indicators API returned an unexpected response. Please try again."

        # A known code returns `[metadata, [series]]`; an unknown one returns a single-element
        # array carrying an error message.
        rows = body[1] if isinstance(body, list) and len(body) > 1 else None
        if not rows:
            unknown_codes.append(indicator_code)

    if unknown_codes:
        return False, f"These indicator codes were not found: {', '.join(unknown_codes)}."

    return True, None
