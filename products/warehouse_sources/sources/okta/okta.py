import re
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import urlparse

import requests

from products.warehouse_sources.sources.okta.settings import OKTA_ENDPOINTS, POLICY_TYPES, OktaEndpointConfig
from products.warehouse_sources.sources.sdk import (
    BaseNextUrlPaginator,
    ClientConfig,
    Endpoint,
    HeaderLinkPaginator,
    JSONResponsePaginator,
    Resource,
    ResponseAction,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    _is_host_safe,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
)

HOST_NOT_ALLOWED_ERROR = "Okta domain is not allowed"

# An org answers 400 for a policy type it does not support, and E0000015 for a type behind a
# feature it has not enabled. Only `type` is sent, so neither can mean a malformed request.
UNSUPPORTED_POLICY_TYPE_ACTIONS: list[ResponseAction] = [
    {"status_code": 400, "action": "ignore"},
    {"json_field": "errorCode", "json_values": ["E0000015"], "action": "ignore"},
]


class OktaHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class OktaResumeConfig:
    next_url: Optional[str] = None
    # Fan-out tables checkpoint the shape `build_dependent_resource` emits: which parents finished
    # and the child page of the parent in progress.
    fanout_state: Optional[dict[str, Any]] = None
    # Policy tables: the next policy type to read. Every earlier type is already written.
    policy_type: Optional[str] = None


def normalize_domain(domain: str) -> str:
    """Turn whatever the user typed into a bare Okta org host.

    Accepts values like ``company.okta.com``, ``https://company.okta.com/``,
    or ``company.okta.com/api/v1`` and returns ``company.okta.com``.
    """
    domain = domain.strip()
    domain = re.sub(r"^https?://", "", domain, flags=re.IGNORECASE)
    domain = domain.split("/")[0]
    return domain.strip().rstrip("/")


