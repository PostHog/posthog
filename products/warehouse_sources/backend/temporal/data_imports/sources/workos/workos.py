import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import orjson
import pyarrow as pa
from asgiref.sync import async_to_sync
from requests import Request, Response
from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import (
    WEBHOOK_SCHEMA_NAMES,
    WORKOS_ENDPOINTS,
)

BASE_URL = "https://api.workos.com"
WEBHOOK_ENDPOINTS_PATH = "/webhook_endpoints"
# WorkOS lists 10 endpoints per page by default, so an account with more than that can hide
# ours behind the first page. 100 is the documented maximum.
WEBHOOK_ENDPOINTS_PAGE_SIZE = 100

# Delete events carry a soft tombstone because a webhook sync merges on `id` and can never
# remove a row. On the tables that can switch to webhook sync, the polled backfill writes these
# columns too, so a query that filters on `workos_deleted` covers every row in the table rather
# than only the rows a webhook has touched.
DELETED_COLUMN = "workos_deleted"
DELETED_AT_COLUMN = "workos_deleted_at"


@dataclasses.dataclass
class WorkOSResumeConfig:
    """Resume state for WorkOS endpoints.

    Every WorkOS list endpoint uses cursor pagination keyed on the ``after``
    object ID returned in ``list_metadata.after``. The checkpoint is just that
    cursor. On resume we start fetching from the saved cursor (at-least-once
    semantics): the page whose cursor did not persist before a crash is
    re-yielded and deduped by the ``id`` primary key.
    """

    after: str


class WorkOSPaginator(BasePaginator):
    """Cursor paginator for the WorkOS API.

    WorkOS returns ``{"data": [...], "list_metadata": {"before": ..., "after": ...}}``.
    The next page is fetched by passing ``after=<last object id>``; pagination
    ends when ``list_metadata.after`` is null.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Emit the seeded cursor on the first request so resume starts from the
        # saved page. Fresh runs (no cursor) omit the param.
        if self._after is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._after

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        try:
            body = response.json()
        except ValueError:
            body = None

        next_after = None
        if isinstance(body, dict):
            metadata = body.get("list_metadata")
            if isinstance(metadata, dict):
                next_after = metadata.get("after")

        if next_after:
            self._after = next_after
            self._has_next_page = True
        else:
            self._after = None
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._has_next_page and self._after is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._after

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # ``_after`` retains the previous page's cursor once exhausted, so guard on
        # ``_has_next_page`` to avoid handing back a stale checkpoint that would
        # re-fetch an already-processed page on resume.
        if not self._has_next_page or self._after is None:
            return None
        return {"after": self._after}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after:
            self._after = after
            self._has_next_page = True


def get_resource(name: str) -> EndpointResource:
    config = WORKOS_ENDPOINTS[name]

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": "data",
        "params": {
            "limit": config.page_size,
            # Stable creation-ordered pagination so the cursor walks deterministically.
            # Must be "desc" (the WorkOS SDK default): the high-volume directory_users
            # and directory_groups list endpoints reject "order=asc" with a 422, while
            # "desc" is accepted on every WorkOS list endpoint.
            "order": "desc",
        },
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate WorkOS API credentials with a cheap list call."""
    url = f"{BASE_URL}/organizations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = make_tracked_session().get(url, headers=headers, params={"limit": 1}, timeout=10)

        if response.status_code == 200:
            return True, None

        # A 403 still proves the key is genuine, because WorkOS rejects an invalid key with a
        # 401. Accept it at source-create so an account that cannot reach Organizations can
        # still sync the endpoints it does have. Sync-time 403s are handled by
        # get_non_retryable_errors().
        if response.status_code == 403:
            return True, None

        if response.status_code == 401:
            return False, "Your WorkOS API key is invalid or has been revoked."

        try:
            error_data = response.json()
            message = error_data.get("message")
            if message:
                return False, message
        except ValueError:
            pass

        return False, response.text
    except RequestException as e:
        return False, str(e)


def create_webhook(api_key: str, webhook_url: str, events: list[str]) -> WebhookCreationResult:
    """Register a WorkOS webhook and retain its one-time signing secret."""
    try:
        response = make_tracked_session().post(
            f"{BASE_URL}{WEBHOOK_ENDPOINTS_PATH}",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"endpoint_url": webhook_url, "events": events},
            timeout=10,
        )
        response.raise_for_status()
        signing_secret = response.json().get("secret")
        if not signing_secret:
            return WebhookCreationResult(
                success=False,
                error="WorkOS created the webhook but did not return a signing secret. Add the secret manually.",
                pending_inputs=["signing_secret"],
            )
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": signing_secret})
    except Exception as e:
        return WebhookCreationResult(
            success=False,
            error=f"Failed to create the WorkOS webhook: {e}. Please create it manually in WorkOS.",
        )


