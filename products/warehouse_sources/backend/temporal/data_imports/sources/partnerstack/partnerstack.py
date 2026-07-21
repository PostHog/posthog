import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.settings import (
    PARTNERSTACK_ENDPOINTS,
)

PARTNERSTACK_BASE_URL = "https://api.partnerstack.com/api/v2"
# The Vendor API caps `limit` at 250; the largest page minimises round trips.
PAGE_SIZE = 250
# Cursor pagination keys on each object's `key`, which is also the primary key of every object.
CURSOR_FIELD = "key"
STARTING_AFTER_PARAM = "starting_after"
# Cheap endpoint used to confirm the key pair is genuine. The credentials are account-wide, so one
# probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/partnerships"


@dataclasses.dataclass
class PartnerStackResumeConfig:
    # The `key` of the last object yielded. On resume the next request passes it as `starting_after`,
    # so a crashed full-refresh sync continues after the last object persisted; merge dedupes on `key`.
    starting_after: str | None = None


class PartnerStackPaginator(BasePaginator):
    """Cursor pagination for the Vendor API: the next page is requested with ``starting_after`` set to
    the ``key`` of the last object on the current page, and the API signals continuation with
    ``data.has_more``. Pagination stops on an empty page, a cleared ``has_more`` flag, or a last object
    without a ``key`` (we can't advance safely). Malformed 200-body shapes never reach here — the
    endpoint's ``data_selector_malformed_retryable`` reissues those before ``update_state`` runs.
    """

    def __init__(self) -> None:
        super().__init__()
        self._starting_after: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._starting_after is not None:
            if request.params is None:
                request.params = {}
            request.params[STARTING_AFTER_PARAM] = self._starting_after

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._starting_after = None

        body = response.json()
        has_more = (
            isinstance(body, dict) and isinstance(body.get("data"), dict) and bool(body["data"].get("has_more", False))
        )

        # An empty page or a cleared `has_more` flag means we've reached the end of the collection.
        if not data or not has_more:
            self._has_next_page = False
            return

        last = data[-1]
        cursor = last.get(CURSOR_FIELD) if isinstance(last, dict) else None
        # Without a cursor from the last object we cannot advance safely, so stop.
        if cursor is None:
            self._has_next_page = False
            return

        self._starting_after = cursor
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[STARTING_AFTER_PARAM] = self._starting_after

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._starting_after is not None:
            return {"starting_after": self._starting_after}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        starting_after = state.get("starting_after")
        if starting_after is not None:
            self._starting_after = str(starting_after)
            self._has_next_page = True


def partnerstack_source(
    public_key: str,
    private_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PartnerStackResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PARTNERSTACK_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PARTNERSTACK_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Basic auth over the public/private key pair; the framework redacts the secret from logs.
            "auth": {"type": "http_basic", "username": public_key, "password": private_key},
            "paginator": PartnerStackPaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data.items",
                    # A 200 whose body isn't the expected `{"data": {"items": [...]}}` envelope is
                    # treated as transient and reissued, matching the hand-rolled source's retry.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.starting_after is not None:
            initial_paginator_state = {"starting_after": resume.starting_after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("starting_after") is not None:
            resumable_source_manager.save_state(PartnerStackResumeConfig(starting_after=str(state["starting_after"])))

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
        column_hints=resource.column_hints,
    )


def validate_credentials(public_key: str, private_key: str) -> tuple[bool, str | None]:
    # The key pair is account-wide, so a single probe validates access to every list endpoint.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(public_key, private_key)),
        f"{PARTNERSTACK_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        auth=HttpBasicAuth(username=public_key, password=private_key),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid PartnerStack API keys"
    if status is None:
        return False, "Could not validate PartnerStack API keys"
    return False, f"PartnerStack returned HTTP {status}"
