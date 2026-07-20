import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.settings import (
    DING_CONNECT_ENDPOINTS,
    DingConnectEndpointConfig,
)

DING_CONNECT_BASE_URL = "https://api.dingconnect.com"

# ListTransferRecords requires a Take (page size) and bypasses already-returned rows with Skip.
TRANSFER_RECORDS_PAGE_SIZE = 100

# Envelope keys returned alongside the data on every DingConnect response. Stripped from the
# single-object GetBalance response so only the balance fields land in the row.
_ENVELOPE_KEYS = ("ResultCode", "ErrorCodes", "ThereAreMoreItems")


def _non_secret_headers() -> dict[str, str]:
    # The api_key travels via the framework `api_key` auth so its value is redacted from logs and
    # raised error messages; only the non-secret content-negotiation headers are set here.
    return {"Accept": "application/json", "Content-Type": "application/json"}


def _flatten_transfer_record(record: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested TransferId identifiers to the top level so TransferRef is a usable primary key."""
    transfer_id = record.get("TransferId")
    if isinstance(transfer_id, dict):
        record = {**record}
        record["TransferRef"] = transfer_id["TransferRef"]
        record["DistributorRef"] = transfer_id.get("DistributorRef")
    return record


def _row_from_single_object(body: dict[str, Any]) -> dict[str, Any]:
    """Build a single row from an envelope that carries the payload at the top level (GetBalance)."""
    return {key: value for key, value in body.items() if key not in _ENVELOPE_KEYS}


class DingConnectTransferRecordsPaginator(BasePaginator):
    """Skip/Take offset paging carried in the POST body.

    ListTransferRecords paginates via ``{"Skip": n, "Take": page_size}`` in the JSON payload and
    signals continuation with the documented ``ThereAreMoreItems`` flag; when that flag is absent we
    fall back to "a full page implies more". No built-in paginator reads a body-level boolean, so this
    keeps the exact termination the hand-rolled source had while remaining resumable.
    """

    def __init__(self, skip: int = 0) -> None:
        super().__init__()
        self._skip = skip

    def _inject(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["Skip"] = self._skip
        request.json["Take"] = TRANSFER_RECORDS_PAGE_SIZE

    def init_request(self, request: Request) -> None:
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        try:
            body = response.json()
        except Exception:
            body = {}
        there_are_more = body.get("ThereAreMoreItems") if isinstance(body, dict) else None
        # `ThereAreMoreItems` is the documented continuation flag; fall back to a short final page.
        has_next = bool(there_are_more) if there_are_more is not None else len(items) == TRANSFER_RECORDS_PAGE_SIZE
        if not items or not has_next:
            self._has_next_page = False
            return
        self._skip += TRANSFER_RECORDS_PAGE_SIZE
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self._skip already points at the next page to fetch (update_state advanced it).
        return {"skip": self._skip} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        skip = state.get("skip")
        if skip is not None:
            self._skip = int(skip)
            self._has_next_page = True


@dataclasses.dataclass
class DingConnectResumeConfig:
    # Number of TransferRecords rows already returned; the Skip value the next page resumes from.
    # Only the paginated TransferRecords endpoint persists this; reference endpoints complete in a
    # single request and never save state.
    skip: int = 0


def _build_resource(endpoint: str, config: DingConnectEndpointConfig) -> dict[str, Any]:
    endpoint_config: dict[str, Any] = {"path": config.path, "method": config.method}
    resource: dict[str, Any] = {"name": endpoint, "endpoint": endpoint_config}

    if config.paginated:
        # TransferRecords: paged POST; the paginator injects Skip/Take into the JSON body.
        endpoint_config["data_selector"] = config.data_selector
        endpoint_config["paginator"] = DingConnectTransferRecordsPaginator()
        resource["data_map"] = _flatten_transfer_record
    elif config.data_selector == "":
        # GetBalance returns a single object at the top level; wrap it as one row and strip the
        # envelope keys so only the balance fields land.
        endpoint_config["paginator"] = SinglePagePaginator()
        resource["data_map"] = _row_from_single_object
    else:
        # Reference/catalog lookups return their whole bounded list under `Items` in one response.
        endpoint_config["data_selector"] = config.data_selector
        endpoint_config["paginator"] = SinglePagePaginator()

    return resource


def ding_connect_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DingConnectResumeConfig],
) -> SourceResponse:
    config = DING_CONNECT_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": DING_CONNECT_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "api_key", "location": "header"},
        },
        "resources": [_build_resource(endpoint, config)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"skip": resume.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (the full-refresh replace plus the primary key dedupe any re-pulled rows)
        # rather than skipping it. Only the paginated TransferRecords endpoint ever produces state.
        if state and state.get("skip") is not None:
            resumable_source_manager.save_state(DingConnectResumeConfig(skip=int(state["skip"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # full refresh only — no DingConnect endpoint exposes a server-side timestamp filter
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    # GetBalance is the cheapest call that proves both the key is valid and an account is attached.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{DING_CONNECT_BASE_URL}/api/V1/GetBalance",
        headers={"api_key": api_key, **_non_secret_headers()},
    )
    return ok
