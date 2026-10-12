import re
import json
import hashlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

from requests import Response
from requests.exceptions import HTTPError, RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import create_auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logrocket import (
    LogrocketSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logrocket.settings import (
    BASE_URL,
    ENDPOINTS,
    LogrocketEndpoint,
)


@frozen
class LogrocketResumeConfig:
    cursor: str | None = None
    file_id: str | None = None
    line_number: int = 0
    completed_file_ids: list[str] = field(default_factory=list)
    finished: bool = False


class LogrocketPaginator(JSONResponseCursorPaginator):
    def __init__(self, schema_name: str) -> None:
        super().__init__(cursor_path="cursor", raise_on_repeated_cursor=True)
        self.schema_name = schema_name

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if self.schema_name == "audit_logs":
            if not isinstance(body.get("has_next"), bool):
                raise ValueError("LogRocket omitted the audit pagination flag")
            has_next = body["has_next"]
        else:
            has_next = bool(data)
        if not has_next:
            self._has_next_page = False
            return
        cursor = body.get("cursor")
        if cursor is None or cursor == "":
            raise ValueError("LogRocket omitted the next pagination cursor")
        next_cursor = str(cursor)
        if next_cursor == self._previous_cursor_value:
            raise ValueError("LogRocket cursor pagination is not advancing")
        self._previous_cursor_value = next_cursor
        self._cursor_value = next_cursor
        self._has_next_page = True


def _client_config(config: LogrocketSourceConfig) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "api_key", "name": "Authorization", "api_key": f"token {config.api_key}"},
        "headers": {"Accept": "application/json"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 30),
        "retry_budget_seconds": 120,
        "retry_after_max_seconds": 60,
        # Manifest bodies contain signed file URLs that must stay out of sample capture.
        "capture": False,
    }


def _client(config: LogrocketSourceConfig) -> RESTClient:
    client_config = _client_config(config)
    return RESTClient(
        base_url=client_config["base_url"],
        auth=create_auth(client_config["auth"]),
        headers=client_config["headers"],
        allowed_hosts=client_config["allowed_hosts"],
        allow_redirects=client_config["allow_redirects"],
        request_timeout=client_config["request_timeout"],
        retry_budget_seconds=client_config["retry_budget_seconds"],
        retry_after_max_seconds=client_config["retry_after_max_seconds"],
        capture=client_config["capture"],
    )


def _request_path(config: LogrocketSourceConfig, endpoint: LogrocketEndpoint) -> str:
    return f"orgs/{quote(config.organization_id, safe='')}/apps/{quote(config.project_id, safe='')}/{endpoint.path}"


def _request_params(schema_name: str, page_size: int) -> dict[str, Any]:
    return {"limit": page_size, **({"cursor": "0"} if schema_name == "audit_logs" else {})}


def _resource_config(config: LogrocketSourceConfig, schema_name: str) -> EndpointResource:
    endpoint = schema_for_resource(ENDPOINTS, schema_name)
    endpoint_def: Endpoint = {
        "path": _request_path(config, endpoint),
        "params": _request_params(schema_name, endpoint.page_size),
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "paginator": LogrocketPaginator(schema_name),
    }
    return {
        "name": schema_name,
        "table_name": schema_name,
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": endpoint_def,
    }


def validate_credentials(config: LogrocketSourceConfig, schema_name: str | None) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, "Unknown LogRocket table. Select a supported table."
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in (config.organization_id, config.project_id)):
        return False, "Enter the organization ID and project ID from your LogRocket project URL."
    if not config.api_key or not config.api_key.isascii() or any(ord(char) < 32 for char in config.api_key):
        return False, "Enter a valid LogRocket API key from Settings > API Keys."

    probe_schema = schema_name or "audit_logs"
    endpoint = ENDPOINTS[probe_schema]
    client = _client(config)
    try:
        next(
            client.paginate(
                path=_request_path(config, endpoint),
                params=_request_params(probe_schema, 1),
                data_selector=endpoint.data_selector,
                data_selector_required=True,
                paginator=SinglePagePaginator(),
            )
        )
        return True, None
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, "LogRocket rejected your API key. Create a new key in Settings > API Keys."
        if status == 403:
            if schema_name is None:
                return True, None
            return False, "LogRocket denied access to this table. Check your API key permissions and required add-on."
        if status == 404:
            return False, "LogRocket could not find this project. Check the organization ID and project ID."
        raise
    finally:
        client.session.close()


def _export_file_id(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
    ):
        raise ValueError("LogRocket returned an invalid export file URL")
    return hashlib.sha256(f"{parts.hostname}{parts.path}".encode()).hexdigest()


