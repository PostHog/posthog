import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import UUID

from asgiref.sync import async_to_sync
from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.browse_ai.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PERMISSION_ERROR,
    BrowseAIEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse

if TYPE_CHECKING:
    import pyarrow as pa

    from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager


@frozen
class BrowseAIResumeConfig:
    paginator_state: dict[str, Any] | None = None


class BrowseAIPagePaginator(PageNumberPaginator):
    def __init__(self, pagination_path: str) -> None:
        super().__init__(base_page=1, stop_after_empty_page=False)
        self.pagination_path = pagination_path

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        pagination = response.json()
        for key in self.pagination_path.split("."):
            pagination = pagination[key]
        has_more = pagination["hasMore"]
        if not isinstance(has_more, bool):
            raise ValueError("Browse AI returned an invalid hasMore value")
        super().update_state(response, data)
        self._has_next_page = has_more


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    if isinstance(row.get("createdAt"), int | float):
        row["createdAt"] = datetime.fromtimestamp(row["createdAt"] / 1000, tz=UTC)
    return row


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(base_url=BASE_URL, auth=BearerTokenAuth(api_key), request_timeout=30)
    try:
        next(
            client.paginate(
                "robots", paginator=SinglePagePaginator(), data_selector="robots.items", data_selector_required=True
            )
        )
    except HTTPError as error:
        if error.response is not None and error.response.status_code in (401, 403):
            return False, AUTH_ERROR if error.response.status_code == 401 else PERMISSION_ERROR
        raise
    return True, None


def endpoint_config(endpoint: BrowseAIEndpoint) -> Endpoint:
    return {
        "path": endpoint.path,
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "paginator": BrowseAIPagePaginator(endpoint.pagination_path)
        if endpoint.pagination_path
        else SinglePagePaginator(),
    }


def browse_ai_source(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[BrowseAIResumeConfig],
    webhook_manager: "WebhookSourceManager",
) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError(f"Unknown Browse AI schema: {inputs.schema_name}")
    endpoint = ENDPOINTS[inputs.schema_name]
    webhook_enabled = endpoint.name == "tasks" and async_to_sync(webhook_manager.webhook_enabled)()

    def rows() -> Iterator[list[dict[str, Any]]]:
        resume = manager.load_state() if manager.can_resume() else None
        client: ClientConfig = {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "request_timeout": 30,
        }

        def save_state(state: dict[str, Any] | None) -> None:
            manager.save_state(BrowseAIResumeConfig(paginator_state=state))

        initial = resume.paginator_state if resume else None
        if endpoint.fanout:
            resource = build_dependent_resource(
                endpoint_configs=ENDPOINTS,
                child_endpoint=endpoint.name,
                fanout=endpoint.fanout,
                client_config=client,
                path_format_values={},
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                db_incremental_field_last_value=None,
                parent_endpoint_extra=endpoint_config(ENDPOINTS["robots"]),
                child_endpoint_extra=endpoint_config(endpoint),
                child_params_extra=endpoint.params,
                page_size_param=None,
                resume_hook=save_state,
                initial_paginator_state=initial,
            )
        else:
            resource = rest_api_resource(
                {
                    "client": client,
                    "resources": [
                        {"name": endpoint.name, "endpoint": endpoint_config(endpoint), "table_format": "delta"}
                    ],
                },
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=save_state,
                initial_paginator_state=initial,
            )
        for page in resource:
            yield [normalize_row(row) for row in page]

    return SourceResponse(
        name=endpoint.name,
        items=(lambda: webhook_manager.get_items(table_transformer=webhook_table)) if webhook_enabled else rows,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
        supports_resume=not webhook_enabled and endpoint.fanout is not None,
    )


def webhook_table(table: "pa.Table") -> "pa.Table":
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (  # noqa: PLC0415 - keep Arrow conversion off the source registry import path
        table_from_py_list,
    )

    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in table.to_pylist():
        task = row["task"]
        key = (task["robotId"], task["id"])
        previous = latest.get(key)
        if previous is None or (task.get("finishedAt") or 0) >= (previous.get("finishedAt") or 0):
            latest[key] = task
    return table_from_py_list([normalize_row(task) for task in latest.values()])