def _webhook_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _iterate_webhook_endpoints(api_key: str) -> Iterator[dict[str, Any]]:
    """Walk every registered webhook endpoint through WorkOS's `after` cursor."""
    session = make_tracked_session()
    after: Optional[str] = None
    while True:
        params: dict[str, Any] = {"limit": WEBHOOK_ENDPOINTS_PAGE_SIZE}
        if after:
            params["after"] = after

        response = session.get(
            f"{BASE_URL}{WEBHOOK_ENDPOINTS_PATH}", headers=_webhook_headers(api_key), params=params, timeout=10
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            return

        yield from (webhook for webhook in body.get("data") or [] if isinstance(webhook, dict))

        metadata = body.get("list_metadata")
        after = metadata.get("after") if isinstance(metadata, dict) else None
        if not after:
            return


def _matching_webhooks(api_key: str, webhook_url: str) -> list[dict[str, Any]]:
    return [webhook for webhook in _iterate_webhook_endpoints(api_key) if webhook.get("endpoint_url") == webhook_url]


def get_webhook_info(api_key: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        matching = _matching_webhooks(api_key, webhook_url)
        if not matching:
            return ExternalWebhookInfo(exists=False)
        return ExternalWebhookInfo(
            exists=True,
            url=webhook_url,
            enabled_events=sorted({event for webhook in matching for event in webhook.get("events", [])}),
            status=str(matching[0].get("status")) if matching[0].get("status") else None,
            created_at=str(matching[0].get("created_at")) if matching[0].get("created_at") else None,
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))


def sync_webhook_events(api_key: str, webhook_url: str, desired_events: list[str]) -> WebhookSyncResult:
    """Add any missing `desired_events` to the endpoints pointing at `webhook_url`.

    Events are merged, never removed, so an endpoint a user broadened by hand keeps its extras.
    """
    if not desired_events:
        return WebhookSyncResult(success=True)

    try:
        session = make_tracked_session()
        for webhook in _matching_webhooks(api_key, webhook_url):
            current = webhook.get("events") or []
            merged = sorted(set(current) | set(desired_events))
            if merged == sorted(current):
                continue

            response = session.patch(
                f"{BASE_URL}{WEBHOOK_ENDPOINTS_PATH}/{webhook.get('id')}",
                headers=_webhook_headers(api_key),
                json={"events": merged},
                timeout=10,
            )
            response.raise_for_status()
        return WebhookSyncResult(success=True)
    except Exception as e:
        return WebhookSyncResult(
            success=False,
            error=(
                f"Failed to update the WorkOS webhook events: {e}. "
                f"Please add these events manually in WorkOS: {', '.join(desired_events)}"
            ),
        )


def delete_webhook(api_key: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        session = make_tracked_session()
        for webhook in _matching_webhooks(api_key, webhook_url):
            webhook_id = webhook.get("id")
            if webhook_id:
                response = session.delete(
                    f"{BASE_URL}{WEBHOOK_ENDPOINTS_PATH}/{webhook_id}",
                    headers=_webhook_headers(api_key),
                    timeout=10,
                )
                response.raise_for_status()
        return WebhookDeletionResult(success=True)
    except Exception as e:
        return WebhookDeletionResult(success=False, error=f"Failed to delete the WorkOS webhook: {e}")


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Extract full WorkOS resources and preserve delete events as soft tombstones."""
    rows_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    rows = table.to_pylist()
    for event in rows:
        event_type = event.get("event")
        resource = event.get("data")
        if isinstance(resource, str):
            try:
                resource = orjson.loads(resource)
            except orjson.JSONDecodeError:
                continue
        if not isinstance(event_type, str) or not isinstance(resource, dict) or not resource.get("id"):
            continue

        deleted = event_type.endswith(".deleted")
        raw_created_at = event.get("created_at")
        created_at = raw_created_at if isinstance(raw_created_at, str) else ""
        resource = {
            **resource,
            DELETED_COLUMN: deleted,
            DELETED_AT_COLUMN: raw_created_at if deleted else None,
        }
        current = rows_by_id.get(str(resource["id"]))
        if current is None or created_at >= current[0]:
            rows_by_id[str(resource["id"])] = (created_at, resource)

    return table_from_py_list([row for _, row in rows_by_id.values()])


def workos_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorkOSResumeConfig],
    webhook_source_manager: WebhookSourceManager,
) -> SourceResponse:
    endpoint_config = WORKOS_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Content-Type": "application/json",
            },
            "paginator": WorkOSPaginator(),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    # Seed the paginator from the saved checkpoint when resuming.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.after:
            initial_paginator_state = {"after": resume_config.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # rest_client passes None once the paginator is exhausted; nothing to persist then.
        if state and state.get("after"):
            resumable_source_manager.save_state(WorkOSResumeConfig(after=str(state["after"])))

    webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    if endpoint in WEBHOOK_SCHEMA_NAMES:
        resource = resource.add_map(lambda row: {**row, DELETED_COLUMN: False, DELETED_AT_COLUMN: None})

    return SourceResponse(
        name=endpoint,
        items=lambda: (
            webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
            if webhook_enabled
            else resource
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
    )
