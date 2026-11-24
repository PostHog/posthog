import json
from collections.abc import Iterable
from datetime import timedelta
from typing import Any, Optional, cast
from urllib.parse import urlparse

from requests import Request, Response

from products.warehouse_sources.sources.helpin.settings import (
    API_PATH_PREFIX,
    HELPIN_CLOUD_API_HOST,
    HELPIN_ENDPOINTS,
    HelpinEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    EndpointResource,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    parse_datetime_value,
    rest_api_resource,
)

NEXT_OFFSET_PATH = "data.next_offset"
PROBE_TIMEOUT_SECONDS = 15.0


@frozen
class HelpinResumeConfig:
    # The paginator (or fan-out) state as the framework hands it to the resume hook, stored unchanged.
    paginator_state: dict[str, Any] | None = None


class HelpinPassPaginator(JSONResponseCursorPaginator):
    """Follows `data.next_offset` through one pass per params set, then starts the next pass at offset 0."""

    def __init__(self, passes: tuple[dict[str, Any], ...]) -> None:
        super().__init__(cursor_path=NEXT_OFFSET_PATH, cursor_param="offset")
        self._passes = passes
        self._pass_index = 0

    def init_request(self, request: Request) -> None:
        self._apply_pass(request)
        super().init_request(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page and self._pass_index + 1 < len(self._passes):
            self._pass_index += 1
            self._cursor_value = None
            self._previous_cursor_value = None
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply_pass(request)
        super().update_request(request)

    def _apply_pass(self, request: Request) -> None:
        request.params.update(self._passes[self._pass_index])
        if self._cursor_value is None:
            request.params.pop("offset", None)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._has_next_page:
            return None
        return {"pass": self._pass_index, "cursor": self._cursor_value}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self._pass_index = int(state.get("pass") or 0)
        super().set_resume_state(state)
        self._has_next_page = True


def normalize_api_host(api_host: Optional[str]) -> str:
    """Return the API base URL for a Helpin host, ending in `/public/v1`.

    A blank host means Helpin Cloud. Self-hosted hosts must be plain https URLs: the token goes in a
    header to this host, so a scheme, credentials or encoded characters that could make the safety
    check and the HTTP client disagree on the target host are refused.
    """
    host = (api_host or "").strip()
    if not host:
        host = HELPIN_CLOUD_API_HOST
    if "://" not in host:
        host = f"https://{host}"
    if "\\" in host or "%" in host or "@" in host or "?" in host or "#" in host:
        raise ValueError("Invalid Helpin API host")
    try:
        parsed = urlparse(host)
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid Helpin API host")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("The Helpin API host must use https")
    host_part = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    if parsed.netloc.lower() != (host_part + (f":{port}" if port else "")).lower():
        raise ValueError("Invalid Helpin API host")
    path = parsed.path.rstrip("/")
    if path.lower().endswith(API_PATH_PREFIX):
        path = path[: -len(API_PATH_PREFIX)]
    return f"https://{parsed.netloc}{path}{API_PATH_PREFIX}"


def api_hostname(api_host: Optional[str]) -> str:
    return urlparse(normalize_api_host(api_host)).hostname or ""


def _get(base_url: str, api_token: str, path: str, params: Optional[dict[str, Any]] = None) -> Response:
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
    return session.get(
        f"{base_url}{path}",
        params=params,
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        timeout=PROBE_TIMEOUT_SECONDS,
    )


def _error_code(response: Response) -> Optional[str]:
    try:
        error = response.json().get("error")
    except Exception:
        return None
    return error.get("code") if isinstance(error, dict) else None


def validate_credentials(
    base_url: str, api_token: str, schema_name: Optional[str] = None
) -> tuple[bool, Optional[str]]:
    if schema_name is None:
        response = _get(base_url, api_token, "/me")
        if response.status_code == 200:
            return True, None
        if response.status_code == 401:
            return False, "Helpin didn't accept this token. Create a new token for the automation account in Helpin."
        if response.status_code == 403:
            if _error_code(response) == "api_disabled":
                return False, "The Helpin API is turned off for this workspace. Ask a workspace manager to turn it on."
            # The token is genuine but lacks the context scope. Per-table scopes are checked per table.
            return True, None
        if response.status_code == 404:
            return False, "Couldn't find the Helpin API at this host. Check the API host."
        return False, f"The Helpin API returned an unexpected status code ({response.status_code}). Try again later."

    config = HELPIN_ENDPOINTS.get(schema_name)
    if config is None:
        return False, f"Unknown Helpin table: {schema_name}"
    probe = HELPIN_ENDPOINTS[config.fanout.parent_name] if config.fanout else config
    response = _get(base_url, api_token, probe.path, {"limit": 1})
    if response.status_code == 200:
        return True, None
    if response.status_code == 403:
        return (
            False,
            f"Your Helpin token can't read this table. Give its automation account the `{config.scope}` scope.",
        )
    if response.status_code == 401:
        return False, "Helpin didn't accept this token. Create a new token for the automation account in Helpin."
    return False, f"The Helpin API returned an unexpected status code ({response.status_code}). Try again later."


def endpoint_permissions(base_url: str, api_token: str, endpoints: list[str]) -> dict[str, Optional[str]]:
    """Name the missing scope of each table, from the scopes that `/me` lists for the token."""
    result: dict[str, Optional[str]] = dict.fromkeys(endpoints)
    try:
        response = _get(base_url, api_token, "/me")
        scopes = response.json()["data"]["scopes"] if response.status_code == 200 else None
    except Exception:
        return result
    if not isinstance(scopes, list):
        return result
    for name in endpoints:
        config = HELPIN_ENDPOINTS.get(name)
        if config is not None and config.scope not in scopes:
            result[name] = f"Needs the `{config.scope}` scope on the automation account."
    return result


def _updated_since(db_incremental_field_last_value: Any) -> Optional[str]:
    watermark = parse_datetime_value(db_incremental_field_last_value)
    if watermark is None:
        return None
    # Helpin filters by whole days, in a time zone it doesn't document. A day earlier never misses
    # a row; the merge drops the rows read again.
    return (watermark.date() - timedelta(days=1)).isoformat()


def _incremental_params(config: HelpinEndpointConfig, db_incremental_field_last_value: Any) -> dict[str, Any]:
    since = _updated_since(db_incremental_field_last_value)
    if since is None or config.updated_filter is None:
        return {}
    if config.updated_filter == "updated_after":
        return {"updated_after": since}
    rule = {"field": "updated_at", "operator": "on_or_after", "value": since}
    return {"filter": json.dumps({"logic": "and", "rules": [rule]}, separators=(",", ":"))}


def _paginator(config: HelpinEndpointConfig) -> BasePaginator:
    if config.pagination == "single":
        return SinglePagePaginator()
    if config.passes:
        return HelpinPassPaginator(config.passes)
    return JSONResponseCursorPaginator(cursor_path=NEXT_OFFSET_PATH, cursor_param="offset")


def _client_config(base_url: str, api_token: str) -> ClientConfig:
    return {
        "base_url": base_url,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
        "paginator": JSONResponseCursorPaginator(cursor_path=NEXT_OFFSET_PATH, cursor_param="offset"),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _source_response(config: HelpinEndpointConfig, items: Iterable[Any]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=lambda: items,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def helpin_source(
    base_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HelpinResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HELPIN_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.paginator_state:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(HelpinResumeConfig(paginator_state=state))

    if config.fanout is not None:
        child = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=HELPIN_ENDPOINTS,
                child_endpoint=config.name,
                fanout=config.fanout,
                client_config=_client_config(base_url, api_token),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                parent_endpoint_extra={
                    "data_selector": HELPIN_ENDPOINTS[config.fanout.parent_name].data_selector,
                    "data_selector_required": True,
                },
                child_endpoint_extra={
                    "data_selector": config.data_selector,
                    "data_selector_required": True,
                    "paginator": _paginator(config),
                },
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state,
                resume_parent_pagination=True,
            ),
        )
        return _source_response(config, child)

    use_incremental = should_use_incremental_field and bool(config.incremental_fields)
    params: dict[str, Any] = {"limit": config.page_size, **config.params}
    if use_incremental:
        params.update(_incremental_params(config, db_incremental_field_last_value))

    resource_config: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": config.data_selector,
            "data_selector_required": True,
            "paginator": _paginator(config),
        },
        "table_format": "delta",
    }
    rest_config: RESTAPIConfig = {"client": _client_config(base_url, api_token), "resources": [resource_config]}

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _source_response(config, resource)