class BrowseAIWebhooks:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        # Webhook listings contain callback tokens that are not known before the response arrives.
        self.client = RESTClient(base_url=BASE_URL, auth=BearerTokenAuth(api_key), request_timeout=30, capture=False)

    def _robots(self) -> list[dict[str, Any]]:
        return next(
            self.client.paginate(
                "robots", paginator=SinglePagePaginator(), data_selector="robots.items", data_selector_required=True
            )
        )

    def _path(self, robot_id: str) -> str:
        return f"robots/{UUID(robot_id)}/webhooks"

    def _hooks(self, robot_id: str) -> list[dict[str, Any]]:
        return next(
            self.client.paginate(
                self._path(robot_id),
                paginator=SinglePagePaginator(),
                data_selector="webhooks.items",
                data_selector_required=True,
            )
        )

    @staticmethod
    def _matches(url: str, webhook_url: str) -> bool:
        parsed = urlsplit(url)
        expected = urlsplit(webhook_url)
        return (parsed.scheme, parsed.netloc, parsed.path) == (expected.scheme, expected.netloc, expected.path)

    def create(self, webhook_url: str) -> WebhookCreationResult:
        robots = self._robots()
        if not robots:
            return WebhookCreationResult(success=False, error="Create a Browse AI robot before enabling webhooks.")
        existing = {robot["id"]: self._hooks(robot["id"]) for robot in robots}
        tokens = {
            token
            for hooks in existing.values()
            for hook in hooks
            if self._matches(hook["url"], webhook_url) and hook["webhookEvent"] == "taskFinished"
            for token in parse_qs(urlsplit(hook["url"]).query).get("token", [])
        }
        if len(tokens) > 1:
            return WebhookCreationResult(
                success=False, error="Delete the existing Browse AI webhooks and reconnect them."
            )
        token = next(iter(tokens), secrets.token_urlsafe(32))
        parsed = urlsplit(webhook_url)
        query = parse_qs(parsed.query)
        query["token"] = [token]
        signed_url = urlunsplit(parsed._replace(query=urlencode(query, doseq=True)))
        with make_tracked_session(redact_values=(self.api_key, token)) as session:
            session.auth = BearerTokenAuth(self.api_key)
            for robot in robots:
                if any(
                    hook["url"] == signed_url and hook["webhookEvent"] == "taskFinished"
                    for hook in existing[robot["id"]]
                ):
                    continue
                response = session.post(
                    f"{BASE_URL}/{self._path(robot['id'])}",
                    json={"hookUrl": signed_url, "eventType": "taskFinished"},
                    timeout=30,
                )
                response.raise_for_status()
        return WebhookCreationResult(success=True, extra_inputs={"webhook_token": token})

    def info(self, webhook_url: str) -> ExternalWebhookInfo:
        robots = self._robots()
        matches = {
            robot["id"]: [
                hook
                for hook in self._hooks(robot["id"])
                if self._matches(hook["url"], webhook_url)
                and hook["webhookEvent"] == "taskFinished"
                and parse_qs(urlsplit(hook["url"]).query).get("token")
            ]
            for robot in robots
        }
        exists = any(matches.values())
        return ExternalWebhookInfo(
            exists=exists,
            url=webhook_url if exists else None,
            enabled_events=["taskFinished"] if exists else [],
            status="active" if robots and all(matches.values()) else "incomplete",
        )

    def delete(self, webhook_url: str) -> WebhookDeletionResult:
        with make_tracked_session(redact_values=(self.api_key,)) as session:
            session.auth = BearerTokenAuth(self.api_key)
            for robot in self._robots():
                for hook in self._hooks(robot["id"]):
                    if not self._matches(hook["url"], webhook_url):
                        continue
                    response = session.delete(f"{BASE_URL}/{self._path(robot['id'])}/{UUID(hook['id'])}", timeout=30)
                    if response.status_code != 404:
                        response.raise_for_status()
        return WebhookDeletionResult(success=True)