def _file_rows(
    url: str,
    file_id: str,
    resume: LogrocketResumeConfig,
    manager: ResumableSourceManager[LogrocketResumeConfig],
) -> Iterator[dict[str, Any]]:
    secrets = tuple(value for _, value in parse_qsl(urlsplit(url).query) if value)
    # Export URLs carry storage credentials. A separate session prevents forwarding the LogRocket API key.
    with make_tracked_session(
        retry=DEFAULT_RETRY.new(total=1), redact_values=(url, *secrets), capture=False
    ) as session:
        try:
            with session.get(url, stream=True, timeout=(10, 30), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise RuntimeError("LogRocket export download failed. Retry the sync to obtain a new file URL.")
                for line_number, line in enumerate(response.iter_lines(chunk_size=64 * 1024), start=1):
                    if line_number <= resume.line_number or not line.strip():
                        if line_number % 1000 == 0:
                            manager.safe_point()
                        continue
                    try:
                        row = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        raise ValueError(f"Invalid JSON in LogRocket export at line {line_number}") from None
                    if not isinstance(row, dict):
                        raise ValueError(f"Expected a LogRocket event object at line {line_number}")
                    timestamp = row.get("time")
                    row["event_time"] = datetime.fromtimestamp(timestamp / 1000, UTC) if timestamp is not None else None
                    row["export_file_id"] = file_id
                    row["export_line"] = line_number
                    manager.save_state(
                        LogrocketResumeConfig(
                            cursor=resume.cursor,
                            file_id=file_id,
                            line_number=line_number,
                            completed_file_ids=resume.completed_file_ids,
                        )
                    )
                    yield row
        except RequestException:
            raise RuntimeError("LogRocket export download failed. Retry the sync to obtain a new file URL.") from None


def _session_events(
    config: LogrocketSourceConfig,
    resume: LogrocketResumeConfig,
    manager: ResumableSourceManager[LogrocketResumeConfig],
) -> Iterator[dict[str, Any]]:
    endpoint = ENDPOINTS["session_events"]
    next_state: dict[str, Any] | None = None

    def page_state(state: dict[str, Any] | None, has_next_page: bool) -> None:
        nonlocal next_state
        next_state = state

    client = _client(config)
    try:
        for page in client.paginate(
            path=_request_path(config, endpoint),
            params=_request_params("session_events", endpoint.page_size),
            data_selector=endpoint.data_selector,
            data_selector_required=True,
            paginator=LogrocketPaginator("session_events"),
            initial_paginator_state={"cursor": resume.cursor} if resume.cursor is not None else None,
            page_state_hook=page_state,
        ):
            files = [(item["url"], _export_file_id(item["url"])) for item in page]
            if resume.file_id is not None and not any(file_id == resume.file_id for _, file_id in files):
                raise RuntimeError("The saved LogRocket export file is no longer available. Restart the full refresh.")
            completed = list(resume.completed_file_ids)
            for url, file_id in files:
                if file_id in completed:
                    continue
                file_resume = LogrocketResumeConfig(
                    cursor=resume.cursor,
                    file_id=file_id,
                    line_number=resume.line_number if file_id == resume.file_id else 0,
                    completed_file_ids=list(completed),
                )
                # Row checkpoints are saved before each yield, so a finished file or page needs no save after it:
                # a resume reopens the last file, skips its saved lines and moves on.
                yield from _file_rows(url, file_id, file_resume, manager)
                completed.append(file_id)
                manager.safe_point()
            resume = LogrocketResumeConfig(cursor=str(next_state["cursor"])) if next_state else resume
            manager.safe_point()
        manager.save_state(LogrocketResumeConfig(finished=True))
        manager.safe_point()
    finally:
        client.session.close()


def logrocket_source(
    config: LogrocketSourceConfig,
    manager: ResumableSourceManager[LogrocketResumeConfig],
    inputs: SourceInputs,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    if inputs.should_use_incremental_field:
        raise ValueError("LogRocket supports full refresh only. Change the table sync mode to full refresh.")
    resume = manager.load_state() if manager.can_resume() else None
    resume = resume or LogrocketResumeConfig()
    items: Callable[[], Iterable[Any]]
    if resume.finished:
        items = lambda: iter(())
    elif inputs.schema_name == "session_events":
        items = lambda: _session_events(config, resume, manager)
    else:

        def save_page(state: dict[str, Any] | None) -> None:
            manager.save_state(
                LogrocketResumeConfig(cursor=str(state["cursor"])) if state else LogrocketResumeConfig(finished=True)
            )

        resource_config = _resource_config(config, inputs.schema_name)
        resource_config["columns"] = {"created_date": {"data_type": "timestamp"}}
        rest_config: RESTAPIConfig = {"client": _client_config(config), "resources": [resource_config]}
        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_page,
            initial_paginator_state={"cursor": resume.cursor} if resume.cursor is not None else None,
        )
        items = lambda: resource
    return SourceResponse(
        name=inputs.schema_name,
        items=items,
        primary_keys=list(endpoint.primary_keys) if endpoint.primary_keys else None,
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
    )
