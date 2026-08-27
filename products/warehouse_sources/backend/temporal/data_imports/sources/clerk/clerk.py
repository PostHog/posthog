import functools
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

from requests import Request, Response
from requests.exceptions import HTTPError, RequestException
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.settings import (
    CLERK_ENDPOINTS,
    RETIRED_ENDPOINTS,
    ClerkEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


@dataclasses.dataclass
class ClerkResumeConfig:
    """Resume state for Clerk endpoints.

    Flat endpoints use offset-based pagination, so the checkpoint is just the next offset to
    fetch. Fan-out endpoints checkpoint per parent instead, and store the framework's own
    dependent-resource state under ``fan_out``. On resume we start fetching from the saved
    position (at-least-once semantics): any duplicates from a batch that was yielded but whose
    checkpoint did not persist are deduped by the ``id`` primary key.
    """

    offset: int = 0
    fan_out: Optional[dict[str, Any]] = None


def _resource(name: str, config: ClerkEndpointConfig, path: str, params: dict[str, Any]) -> EndpointResource:
    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        # A fan-out's parent and child paginate different response shapes, so each resource
        # carries its own paginator rather than sharing one at the client level.
        "paginator": ClerkPaginator(limit=config.page_size, data_key=config.data_key),
    }

    # Only set data_selector for endpoints that return wrapped responses {data: [...], total_count: ...}
    if config.is_wrapped_response:
        endpoint_config["data_selector"] = config.data_key

    return {
        "name": name,
        "table_name": name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def get_resources(name: str) -> list[EndpointResource]:
    """Resources needed to sync `name` — the endpoint itself, preceded by its parent when it fans out."""
    config = CLERK_ENDPOINTS[name]
    fan_out = config.fan_out

    if fan_out is None:
        return [_resource(name, config, config.path, {"limit": config.page_size})]

    parent_config = CLERK_ENDPOINTS[fan_out.parent]
    child_params: dict[str, Any] = {
        fan_out.query_param: {"type": "resolve", "resource": fan_out.parent, "field": fan_out.parent_field},
        "limit": config.page_size,
    }
    return [
        _resource(fan_out.parent, parent_config, parent_config.path, {"limit": parent_config.page_size}),
        _resource(name, config, f"{config.path}?{fan_out.query_param}={{{fan_out.query_param}}}", child_params),
    ]


class ClerkPaginator(BasePaginator):
    """Paginator for Clerk API using offset-based pagination."""

    def __init__(self, limit: int = 100, data_key: str = "data") -> None:
        super().__init__()
        self._limit = limit
        self._offset = 0
        self._data_key = data_key

    def init_request(self, request: Request) -> None:
        # Emit the seeded offset on the first request so resume starts from the
        # saved page. Fresh runs (offset=0) omit the param to preserve the
        # existing URL shape.
        if self._offset > 0:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._offset

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        # A successful response with an empty body means there are no more rows.
        # rest_client already treats this as an empty page (body=None); mirror
        # that here instead of re-parsing and raising JSONDecodeError.
        if not response.content or not response.content.strip():
            self._has_next_page = False
            return

        res = response.json()

        if not res:
            self._has_next_page = False
            return

        # Clerk endpoints return either:
        # - Direct array: /users, /invitations
        # - Wrapped object {data: [...], total_count: ...}: /organizations, /organization_memberships
        #   (/m2m_tokens wraps under `m2m_tokens` instead of `data`)
        total_count: Optional[int] = None
        if isinstance(res, dict) and self._data_key in res:
            items = res[self._data_key]
            raw_total = res.get("total_count")
            if isinstance(raw_total, int):
                total_count = raw_total
        elif isinstance(res, list):
            items = res
        else:
            items = []

        next_offset = self._offset + len(items)

        # Prefer total_count for wrapped endpoints so we don't issue an extra
        # empty request when total_count is exactly divisible by limit.
        if total_count is not None:
            self._has_next_page = next_offset < total_count
        else:
            self._has_next_page = len(items) >= self._limit

        if self._has_next_page:
            self._offset = next_offset

    def update_request(self, request: Request) -> None:
        if self._has_next_page:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._offset

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # rest_client only calls this when has_next_page is True, so ``_offset``
        # already points at the page we still need to fetch.
        return {"offset": self._offset}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self._offset = int(offset)
            self._has_next_page = True


# Timestamp fields that need conversion from milliseconds to seconds
TIMESTAMP_FIELDS = [
    "created_at",
    "updated_at",
    "last_sign_in_at",
    "last_active_at",
    "mfa_enabled_at",
    "mfa_disabled_at",
    "password_last_updated_at",
    "legal_accepted_at",
    "expires_at",  # invitations
    "expire_at",  # sessions
    "abandon_at",  # sessions
    "expiration",  # api_keys, m2m_tokens
    "last_used_at",  # api_keys, m2m_tokens
    "idp_certificate_issued_at",  # saml_connections
    "idp_certificate_expires_at",  # saml_connections
    "period_start",  # commerce_subscription_items
    "period_end",  # commerce_subscription_items
    "canceled_at",  # commerce_subscription_items
    "past_due_at",  # commerce_subscription_items
    "ended_at",  # commerce_subscription_items
]


def _convert_timestamps(item: dict[str, Any]) -> dict[str, Any]:
    """Convert Clerk timestamp fields from milliseconds to seconds."""
    for field in TIMESTAMP_FIELDS:
        value = item.get(field)
        # Some endpoints return these fields as an ISO string (or other non-numeric shape)
        # rather than epoch milliseconds; leave those untouched instead of crashing on `//`.
        # bool is an int subclass, so exclude it explicitly.
        if isinstance(value, int) and not isinstance(value, bool):
            # Clerk returns timestamps in milliseconds, convert to seconds.
            # Use integer division to maintain int64 type for delta table compatibility.
            item[field] = value // 1000
    return item


# Secrets Clerk returns on list rows that would let a reader impersonate the object: redeemable
# invitation links, and the reusable `token` on each m2m_token that authenticates as its machine.
# Anyone who can read the warehouse table could otherwise copy one, so drop them before the row
# is stored. Values are dotted paths into each endpoint's row shape.
SENSITIVE_FIELDS_BY_ENDPOINT: dict[str, tuple[str, ...]] = {
    "invitations": ("url",),
    "organization_invitations": ("url",),
    "waitlist_entries": ("invitation.url",),
    "m2m_tokens": ("token",),
}


def _strip_sensitive_fields(item: dict[str, Any], paths: tuple[str, ...]) -> dict[str, Any]:
    """Remove the given dotted-path fields from a row in place."""
    for path in paths:
        parts = path.split(".")
        target: Any = item
        for part in parts[:-1]:
            target = target.get(part) if isinstance(target, dict) else None
            if target is None:
                break
        if isinstance(target, dict):
            target.pop(parts[-1], None)
    return item


# Curated copy shared with the sync path's non-retryable-error map in source.py, so a bad key is
# explained the same way whether it's caught at create time or on a running sync. The previous
# behaviour forwarded Clerk's raw response body (and requests' exception string) straight to the
# wizard, which the user can't act on.
_INVALID_KEY_MESSAGE = (
    "Your Clerk secret key is invalid or has been revoked. Please update the secret key in your "
    "Clerk dashboard and reconnect."
)
_FORBIDDEN_KEY_MESSAGE = (
    "Your Clerk secret key does not have permission to access this endpoint. Please check the "
    "key's permissions in your Clerk dashboard."
)


def validate_credentials(secret_key: str) -> tuple[bool, str | None]:
    """Validate Clerk API credentials by making a test request."""
    url = "https://api.clerk.com/v1/users"
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    try:
        response = make_tracked_session().get(url, headers=headers, params={"limit": 1}, timeout=10)
    except RequestException as e:
        capture_exception(e)
        return False, "Couldn't reach Clerk to validate your secret key. Please try again in a moment."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, _INVALID_KEY_MESSAGE
    if response.status_code == 403:
        return False, _FORBIDDEN_KEY_MESSAGE

    # Any other status is unexpected for this endpoint; keep the raw detail for us instead of
    # surfacing it to the user.
    capture_exception(Exception(f"Unexpected Clerk credential validation response ({response.status_code})"))
    return False, "Couldn't validate your Clerk secret key. Please check the key and try again."


# Clerk error codes meaning "this account has not switched the feature on". Paired with the
# statuses Clerk returns them under: 402 carries no body code, so the status alone is the signal.
_FEATURE_DISABLED_CODES = frozenset({"billing_not_enabled", "feature_not_enabled"})

# A gated list endpoint (the Restrictions allow-list and block-list) answers 404 `resource_not_found`
# instead of a 4xx feature code when its feature is off. This check only runs for endpoints that carry
# a `gated_feature`, so a 404 here means the feature is not on rather than a genuinely missing record.
_FEATURE_DISABLED_NOT_FOUND_CODE = "resource_not_found"


def _is_feature_disabled(response: Optional[Response]) -> bool:
    if response is None:
        return False
    if response.status_code == 402:
        return True
    if response.status_code not in (400, 403, 404):
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    errors = body.get("errors") if isinstance(body, dict) else None
    if not isinstance(errors, list):
        return False
    codes = {error.get("code") for error in errors if isinstance(error, dict)}
    if response.status_code == 404:
        return _FEATURE_DISABLED_NOT_FOUND_CODE in codes
    return bool(codes & _FEATURE_DISABLED_CODES)


def _skip_when_feature_disabled(
    items: Iterator[Any], endpoint: str, gated_feature: str, logger: FilteringBoundLogger
) -> Iterator[Any]:
    try:
        yield from items
    except HTTPError as err:
        if not _is_feature_disabled(err.response):
            raise
        logger.warning(
            f"{gated_feature} is not enabled on this Clerk account, so the {endpoint} table synced no rows. "
            "Turn it on in your Clerk dashboard, or turn off syncing for this table."
        )


def clerk_source(
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClerkResumeConfig],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    retired_reason = RETIRED_ENDPOINTS.get(endpoint)
    if retired_reason is not None:
        raise ValueError(retired_reason)

    endpoint_config = CLERK_ENDPOINTS[endpoint]
    resources = get_resources(endpoint)

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.clerk.com/v1",
            "auth": {
                "type": "bearer",
                "token": secret_key,
            },
            "headers": {
                "Content-Type": "application/json",
            },
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": list(resources),
    }

    # Seed the paginator from the saved checkpoint when resuming. A fan-out endpoint checkpoints
    # per parent, so its state passes through untouched rather than as a flat offset.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            if endpoint_config.fan_out is not None:
                initial_paginator_state = resume_config.fan_out
            elif resume_config.offset > 0:
                initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # rest_client passes None once the paginator is exhausted; nothing to persist then.
        if not state:
            return
        if endpoint_config.fan_out is not None:
            resumable_source_manager.save_state(ClerkResumeConfig(fan_out=state))
        elif state.get("offset") is not None:
            resumable_source_manager.save_state(ClerkResumeConfig(offset=int(state["offset"])))

    built = rest_api_resources(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    resource = next(candidate for candidate in built if candidate.name == endpoint).add_map(_convert_timestamps)

    sensitive_fields = SENSITIVE_FIELDS_BY_ENDPOINT.get(endpoint)
    if sensitive_fields:
        resource = resource.add_map(functools.partial(_strip_sensitive_fields, paths=sensitive_fields))

    gated_feature = endpoint_config.gated_feature

    def items() -> Iterator[Any]:
        if gated_feature is None:
            yield from resource
            return
        yield from _skip_when_feature_disabled(iter(resource), endpoint, gated_feature, logger)

    if endpoint_config.partition_key is None:
        return SourceResponse(
            name=endpoint,
            items=items,
            primary_keys=["id"],
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
    )
