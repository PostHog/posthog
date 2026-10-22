import re
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logicmonitor import (
    LogicmonitorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.settings import (
    API_VERSION,
    ENDPOINTS,
    FIELDS,
    MAX_ALERTS_PER_WINDOW,
    PAGE_SIZE,
    PRIMARY_KEYS,
)

AUTH_ERROR = "LogicMonitor rejected the bearer token. Check the token and its expiration date."
PERMISSION_ERROR = "LogicMonitor denied access. Give the token's user view permission for the selected resource."
DENSE_WINDOW_ERROR = (
    "LogicMonitor returned too many alerts in one second. Contact support to export this alert history."
)


@frozen
class LogicMonitorResumeConfig:
    offset: int = 0
    window_start: int = 0
    window_end: int = 0
    sync_end: int = 0
    complete: bool = False


def portal_url(value: str) -> str:
    message = "Enter an HTTPS LogicMonitor portal URL, such as https://example.logicmonitor.com, without a path."
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme != "https"
            or not re.fullmatch(
                r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.logicmonitor\.com", parsed.hostname or ""
            )
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(message)
    except ValueError:
        raise ValueError(message) from None
    return f"https://{parsed.hostname}"


def validate_portal_host(value: str, team_id: int) -> tuple[bool, str | None]:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (  # noqa: PLC0415 -- keeps Django models off the source registration path
        ValidateDatabaseHostMixin,
    )

    try:
        url = portal_url(value)
    except ValueError as error:
        return False, str(error)
    return ValidateDatabaseHostMixin().is_database_host_valid(urlsplit(url).hostname or "", team_id)


class AlertWindowTooLarge(Exception):
    pass


class AlertPaginator(OffsetPaginator):
    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        total = response.json().get("total")
        if not isinstance(total, int) or total < 0:
            raise ValueError("LogicMonitor did not return a valid alert count.")
        if total > MAX_ALERTS_PER_WINDOW:
            if self.offset:
                raise ValueError("LogicMonitor alert counts changed during pagination. Restart the full refresh.")
            raise AlertWindowTooLarge
        super().update_state(response, data)


class LogicMonitorClient:
    def __init__(self, config: LogicmonitorSourceConfig) -> None:
        self.base_url = f"{portal_url(config.portal_url)}/santaba/rest/"
        self.token = config.bearer_token

    def validate_credentials(self) -> tuple[bool, str | None]:
        client = RESTClient(
            base_url=self.base_url,
            auth=BearerTokenAuth(token=self.token),
            headers={"X-Version": API_VERSION},
            allowed_hosts=[],
            allow_redirects=False,
            request_timeout=60,
        )
        try:
            next(
                client.paginate(
                    path=ENDPOINTS["devices"],
                    params={"size": 1, "fields": "id"},
                    paginator=SinglePagePaginator(),
                    data_selector="items",
                    data_selector_required=True,
                )
            )
        except HTTPError as error:
            if error.response is not None and error.response.status_code in (401, 403):
                return False, AUTH_ERROR if error.response.status_code == 401 else PERMISSION_ERROR
            raise
        return True, None

    def source_response(
        self, inputs: SourceInputs, manager: ResumableSourceManager[LogicMonitorResumeConfig]
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown LogicMonitor table: {inputs.schema_name}")
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: self.iter_rows(inputs, manager),
            primary_keys=PRIMARY_KEYS,
            sort_mode=None,
            on_complete=manager.clear_state,
        )

    def iter_rows(
        self, inputs: SourceInputs, manager: ResumableSourceManager[LogicMonitorResumeConfig]
    ) -> Iterator[list[dict[str, Any]]]:
        saved = manager.load_state() if manager.can_resume() else None
        sync_end = int(time.time()) + 1
        state = saved or LogicMonitorResumeConfig(window_end=sync_end, sync_end=sync_end)
        is_alerts = inputs.schema_name == "alerts"
        while not state.complete:
            params: dict[str, Any] = {}
            if inputs.schema_name in FIELDS:
                params["fields"] = FIELDS[inputs.schema_name]
            if is_alerts:
                params["filter"] = f'cleared:"*",startEpoch>:{state.window_start},startEpoch<{state.window_end}'
                params["sort"] = "startEpoch"
            paginator_class = AlertPaginator if is_alerts else OffsetPaginator
            config: RESTAPIConfig = {
                "client": {
                    "base_url": self.base_url,
                    "auth": {"type": "bearer", "token": self.token},
                    "headers": {"X-Version": API_VERSION},
                    "allowed_hosts": [],
                    "allow_redirects": False,
                    "request_timeout": 60,
                    "paginator": paginator_class(limit=PAGE_SIZE, limit_param="size", total_path="total"),
                },
                "resources": [
                    {
                        "name": inputs.schema_name,
                        "table_format": "delta",
                        "write_disposition": "replace",
                        "endpoint": {
                            "path": ENDPOINTS[inputs.schema_name],
                            "params": params,
                            "data_selector": "items",
                            "data_selector_required": True,
                        },
                    }
                ],
            }

            def save_checkpoint(
                paginator_state: dict[str, Any] | None, state: LogicMonitorResumeConfig = state
            ) -> None:
                if paginator_state is not None:
                    manager.save_state(replace(state, offset=int(paginator_state["offset"])))
                else:
                    manager.save_state(
                        replace(
                            state,
                            offset=0,
                            window_start=state.window_end,
                            window_end=state.sync_end,
                            complete=not is_alerts or state.window_end >= state.sync_end,
                        )
                    )

            resource = rest_api_resource(
                config,
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=save_checkpoint,
                initial_paginator_state={"offset": state.offset},
            )
            try:
                yield from resource
            except AlertWindowTooLarge:
                if state.window_end - state.window_start <= 1:
                    raise ValueError(DENSE_WINDOW_ERROR) from None
                # Split before yielding this window so a retry cannot duplicate its rows.
                state = replace(state, window_end=(state.window_start + state.window_end) // 2, offset=0)
                manager.save_state(state)
                manager.safe_point()
                continue
            if not is_alerts or state.window_end >= state.sync_end:
                break
            state = replace(state, window_start=state.window_end, window_end=state.sync_end, offset=0)