def _base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}/api/v1"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"SSWS {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _format_datetime_z(dt: datetime) -> str:
    """Okta wants ISO 8601 with millisecond precision and a literal ``Z`` suffix."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _build_initial_params(
    config: OktaEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size} if config.send_limit else {}

    if config.name == "logs":
        # The System Log defaults to the last 7 days when `since` is omitted, so on the
        # first sync we explicitly reach back to the start of Okta's retention window.
        params["sortOrder"] = "ASCENDING"
        if should_use_incremental_field:
            since_value = db_incremental_field_last_value
            if not since_value and config.default_lookback_days:
                since_value = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
            if since_value:
                params["since"] = _format_incremental_value(since_value)
        return params

    if config.incremental_param == "filter" and should_use_incremental_field and db_incremental_field_last_value:
        field = incremental_field or config.default_incremental_field
        formatted = _format_incremental_value(db_incremental_field_last_value)
        # Okta's SCIM-style filter expects the value wrapped in double quotes.
        params["filter"] = f'{field} gt "{formatted}"'

    return params


def _drop_fields(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    paths = [name.split(".") for name in fields]

    def drop(row: dict[str, Any]) -> dict[str, Any]:
        for *parents, leaf in paths:
            target: Any = row
            for parent in parents:
                target = target.get(parent) if isinstance(target, dict) else None
            if isinstance(target, dict):
                target.pop(leaf, None)
        return row

    return drop


def _lift_fields(fields: dict[str, tuple[str, ...]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def lift(row: dict[str, Any]) -> dict[str, Any]:
        for column, path in fields.items():
            value: Any = row
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            row[column] = value
        return row

    return lift


def _map_rows(resource: Iterable[Any], config: OktaEndpointConfig) -> Iterable[Any]:
    if config.excluded_fields:
        resource = cast(Resource, resource).add_map(_drop_fields(config.excluded_fields))
    if config.lifted_fields:
        resource = cast(Resource, resource).add_map(_lift_fields(config.lifted_fields))
    return resource


def _is_same_host(url: str, domain: str) -> bool:
    """Whether ``url`` points at the configured Okta org host.

    Pagination/resume URLs are server-controlled (they arrive in the Link header), so we
    pin them to the validated org host to avoid being redirected at an arbitrary internal
    address (SSRF).
    """
    try:
        return (urlparse(url).hostname or "").lower() == normalize_domain(domain).lower()
    except Exception:
        return False


def _stop_off_org_host(paginator: BaseNextUrlPaginator, domain: str) -> None:
    if paginator._has_next_page and paginator._next_url is not None and not _is_same_host(paginator._next_url, domain):
        paginator._has_next_page = False
        paginator._next_url = None


class OktaLinkPaginator(HeaderLinkPaginator):
    """Okta paginates via the ``Link`` header, with two Okta-specific twists on top of
    the framework's ``rel="next"`` following:

    - The System Log endpoint *always* returns a next link (it is designed for polling),
      so an empty page must end pagination rather than looping forever.
    - The next link is server-controlled, so it is pinned to the org host; an off-host
      link stops pagination (SSRF guard) instead of being followed.
    """

    def __init__(self, domain: str) -> None:
        super().__init__()
        self._domain = domain

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)
        _stop_off_org_host(self, self._domain)


class OktaBodyLinkPaginator(JSONResponsePaginator):
    """Follows the ``_links.next.href`` body link of the custom-role endpoints, pinned to the org host."""

    def __init__(self, domain: str) -> None:
        super().__init__(next_url_path="_links.next.href")
        self._domain = domain

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)
        _stop_off_org_host(self, self._domain)


def _iter_policy_types(
    build_resource: Callable[[str], Iterable[Any]],
    resumable_source_manager: ResumableSourceManager[OktaResumeConfig],
    resume: Optional[OktaResumeConfig],
) -> Iterator[Any]:
    start = POLICY_TYPES.index(resume.policy_type) if resume and resume.policy_type in POLICY_TYPES else 0
    for index in range(start, len(POLICY_TYPES)):
        policy_type = POLICY_TYPES[index]
        if index > start:
            # Every row of the earlier types is yielded, so a hand-off here resumes at this type.
            resumable_source_manager.save_state(OktaResumeConfig(policy_type=policy_type))
            resumable_source_manager.safe_point()
        yield from build_resource(policy_type)


def validate_credentials(
    domain: str, api_key: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe a cheap list endpoint to confirm the SSWS token is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the token is valid but may
    simply lack the scope for this particular probe. A scoped probe (``schema_name`` set) treats
    403 as a hard failure.
    """
    try:
        normalized = normalize_domain(domain)
    except Exception:
        return False, "Invalid Okta domain"

    if not normalized or not re.match(r"^[A-Za-z0-9.\-]+$", normalized):
        return False, "Invalid Okta domain"

    # The org domain is fully customer-controlled, so block hosts that resolve to private/
    # internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"https://{normalized}/api/v1/users"
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address, defeating
        # the host check above (SSRF).
        response = make_tracked_session().get(
            url, headers=_get_headers(api_key), params={"limit": 1}, timeout=10, allow_redirects=False
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Okta API token"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing scope for this probe — let source creation through.
            return True, None
        return False, "Okta API token lacks the required permissions for this endpoint"

    try:
        body = response.json()
        return False, body.get("errorSummary", response.text)
    except Exception:
        return False, response.text


def okta_source(
    domain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OktaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = OKTA_ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": _base_url(domain),
        # Auth (the SSWS token) is supplied via the framework auth config so its value is
        # redacted from logs and raised error messages; only non-secret headers go here.
        "headers": {"Accept": "application/json", "Content-Type": "application/json"},
        "auth": {"type": "api_key", "api_key": f"SSWS {api_key}", "name": "Authorization", "location": "header"},
        "paginator": OktaLinkPaginator(domain),
        # A validated host could 3xx to an internal address; refuse to follow redirects (SSRF).
        "allow_redirects": False,
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    resource: Iterable[Any]
    if config.fanout is not None:
        fanout = config.fanout
        # The saved fan-out state carries child next-page URLs, so pin every request to the org
        # host rather than trusting a stored URL (SSRF).
        client_config["allowed_hosts"] = []

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(OktaResumeConfig(fanout_state=state))

        child_endpoint_extra: Optional[Endpoint] = None if config.paginated else {"paginator": "single_page"}

        def build_fanout(policy_type: Optional[str] = None) -> Iterable[Any]:
            child_fanout = fanout
            parent_endpoint_extra: Optional[Endpoint] = None
            if policy_type is not None:
                child_fanout = dataclasses.replace(fanout, parent_params={**fanout.parent_params, "type": policy_type})
                parent_endpoint_extra = {"response_actions": UNSUPPORTED_POLICY_TYPE_ACTIONS}
            return _map_rows(
                build_dependent_resource(
                    endpoint_configs=OKTA_ENDPOINTS,
                    child_endpoint=endpoint,
                    fanout=child_fanout,
                    client_config=client_config,
                    path_format_values={},
                    team_id=team_id,
                    job_id=job_id,
                    db_incremental_field_last_value=None,
                    parent_endpoint_extra=parent_endpoint_extra,
                    child_endpoint_extra=child_endpoint_extra,
                    page_size_param="limit" if config.paginated and config.send_limit else None,
                    resume_hook=save_fanout_checkpoint if config.resumable else None,
                    initial_paginator_state=resume.fanout_state if resume and config.resumable else None,
                ),
                config,
            )

        if config.per_policy_type:
            resource = _iter_policy_types(build_fanout, resumable_source_manager, resume)
        else:
            resource = build_fanout()
    elif config.per_policy_type:
        params = _build_initial_params(config, False, None, None)

        def build_policies(policy_type: str) -> Iterable[Any]:
            policy_config: RESTAPIConfig = {
                "client": client_config,
                "resources": [
                    {
                        "name": endpoint,
                        "endpoint": {
                            "path": config.path,
                            "params": {**params, "type": policy_type},
                            "response_actions": UNSUPPORTED_POLICY_TYPE_ACTIONS,
                        },
                    }
                ],
            }
            return _map_rows(rest_api_resource(policy_config, team_id, job_id, None), config)

        resource = _iter_policy_types(build_policies, resumable_source_manager, resume)
    else:
        params = _build_initial_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )

        endpoint_config: Endpoint = {"path": config.path, "params": params}
        if config.data_selector:
            endpoint_config["data_selector"] = config.data_selector
        if config.next_link_in_body:
            endpoint_config["paginator"] = OktaBodyLinkPaginator(domain)

        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resources": [{"name": endpoint, "endpoint": endpoint_config}],
        }

        # A poisoned resume URL (off the org host) must be ignored, falling back to the initial org
        # URL rather than being followed (SSRF).
        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None and resume.next_url and _is_same_host(resume.next_url, domain):
            initial_paginator_state = {"next_url": resume.next_url}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
            # the next page (merge dedupes) rather than skipping data.
            if state and state.get("next_url"):
                resumable_source_manager.save_state(OktaResumeConfig(next_url=state["next_url"]))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        resource = _map_rows(resource, config)

    def items() -> Iterator[list[Any]]:
        # Re-check at run time (not just at source-create) in case the domain was edited or now
        # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(normalize_domain(domain), team_id)
        if not host_ok:
            raise OktaHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        yield from resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # Okta returns the System Log ascending (we request sortOrder=ASCENDING). The filter
        # endpoints don't guarantee an order, but each sync re-applies `filter=lastUpdated gt
        # <watermark>` and paginates every page, so completeness doesn't depend on ordering.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
