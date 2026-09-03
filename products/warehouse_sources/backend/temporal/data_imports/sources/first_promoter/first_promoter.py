import logging
import dataclasses
from collections.abc import Callable, Iterable
from functools import partial
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.settings import (
    DEFAULT_PAGE_SIZE,
    FIRST_PROMOTER_ENDPOINTS,
    FirstPromoterEndpointConfig,
    base_url,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class FirstPromoterResumeConfig:
    page: int


def _format_filter_date(value: Any) -> str:
    """Format the incremental watermark for a `filters[<field>][from]` bound.

    The Admin API documents these bounds as `YYYY-MM-DD` dates, so the watermark is truncated to
    its day. That rounds the lower bound *down*, re-fetching at most one day of rows (which the
    merge dedupes on `id`) rather than skipping any.
    """
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%d")


def _incremental_window(start_param: str, cursor_path: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor_path,
        "start_param": start_param,
        "initial_value": "1970-01-01",
        "convert": _format_filter_date,
    }


def _page_signature(data: Optional[list[Any]]) -> Optional[tuple[Any, ...]]:
    """Identity of a page's rows, or None when the rows carry no usable id."""
    if not data:
        return None
    ids = []
    for row in data:
        if not isinstance(row, dict) or row.get("id") is None:
            return None
        ids.append(row["id"])
    return tuple(ids)


class FirstPromoterPaginator(PageNumberPaginator):
    """`page`/`per_page` paginator with the two stop conditions the plain page paginator lacks.

    FirstPromoter documents `page`/`per_page` once, globally, rather than per endpoint, and its
    list responses carry no page-count metadata. So this stops on the vendor's documented
    end-of-data signal (a page shorter than `per_page`) and, as a backstop, on a page whose rows
    repeat the previous page's - which is what an endpoint that quietly ignores `page` would
    return forever.
    """

    def __init__(self, per_page: int = DEFAULT_PAGE_SIZE) -> None:
        super().__init__(base_page=1, page_param="page")
        self.per_page = per_page
        self._previous_signature: Optional[tuple[Any, ...]] = None

    def _apply_page_size(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["per_page"] = self.per_page

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        self._apply_page_size(request)

    def update_request(self, request: Request) -> None:
        super().update_request(request)
        self._apply_page_size(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        signature = _page_signature(data)
        repeats_previous_page = signature is not None and signature == self._previous_signature
        self._previous_signature = signature

        # Handles the empty-page case and advances self.page.
        super().update_state(response, data)
        if not self._has_next_page:
            return

        if data is not None and len(data) < self.per_page:
            self._has_next_page = False
            return

        if repeats_previous_page:
            logger.warning(
                "FirstPromoter returned an identical page twice; stopping pagination "
                "(the endpoint may not support the `page` parameter)"
            )
            self._has_next_page = False


def _drop_fields(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Strip `fields` from a row before storage. Mutates and returns `row` so it can be used
    directly as a `data_map`."""
    for field in fields:
        row.pop(field, None)
    return row


def rest_api_client_config(api_key: str, account_id: str, api_version: str) -> ClientConfig:
    return {
        "base_url": base_url(api_version),
        "auth": {"type": "bearer", "token": api_key},
        # The account id header is mandatory on every Admin API call - without it the API key
        # alone fails auth.
        "headers": {"ACCOUNT-ID": account_id, "Accept": "application/json"},
        # Pin every request to the FirstPromoter host and refuse to follow a 3xx, so a
        # server-side redirect can never replay the bearer token off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
        # Promoter rows carry the `password_setup_url` credential plus PII (emails, names, tax-form
        # URLs) that the name-based sample scrubbers don't recognise. Sample capture observes the
        # raw body before `data_map` strips the credential, so keep these bodies out of shared HTTP
        # sample storage entirely. Requests stay metered and logged with the API key redacted.
        "session": make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False),
    }


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field_name: str | None = None,
) -> EndpointResource:
    config = FIRST_PROMOTER_ENDPOINTS[endpoint]

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": dict(config.extra_params),
        "paginator": FirstPromoterPaginator(),
        # Fail loud if the response shape changes, rather than silently syncing 0 rows.
        "data_selector_required": True,
    }
    if config.data_selector:
        endpoint_config["data_selector"] = config.data_selector

    use_incremental = (
        should_use_incremental_field and bool(config.incremental_fields) and config.incremental_start_param is not None
    )
    if use_incremental and config.incremental_start_param is not None:
        endpoint_config["incremental"] = _incremental_window(
            config.incremental_start_param,
            incremental_field_name or config.default_incremental_field or "created_at",
        )

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }
    if config.redact_fields:
        # Strip credential fields (e.g. `password_setup_url`) from each row before it's persisted.
        resource["data_map"] = partial(_drop_fields, fields=config.redact_fields)
    return resource


def _make_source_response(
    endpoint_config: FirstPromoterEndpointConfig,
    items_fn: Callable[[], Iterable[Any]],
) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key,
        # Every incremental endpoint is requested with an explicit ascending sort on its cursor.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def first_promoter_source(
    api_key: str,
    account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: Optional[ResumableSourceManager[FirstPromoterResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = FIRST_PROMOTER_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": rest_api_client_config(api_key, account_id, api_version),
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    if resumable_source_manager is not None:
        if resumable_source_manager.can_resume():
            resume_config = resumable_source_manager.load_state()
            if resume_config is not None:
                initial_paginator_state = {"page": resume_config.page}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only while there is another page to resume to; the Redis TTL cleans up on
            # completion.
            if resumable_source_manager is None or not state or state.get("page") is None:
                return
            resumable_source_manager.save_state(FirstPromoterResumeConfig(page=int(state["page"])))

        resume_hook = save_checkpoint

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)


def validate_credentials(api_key: str, account_id: str, api_version: str) -> tuple[bool, str | None]:
    # capture=False: the probe hits `/promoters`, whose rows carry the `password_setup_url`
    # credential and promoter PII; keep the response body out of shared HTTP sample storage.
    response = make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False).get(
        f"{base_url(api_version)}/promoters",
        headers={"Authorization": f"Bearer {api_key}", "ACCOUNT-ID": account_id, "Accept": "application/json"},
        params={"per_page": 1},
        timeout=10,
    )
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return (
            False,
            "FirstPromoter rejected these credentials. Check the API key and account ID under "
            "Settings > Integrations > Manage API keys.",
        )
    # The key was accepted (else 401/403), so a 404 on the fixed v2 path means the account id
    # doesn't resolve to a company — point the user at the account id rather than a raw status.
    if response.status_code == 404:
        return (
            False,
            "FirstPromoter couldn't find an account for that account ID. Check the account ID "
            "under Settings > Integrations > Manage API keys, then try again.",
        )
    return False, f"FirstPromoter API returned an unexpected status code: {response.status_code}"
