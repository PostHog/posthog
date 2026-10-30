import datetime
import dataclasses
from collections.abc import Iterable
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.settings import HARVEST_ENDPOINTS

# Harvest serves every account from one global host - there are no regional or per-tenant
# subdomains, so the account is identified by the Harvest-Account-Id header instead.
HARVEST_API_HOST = "api.harvestapp.com"
HARVEST_BASE_URL = f"https://{HARVEST_API_HOST}"

# Harvest rejects requests without a descriptive User-Agent with a 400.
HARVEST_USER_AGENT = "PostHog (https://posthog.com)"

# Connect/read timeout per request, so a stalled response can't hold an import worker forever.
REQUEST_TIMEOUT = (10.0, 60.0)


@dataclasses.dataclass(frozen=True)
class HarvestResumeConfig:
    # Absolute URL of the next page, taken from the response's `links.next`. Harvest's own
    # docs tell integrators to follow that link rather than rebuild page/cursor params, since
    # it picks whichever pagination style is cheapest for the endpoint.
    next_url: Optional[str] = None
    # Per-parent sub-resources (invoice payments, user cost rates) checkpoint the shape
    # `build_dependent_resource` emits: which parents finished and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _to_iso8601(value: Any) -> Optional[str]:
    """Render an incremental watermark as the ISO 8601 string `updated_since` expects.

    The pipeline hands back whatever the Delta table stored for the cursor column, which for a
    DateTime incremental field is a `datetime` but may arrive as an already-formatted string.
    `None` (a first sync) stays `None` so `requests` drops the param entirely.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        # A naive watermark can't be shifted with astimezone(); treat it as UTC, like the
        # other sources do, so incremental sync never crashes on a tz-less stored cursor.
        utc = value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _build_headers(account_id: str) -> dict[str, str]:
    # The access token rides the framework's bearer auth so its value is redacted from logs;
    # only the non-secret identification headers are set here. A token can reach several
    # Harvest accounts, so the account id header is mandatory on every request.
    return {
        "Harvest-Account-Id": account_id,
        "User-Agent": HARVEST_USER_AGENT,
        "Accept": "application/json",
    }


def _build_params(endpoint: str, should_use_incremental_field: bool) -> dict[str, Any]:
    config = HARVEST_ENDPOINTS[endpoint]
    params: dict[str, Any] = {"per_page": config.page_size}
    if should_use_incremental_field and config.supports_updated_since:
        params["updated_since"] = {
            "type": "incremental",
            "cursor_path": "updated_at",
            "convert": _to_iso8601,
        }
    return params


def _client_config(account_id: str, access_token: str, api_version: str) -> ClientConfig:
    return {
        "base_url": f"{HARVEST_BASE_URL}/{api_version}",
        "headers": _build_headers(account_id),
        "auth": {"type": "bearer", "token": access_token},
        # Harvest returns a self-contained absolute next-page URL, which already carries
        # `per_page` and `updated_since`, so the filter survives every page.
        "paginator": JSONResponsePaginator(next_url_path="links.next"),
        # Pagination and resume follow URLs supplied by the response body, so pin them to
        # the API host and refuse redirects - a tampered link must not carry the bearer
        # token somewhere else.
        "allowed_hosts": [HARVEST_API_HOST],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT,
    }


def _updated_since(cursor_path: str) -> IncrementalConfig:
    return {"cursor_path": cursor_path, "start_param": "updated_since", "convert": _to_iso8601}


def _fanout_source(
    endpoint: str,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HarvestResumeConfig],
    use_incremental: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = HARVEST_ENDPOINTS[endpoint]
    assert config.fanout is not None
    parent_config = HARVEST_ENDPOINTS[config.fanout.parent_name]

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(HarvestResumeConfig(fanout_state=state))

    # The parent listing always walks the full collection: a child can change without its
    # parent's `updated_at` moving, so the child's own `updated_since` does the narrowing.
    child = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=HARVEST_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value if use_incremental else None,
            should_use_incremental_field=use_incremental,
            incremental_field="updated_at",
            incremental_config_factory=_updated_since,
            page_size_param="per_page",
            parent_endpoint_extra={"data_selector": parent_config.data_key, "data_selector_required": True},
            child_endpoint_extra={"data_selector": config.data_key, "data_selector_required": True},
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: child,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Rows arrive one parent at a time, so they are not one ordered series.
        sort_mode=None,
    )


def harvest_source(
    account_id: str,
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HarvestResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HARVEST_ENDPOINTS[endpoint]
    use_incremental = should_use_incremental_field and config.supports_updated_since
    client_config = _client_config(account_id, access_token, api_version)

    if config.fanout is not None:
        return _fanout_source(
            endpoint,
            client_config,
            team_id,
            job_id,
            resumable_source_manager,
            use_incremental,
            db_incremental_field_last_value,
        )

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": config.data_key,
                    # A missing envelope key means the response shape changed; fail loud
                    # rather than silently syncing zero rows.
                    "data_selector_required": True,
                    "params": _build_params(endpoint, should_use_incremental_field),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; saved AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(HarvestResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_incremental else None,
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
        # Harvest orders list responses by a domain date (spent_date, creation date), newest
        # first, and offers no sort parameter - so rows never arrive ordered by `updated_at`.
        # "desc" keeps the pipeline from checkpointing the watermark mid-sync, which would
        # skip rows an interrupted run had not reached yet.
        sort_mode="desc",
    )


def validate_credentials(account_id: str, access_token: str, api_version: str) -> tuple[bool, Optional[int]]:
    """Probe the authenticated-user endpoint to confirm the token and account id are genuine.

    `/users/me` is readable by every Harvest role, so it validates the credential without
    also requiring the admin access that listing users needs.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{HARVEST_BASE_URL}/{api_version}/users/me",
        headers={"Authorization": f"Bearer {access_token}", **_build_headers(account_id)},
        timeout=REQUEST_TIMEOUT[0],
        allow_redirects=False,
    )
