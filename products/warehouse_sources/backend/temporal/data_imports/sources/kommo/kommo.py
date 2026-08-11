import re
import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.settings import (
    ENDPOINT_CONFIG,
    PAGE_LIMIT,
    KommoEndpoint,
)

# Kommo is a per-account host, so bound every request rather than letting a stalled account
# hold an import worker open indefinitely.
REQUEST_TIMEOUT = (10.0, 60.0)

KOMMO_DOMAIN = "kommo.com"

# A single DNS label: Kommo accounts live at https://<subdomain>.kommo.com.
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclasses.dataclass
class KommoResumeConfig:
    page: int


def normalize_subdomain(raw: str) -> str | None:
    """Reduce whatever the user pasted to the bare account label, or None when it isn't one.

    Accepts `mycompany`, `mycompany.kommo.com`, and `https://mycompany.kommo.com/`. Anything
    else (an amocrm.ru host, a path, an IP) is rejected rather than guessed at, because the
    value picks the host the access token is sent to.
    """
    value = (raw or "").strip().lower()
    value = value.removeprefix("https://").removeprefix("http://")
    value = value.split("/")[0].split("?")[0]
    value = value.removesuffix(f".{KOMMO_DOMAIN}")
    if not _SUBDOMAIN_RE.match(value):
        return None
    return value


def account_host(subdomain: str) -> str:
    return f"{subdomain}.{KOMMO_DOMAIN}"


def _build_paginator(endpoint: KommoEndpoint) -> BasePaginator:
    if not endpoint.paginated:
        return SinglePagePaginator()
    # Kommo pages are 1-indexed and answer 204 No Content once you page past the end; the REST
    # client turns that empty body into an empty page, which stops the paginator. `_page_count`
    # is present on most envelopes and saves that extra request when it is.
    return PageNumberPaginator(base_page=1, page_param="page", total_path="_page_count")


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    endpoint = ENDPOINT_CONFIG[name]

    params: dict[str, Any] = dict(endpoint.params)
    if endpoint.paginated:
        params["limit"] = PAGE_LIMIT

    incremental_param = endpoint.incremental_param if should_use_incremental_field else None
    if incremental_param is not None:
        params[incremental_param] = {
            "type": "incremental",
            "cursor_path": "updated_at",
            "initial_value": 0,
        }

    return {
        "name": name,
        "table_name": name.lower(),
        "primary_key": endpoint.primary_key,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if incremental_param is not None
        else "replace",
        "endpoint": {
            "path": endpoint.path,
            "data_selector": endpoint.data_selector,
            "params": params,
            "paginator": _build_paginator(endpoint),
        },
        "table_format": "delta",
    }


def kommo_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KommoResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> Resource:
    host = account_host(subdomain)
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{host}",
            "auth": {"type": "bearer", "token": api_key},
            "allowed_hosts": [host],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    # A page number is only a safe resume point on a full-refresh run. Incremental runs advance
    # `filter[updated_at][from]` after every batch, so page N of the resumed query is not page N
    # of the interrupted one and resuming by page would skip rows. There the watermark is the
    # resume point: restarting at page 1 with the advanced filter picks up where we stopped,
    # because rows arrive ordered by `updated_at` ascending.
    resume_enabled = not should_use_incremental_field

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume_enabled and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist while there's a next page to come back to; the Redis TTL cleans up.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(KommoResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if resume_enabled else None,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str, subdomain: str) -> tuple[bool, str | None]:
    """Probe the token itself with the cheapest endpoint every Kommo user can reach."""
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    response = session.get(
        f"https://{account_host(subdomain)}/api/v4/account",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Kommo rejected the access token. Check the token and the account subdomain."
    if response.status_code == 403:
        return False, (
            "This Kommo token cannot access the account. Check the integration's scopes and the "
            "token owner's user rights."
        )
    if response.status_code == 402:
        return False, "This Kommo account is not paid up, so the API is unavailable."
    if response.status_code == 404:
        return False, f"No Kommo account found at {account_host(subdomain)}."
    return False, f"Kommo returned an unexpected {response.status_code} response."
