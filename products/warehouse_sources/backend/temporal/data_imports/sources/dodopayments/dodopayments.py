import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.settings import (
    DODOPAYMENTS_ENDPOINTS,
    MODE_HOSTS,
    PAGE_SIZE,
    REQUEST_TIMEOUT_SECONDS,
)


@dataclasses.dataclass
class DodoPaymentsResumeConfig:
    page_number: int


def base_url_for_mode(mode: str) -> str:
    """Resolve the API host for a mode, defaulting to live for an unrecognised value."""
    return MODE_HOSTS.get(mode, MODE_HOSTS["live"])


def to_iso8601(value: Any) -> Optional[str]:
    """Render an incremental watermark as the UTC ISO-8601 string the date filters expect.

    The stored watermark comes back as a datetime for `DateTime` incremental fields, but a
    reset or a hand-edited config can leave a string or an epoch number, so all three are
    accepted. Anything unparseable yields `None`, which drops the filter and full-refreshes
    rather than sending a value the API would reject.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        parsed = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, int | float):
        try:
            parsed = datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        try:
            candidate = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        parsed = candidate.replace(tzinfo=UTC) if candidate.tzinfo is None else candidate.astimezone(UTC)
    else:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


class DodoPaymentsPaginator(PageNumberPaginator):
    """Zero-based `page_number` pagination that stops on the first short page.

    Dodo Payments list responses are a bare `{"items": [...]}` with no total count, no next
    cursor and no Link header, so the only termination signal is a page holding fewer than
    `page_size` rows. Falling back to the base class's empty-page check would cost one extra
    request per table per sync against a 240 requests/minute budget.
    """

    def __init__(self, page_size: int = PAGE_SIZE, page: Optional[int] = None) -> None:
        super().__init__(base_page=0, page=page, page_param="page_number")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is not None and len(data) < self._page_size:
            self._has_next_page = False
            return
        super().update_state(response, data)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page_number": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page_number = state.get("page_number")
        if page_number is not None:
            self.page = int(page_number)
            self._has_next_page = True


def get_resource(
    endpoint: str, should_use_incremental_field: bool, incremental_start_value: Optional[str]
) -> EndpointResource:
    config = DODOPAYMENTS_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.paginated:
        params["page_size"] = PAGE_SIZE
    if should_use_incremental_field and config.start_param and incremental_start_value:
        params[config.start_param] = incremental_start_value

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "table_format": "delta",
        "primary_key": config.primary_keys,
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": "items",
            "paginator": DodoPaymentsPaginator() if config.paginated else "single_page",
            # Every list endpoint wraps its rows in `items`; a body without it is a response
            # shape change, which should fail loud rather than sync zero rows.
            "data_selector_required": True,
            "data_selector_empty_ok": True,
        },
    }


def dodopayments_source(
    api_key: str,
    mode: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DodoPaymentsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DODOPAYMENTS_ENDPOINTS[endpoint]
    incremental_start_value = to_iso8601(db_incremental_field_last_value) if should_use_incremental_field else None
    resource = get_resource(endpoint, should_use_incremental_field, incremental_start_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url_for_mode(mode),
            "auth": {"type": "bearer", "token": api_key},
            # capture=False: list responses carry customer PII, invoice URLs and redeemable
            # `license_keys.key` values that the name-based scrubbers would not recognise, so keep
            # raw bodies out of HTTP sample capture even where an operator enables it.
            "session": make_tracked_session(capture=False, redact_values=(api_key,)),
            # Every request is built from our own base URL, so pin it and refuse redirects rather
            # than letting a redirect replay the bearer token at another origin.
            "allowed_hosts": [],
            "allow_redirects": False,
            # Bound every request so a stalled connect or a hung read can't hold this worker forever.
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
        },
        "resources": [resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page_number": resume.page_number}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Fires after a page has been yielded, so a crash re-yields that page (the merge dedupes
        # on the primary key) instead of skipping it.
        if state and state.get("page_number") is not None:
            resumable_source_manager.save_state(DodoPaymentsResumeConfig(page_number=int(state["page_number"])))

    resource_iter = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # The date filter is already baked into the request params above, so the framework's own
        # incremental param injection is intentionally unused.
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: resource_iter,
        primary_keys=config.primary_keys,
        # Dodo Payments documents no ordering guarantee and offers no sort parameter, so we
        # cannot claim rows arrive oldest-first. "desc" holds the watermark back until the sync
        # finishes, which is correct whichever order the API actually returns.
        sort_mode="desc",
        **partition_kwargs,
    )


def validate_credentials(api_key: str, mode: str) -> tuple[bool, int | None]:
    """Probe the cheapest authenticated list endpoint and report `(is_valid, status_code)`."""
    return validate_via_probe(
        lambda: make_tracked_session(capture=False, allow_redirects=False, redact_values=(api_key,)),
        f"{base_url_for_mode(mode)}/customers?page_size=1",
        headers={"Authorization": f"Bearer {api_key}"},
        allow_redirects=False,
    )
