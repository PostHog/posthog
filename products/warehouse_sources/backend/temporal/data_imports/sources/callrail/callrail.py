import dataclasses
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.settings import (
    CALLRAIL_ENDPOINTS,
    PER_PAGE,
    CallRailEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ApiKeyAuthConfig,
    ClientConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CALLRAIL_BASE_URL = "https://api.callrail.com/v3"

# Hard cap so a runaway pagination loop (e.g. the API never signaling the last page) can't scan
# forever. 250 rows/page * this cap bounds a single endpoint sync.
MAX_PAGES = 100_000


@dataclasses.dataclass(frozen=True)
class CallRailResumeConfig:
    # The resolved account whose data we're pulling. Pinned across a resume so re-resolution can't
    # silently switch accounts mid-sync (an API key can see more than one account). Empty for
    # /a.json, which is not scoped to an account.
    account_id: str
    # Next 1-indexed page to fetch, for an endpoint listed once per account.
    page: Optional[int] = None
    # Fan-out progress for an endpoint reached once per parent row: which parents are done, which
    # one was in flight, and that parent's page cursor. Shape owned by the shared fan-out helper.
    fanout_state: Optional[dict[str, Any]] = None


def _get_headers(api_key: str) -> dict[str, str]:
    # CallRail expects the token wrapped in token="..." per its v3 docs.
    return {
        "Authorization": f'Token token="{api_key}"',
        "Accept": "application/json",
    }


def _auth_config(api_key: str) -> ApiKeyAuthConfig:
    # Framework auth so the credential value is redacted from logs/samples; the full header value
    # is the secret since CallRail wraps the key in token="...".
    return {
        "type": "api_key",
        "name": "Authorization",
        "api_key": f'Token token="{api_key}"',
        "location": "header",
    }


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": CALLRAIL_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": _auth_config(api_key),
        # Call and lead bodies carry caller names and phone numbers, SMS message text and submitted
        # form field values — free text the name-based sample scrubbers aren't guaranteed to catch.
        # Keep raw bodies out of HTTP sample capture even where an operator enables it. Requests are
        # still metered and logged.
        "capture": False,
    }


def _sort_params(config: CallRailEndpointConfig) -> dict[str, Any]:
    # Ascending on the cursor field so the pipeline watermark advances safely and full-refresh
    # pages don't skip/duplicate rows inserted mid-sync.
    if not config.sort_field:
        return {}
    return {"sort": config.sort_field, "order": "asc"}


def _paginator() -> PageNumberPaginator:
    # `total_pages` in the body is the number of PAGES, so pagination stops after the last page
    # without paying an extra empty-page request.
    return PageNumberPaginator(
        base_page=1,
        page_param="page",
        total_path="total_pages",
        maximum_page=MAX_PAGES,
    )


def _format_start_date(value: Any) -> str | None:
    """Format an incremental cursor value as the YYYY-MM-DD `start_date` the API filters on.

    We deliberately drop the time component: CallRail's date filters are interpreted in the
    account's own timezone, so pinning to the date avoids off-by-one drift at the boundary. We may
    re-fetch the watermark day's rows, but the merge dedupes them on the primary key.
    """
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value[:10]
    return None


def resolve_account_id(api_key: str, team_id: int, job_id: str, account_id: str | None = None) -> str:
    """Return the account id to scope data requests to.

    Most CallRail data endpoints are nested under /v3/a/{account_id}/, so we must resolve one
    first. If the user supplied one we trust it; otherwise we use the first account the key sees.
    """
    if account_id:
        return account_id

    # We only ever read the first account, so request a single row like validate_credentials does.
    accounts_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": "accounts",
                "endpoint": {
                    "path": "/a.json",
                    "params": {"per_page": 1},
                    "data_selector": "accounts",
                    "paginator": SinglePagePaginator(),
                },
            }
        ],
    }
    for page in rest_api_resource(accounts_config, team_id, job_id, None):
        for account in page:
            return str(account["id"])
    raise ValueError("No CallRail accounts are accessible with this API key.")


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine by hitting the accounts endpoint."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CALLRAIL_BASE_URL}/a.json?per_page=1",
        headers=_get_headers(api_key),
    )
    return ok


def _fanout_rows(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CallRailResumeConfig],
    resolved_account_id: str,
    initial_fanout_state: Optional[dict[str, Any]],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterable[list[dict[str, Any]]]:
    """Walk a parent listing and pull the child resource once per parent row.

    Neither child resource exposes a server-side date filter, so the request set is bounded by the
    parent listing rather than by a time window. The child still merges on its primary key, which
    is what keeps rows that fall outside a single run's parent window.
    """
    config = CALLRAIL_ENDPOINTS[endpoint]
    assert config.fanout is not None
    parent_config = CALLRAIL_ENDPOINTS[config.fanout.parent_name]

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                CallRailResumeConfig(account_id=resolved_account_id, fanout_state=state)
            )

    return cast(
        Iterable[list[dict[str, Any]]],
        build_dependent_resource(
            endpoint_configs=CALLRAIL_ENDPOINTS,
            child_endpoint=endpoint,
            # The parent's sort comes from its own endpoint config rather than being repeated here,
            # so the two cannot drift.
            fanout=dataclasses.replace(config.fanout, parent_params=_sort_params(parent_config)),
            client_config=_client_config(api_key),
            path_format_values={"account_id": resolved_account_id},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            # No server-side date filter on either child, so there is no request window to build.
            incremental_config_factory=lambda _cursor_path: None,
            page_size_param="per_page",
            child_params_extra=_sort_params(config),
            parent_endpoint_extra={"paginator": _paginator(), "data_selector": parent_config.response_key},
            child_endpoint_extra={"paginator": _paginator(), "data_selector": config.response_key},
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=initial_fanout_state,
        ),
    )


def get_rows(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CallRailResumeConfig],
    account_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CALLRAIL_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        resolved_account_id = resume.account_id
    elif config.requires_account:
        resolved_account_id = resolve_account_id(api_key, team_id, job_id, account_id)
    else:
        resolved_account_id = ""

    if config.fanout is not None:
        yield from _fanout_rows(
            api_key=api_key,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            resumable_source_manager=resumable_source_manager,
            resolved_account_id=resolved_account_id,
            initial_fanout_state=resume.fanout_state if resume is not None else None,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
        return

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.page is not None:
        initial_paginator_state = {"page": resume.page}

    endpoint_config: Endpoint = {
        "path": config.path.replace("{account_id}", resolved_account_id),
        "params": {"per_page": PER_PAGE, **_sort_params(config)},
        # Key the list lives under in the JSON envelope; a missing key reads as an empty page and
        # ends pagination, matching the API's "no more data" signal.
        "data_selector": config.response_key,
        "paginator": _paginator(),
    }
    if config.supports_incremental and should_use_incremental_field:
        endpoint_config["incremental"] = {
            "start_param": "start_date",
            "cursor_path": cast("str", config.sort_field),
            "convert": _format_start_date,
        }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework calls this AFTER a page is yielded
        # so a crash re-pulls from the next page rather than losing the page we just handed off;
        # the merge dedupes any overlap on the primary key.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(
                CallRailResumeConfig(account_id=resolved_account_id, page=int(state["page"]))
            )

    yield from rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def callrail_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CallRailResumeConfig],
    account_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CALLRAIL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        # Lazy so account resolution (a network call) happens at iteration time, not when the
        # SourceResponse is built.
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            resumable_source_manager=resumable_source_manager,
            account_id=account_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
