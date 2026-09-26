from collections.abc import Iterator
from typing import Any, Optional

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.membrain.settings import MEMBRAIN_ENDPOINTS

PAGE_START = 0
PROBE_TIMEOUT_SECONDS = 10.0
CUSTOM_FIELDS_TIMEOUT_SECONDS = 60.0

# The reference's per-entity custom-field arrays are keyed `<entity>CustomFields`
# (companyCustomFields, contactCustomFields, userCustomFields, ...).
_CUSTOM_FIELDS_KEY_SUFFIX = "CustomFields"


@frozen
class MembrainResumeConfig:
    # Row offset of the next page (the `to` of the last page yielded). Offset pagination is
    # deterministic under the explicit sort we request, so a crashed sync resumes from here.
    next_from: int = PAGE_START


def base_url(subdomain: str) -> str:
    """Per-account hostname: every Membrain instance lives on its own subdomain."""
    return f"https://{subdomain}.membrain.com/API/v2"


def _auth_headers(api_key: str) -> dict[str, str]:
    # Membrain accepts the key either as an `?APIKey=` query param or an `APIKey` request
    # header. The header keeps the key out of logged URLs.
    return {"APIKey": api_key, "Accept": "application/json"}


class MembrainPaginator(BasePaginator):
    """Offset paginator for Membrain's `{count, from, to, items}` envelope.

    `to` is the end of the returned window and doubles as the next request's `From`; the last
    page is the one where `to` reaches `count`. All three counters arrive as JSON strings.
    """

    def __init__(self) -> None:
        super().__init__()
        self._current_from = PAGE_START
        self._next_from: Optional[int] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume offset on the first request; a fresh run starts unparametered
        # at offset 0.
        if self._current_from != PAGE_START:
            if request.params is None:
                request.params = {}
            request.params["From"] = self._current_from

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._next_from = None
        body = response.json()

        if not isinstance(body, dict) or "count" not in body or "to" not in body:
            self._has_next_page = False
            return

        # int() raising on a non-numeric counter is deliberate: a malformed envelope must fail
        # loud rather than silently truncate the sync at page one.
        count = int(body["count"])
        to = int(body["to"])

        # `to >= count` is the documented end of the set; a `to` that did not advance past the
        # offset we requested would otherwise refetch the same window forever.
        if to >= count or to <= self._current_from:
            self._has_next_page = False
            return

        self._has_next_page = True
        self._next_from = to

    def update_request(self, request: Request) -> None:
        if self._next_from is None:
            return
        self._current_from = self._next_from
        if request.params is None:
            request.params = {}
        request.params["From"] = self._current_from

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._next_from is not None:
            return {"next_from": self._next_from}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_from = state.get("next_from")
        if next_from is not None:
            self._current_from = int(next_from)
            self._has_next_page = True


def _custom_fields_rows(api_key: str, subdomain: str) -> Iterator[list[dict[str, Any]]]:
    """Flatten `/customFields/` into one row per field definition with an `EntityType` column."""
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    response = session.get(
        f"{base_url(subdomain)}/customFields/",
        headers=_auth_headers(api_key),
        timeout=CUSTOM_FIELDS_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()

    if not isinstance(body, dict) or not any(key.endswith(_CUSTOM_FIELDS_KEY_SUFFIX) for key in body):
        # Membrain reports some failures as HTTP 200 with an error body, so an unexpected shape
        # must fail loud rather than sync zero rows.
        keys = sorted(body.keys())[:20] if isinstance(body, dict) else type(body).__name__
        raise ValueError(f"Unexpected Membrain customFields response shape (body keys: {keys})")

    rows: list[dict[str, Any]] = []
    for key, definitions in body.items():
        if not key.endswith(_CUSTOM_FIELDS_KEY_SUFFIX) or not isinstance(definitions, list):
            continue
        entity_type = key.removesuffix(_CUSTOM_FIELDS_KEY_SUFFIX)
        for definition in definitions:
            rows.append({**definition, "EntityType": entity_type})

    yield rows


def membrain_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MembrainResumeConfig],
) -> SourceResponse:
    config = MEMBRAIN_ENDPOINTS[endpoint]

    if endpoint == "custom_fields":
        return SourceResponse(
            name=endpoint,
            items=lambda: _custom_fields_rows(api_key, subdomain),
            primary_keys=config.primary_keys,
            partition_count=1,
            partition_size=1,
        )

    endpoint_config: Endpoint
    if config.paged:
        params: dict[str, Any] = dict(config.extra_params)
        if config.supports_sort_by:
            # An explicit stable sort keeps offset pages from drifting as rows are written
            # mid-sync (activities otherwise default to Date DESC, companies and contacts to
            # Name ASC).
            params["SortBy"] = "CreatedDate ASC"
        endpoint_config = {
            "path": config.path,
            "params": params,
            "paginator": MembrainPaginator(),
            # A 200 body without `items` (e.g. Membrain's `{"error": ...}` failure shape) is an
            # auth or shape failure. Fail loud rather than silently syncing zero rows.
            "data_selector": "items",
            "data_selector_required": True,
        }
    else:
        endpoint_config = {
            "path": config.path,
            "paginator": SinglePagePaginator(),
            # Bare-array endpoint: a non-list 200 body means the shape changed or the request
            # failed, so fail loud instead of syncing a stray object as a row.
            "data_selector_required": True,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(subdomain),
            "headers": {"Accept": "application/json"},
            # The framework redacts the key from logged URLs, headers and raised error messages.
            "auth": {"type": "api_key", "api_key": api_key, "name": "APIKey", "location": "header"},
            # Defense-in-depth: a 30x must not replay the credentialed APIKey header off-host.
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paged and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_from": resume.next_from}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Saved AFTER a page is yielded, pointing at the next offset to fetch; no save once
        # pagination is exhausted (state is None).
        if state and state.get("next_from") is not None:
            resumable_source_manager.save_state(MembrainResumeConfig(next_from=int(state["next_from"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint if config.paged else None,
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
    )


def validate_credentials(api_key: str, subdomain: str) -> tuple[bool, str | None]:
    """Probe `/users/` (present on every instance, bare array response) to validate the key.

    Membrain reports a missing instance as HTTP 200 with `{"error": "Instance not found"}`, so
    the body has to be inspected as well as the status. Fixed messages only: the raw response or
    exception text is never surfaced.
    """
    try:
        session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
        response = session.get(
            f"{base_url(subdomain)}/users/",
            headers=_auth_headers(api_key),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, "Could not connect to Membrain. Check the subdomain and try again."

    if response.status_code in (401, 403):
        return False, "Invalid Membrain API key. Ask a Membrain admin to check the key, then try again."
    if response.status_code != 200:
        return False, f"Membrain returned HTTP {response.status_code}. Try again in a few minutes."

    try:
        body = response.json()
    except ValueError:
        return False, "Membrain returned an unexpected response. Check the subdomain and try again."

    if isinstance(body, list):
        return True, None

    if isinstance(body, dict) and "error" in body:
        if "instance" in str(body["error"]).lower():
            return (
                False,
                "No Membrain instance was found at that subdomain. Enter just the subdomain of your "
                "Membrain URL: the 'acme' in 'acme.membrain.com'.",
            )
        return False, "Membrain rejected the request. Check your API key and subdomain, then try again."

    return False, "Membrain returned an unexpected response. Check the subdomain and try again."
