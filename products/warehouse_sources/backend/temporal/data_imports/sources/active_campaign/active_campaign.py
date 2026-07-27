import dataclasses
from typing import Any, Optional

from posthog.security.url_validation import is_url_allowed

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.settings import (
    ACTIVE_CAMPAIGN_ENDPOINTS,
)
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

# ActiveCampaign caps `limit` at 100 records per page across all list endpoints.
PAGE_SIZE = 100


@dataclasses.dataclass
class ActiveCampaignResumeConfig:
    offset: int


def _normalize_base_url(api_url: str) -> str:
    """Return the account base URL without a trailing slash or `/api/3` suffix.

    Users copy the URL straight from their ActiveCampaign developer settings, which
    is the bare account host (e.g. https://youraccount.api-us1.com). We tolerate a
    trailing slash or an accidentally-pasted `/api/3` and re-append the version path
    ourselves so the configured base is always consistent.
    """
    url = api_url.strip().rstrip("/")
    if url.endswith("/api/3"):
        url = url[: -len("/api/3")]
    return url


class ActiveCampaignPaginator(OffsetPaginator):
    """Offset/limit paginator with resume support.

    ActiveCampaign returns `meta.total` (sometimes as a string), so we lean on the
    base class's empty-/short-page detection as the reliable stop condition and use
    the total as an early-exit optimization when it parses as an int.
    """

    def __init__(self) -> None:
        super().__init__(limit=PAGE_SIZE, total_path="meta.total")

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"offset": self.offset}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True


def get_resource(endpoint: str) -> EndpointResource:
    config = ACTIVE_CAMPAIGN_ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
            "params": dict(config.extra_params),
        },
        "table_format": "delta",
    }


def active_campaign_source(
    api_url: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ActiveCampaignResumeConfig],
) -> SourceResponse:
    endpoint_config = ACTIVE_CAMPAIGN_ENDPOINTS[endpoint]

    # Re-validate on every sync, not just at source creation: the stored api_url is
    # user-supplied. The Smokescreen egress proxy is the load-bearing SSRF defense;
    # this app-layer check is defense-in-depth that fails fast with a clear error
    # before the request leaves the worker.
    base_url = _normalize_base_url(api_url)
    allowed, reason = is_url_allowed(base_url)
    if not allowed:
        raise ValueError(f"ActiveCampaign API URL is not allowed: {reason}")

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{base_url}/api/3",
            # ActiveCampaign authenticates via the account-wide `Api-Token` header.
            # Going through APIKeyAuth (rather than raw headers) registers the key
            # for value-based log redaction.
            "auth": {
                "type": "api_key",
                "api_key": api_key,
                "name": "Api-Token",
                "location": "header",
            },
            "paginator": ActiveCampaignPaginator(),
            # Disable redirects as defense-in-depth: the Smokescreen egress proxy
            # already blocks redirects onto internal hosts, but ActiveCampaign's API
            # responds directly so there's no legitimate redirect to follow, and
            # pinning it off keeps traffic on the validated host.
            "session": make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to; the Redis TTL handles
        # cleanup once the sync finishes. Saving happens after each page is yielded,
        # so a crash re-fetches the last page rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(ActiveCampaignResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode="asc",
    )


def validate_credentials(api_url: str, api_key: str) -> tuple[bool, str | None]:
    base_url = _normalize_base_url(api_url)
    if not base_url.startswith("https://"):
        return False, "ActiveCampaign API URL must start with https://"

    # Defense-in-depth SSRF check (the Smokescreen egress proxy is the load-bearing
    # control): reject localhost, cloud-metadata hosts, internal domains, and private
    # IPs with a clear error before issuing any request to the user-supplied host.
    allowed, reason = is_url_allowed(base_url)
    if not allowed:
        return False, f"ActiveCampaign API URL is not allowed: {reason}"

    try:
        # `allow_redirects=False` as defense-in-depth — Smokescreen already blocks
        # redirects onto internal hosts, and ActiveCampaign's API responds directly,
        # so no redirect is expected for a valid account.
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{base_url}/api/3/contacts",
            params={"limit": 1},
            headers={"Api-Token": api_key},
            timeout=10,
            allow_redirects=False,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid ActiveCampaign API URL or key"
    # A redirect from a valid account+key is never expected (the API answers directly).
    # It almost always means the account name in the URL is wrong, so the host doesn't
    # resolve to an API tenant and ActiveCampaign bounces the request to a login page.
    if response.is_redirect:
        return (
            False,
            "ActiveCampaign redirected the request, which usually means the account name in the API URL is "
            "incorrect. Check that your API URL looks like https://<youraccountname>.api-us1.com",
        )
    return False, f"ActiveCampaign returned an unexpected status code: {response.status_code}"
