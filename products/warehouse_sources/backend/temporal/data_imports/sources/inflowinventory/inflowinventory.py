import re
import dataclasses
from typing import Any, Optional

import requests
from requests import Request, Response
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.settings import (
    INFLOWINVENTORY_ENDPOINTS,
)

INFLOWINVENTORY_BASE_URL = "https://cloudapi.inflowinventory.com"
# inFlow requires a date-based API version header on every request; pin a recent documented version.
INFLOWINVENTORY_API_VERSION = "2023-04-01"
# The list endpoints accept up to 100 records per page; the largest page minimises round trips.
PAGE_SIZE = 100
# inFlow company IDs are GUIDs. Restrict to host/path-safe characters so the credential stays
# pinned to cloudapi.inflowinventory.com and can't be redirected via a crafted path segment.
COMPANY_ID_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")


@dataclasses.dataclass
class InflowInventoryResumeConfig:
    # The `after` cursor is the ID of the last row yielded. inFlow returns rows ordered by ID, so a
    # crashed full-refresh sync resumes from the record after the last one persisted; merge dedupes
    # on the primary key.
    after: str | None = None


def base_url(company_id: str) -> str:
    return f"{INFLOWINVENTORY_BASE_URL}/{company_id}"


def _version_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs and
    # raised error messages; only the non-secret version/accept header is set here.
    return {"Accept": f"application/json;version={INFLOWINVENTORY_API_VERSION}"}


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", **_version_headers()}


def _make_session(api_key: str) -> requests.Session:
    # Redirects are pinned off so the Bearer key can't be replayed to a cross-host redirect target
    # (SSRF / credential-exfiltration defense). urllib3 retries are disabled — the credential probe
    # is a single request that must not silently retry a transient failure.
    return make_tracked_session(
        headers=_headers(api_key), redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0)
    )


class InflowInventoryPaginator(BasePaginator):
    """Cursor pagination where the ``after`` cursor is the last row's ``id_field`` value.

    inFlow list endpoints return a bare JSON array ordered by ID. A page shorter than the requested
    ``count`` means the collection is exhausted, so we stop; otherwise the last row's id becomes the
    ``after`` cursor for the next page. A full page whose last row lacks the cursor field can't be
    paginated past, so we stop rather than loop forever on the same cursor. Resumable: the cursor is
    persisted so a crashed sync restarts from the record after the last one yielded.
    """

    def __init__(self, id_field: str, page_size: int) -> None:
        super().__init__()
        self.id_field = id_field
        self.page_size = page_size
        self._after: Optional[str] = None

    def _set_after(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["after"] = self._after

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._after is not None:
            self._set_after(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # A short (or empty) page means we've reached the end of the collection.
        if data is None or len(data) < self.page_size:
            self._has_next_page = False
            return

        next_after = data[-1].get(self.id_field)
        if next_after is None:
            # Without a cursor value we can't request the next page safely — stop rather than loop.
            self._has_next_page = False
            return

        self._after = str(next_after)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._after is not None:
            self._set_after(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"after": self._after} if self._has_next_page and self._after is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after is not None:
            self._after = str(after)
            self._has_next_page = True


def inflowinventory_source(
    api_key: str,
    company_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[InflowInventoryResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = INFLOWINVENTORY_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(company_id),
            "headers": _version_headers(),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": InflowInventoryPaginator(id_field=config.id_field, page_size=PAGE_SIZE),
            # Pin every request (including resume URLs) to the base_url host and reject any redirect
            # so the Bearer key can't be replayed to a cross-host target.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"count": PAGE_SIZE},
                    # inFlow list endpoints return a bare JSON array. A non-list body on a 200 is a
                    # permanent contract violation, not transient — fail loud instead of syncing the
                    # stray object as a single row.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.after is not None:
            initial_paginator_state = {"after": resume.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the last cursor (already-yielded pages are persisted) rather than skipping it — merge
        # dedupes the re-pulled page on the primary key.
        if state and state.get("after") is not None:
            resumable_source_manager.save_state(InflowInventoryResumeConfig(after=str(state["after"])))

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, company_id: str, path: str = "products") -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the credentials.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, ``400`` for a malformed company ID, other HTTP status otherwise.
    """
    if not COMPANY_ID_REGEX.match(company_id):
        return 400, "The inFlow Inventory company ID contains unsupported characters"

    session = _make_session(api_key)
    try:
        response = session.get(f"{base_url(company_id)}/{path}", params={"count": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to inFlow Inventory: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"inFlow Inventory returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, company_id: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key, company_id)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid inFlow Inventory API key"
    return False, message or "Could not validate inFlow Inventory credentials"
