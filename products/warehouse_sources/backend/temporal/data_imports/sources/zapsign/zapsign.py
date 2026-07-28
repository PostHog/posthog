"""Thin ZapSign API client used by the data warehouse source.

Spec: https://docs.zapsign.com.br

Everything in this module routes through the shared ``rest_source`` framework (tracked, retrying
transport) or ``make_tracked_session`` directly, so outbound calls show up in our HTTP logs, OTel
metrics, and sample-capture pipeline.
"""

import secrets
import datetime
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import pyarrow as pa
import structlog
from asgiref.sync import async_to_sync
from dateutil import parser as dateutil_parser
from requests.exceptions import HTTPError, RequestException

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.settings import (
    DOCUMENT_DETAIL_PATH,
    DOCUMENTS_RESOURCE,
    ENDPOINT_PATHS,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    SIGNERS_RESOURCE,
    TEMPLATES_RESOURCE,
    TIMESTAMP_COLUMNS,
    ZAPSIGN_BASE_URL,
    ZAPSIGN_SANDBOX_BASE_URL,
)

LOGGER = structlog.get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 30

WEBHOOK_CREATE_PATH = "/api/v1/user/company/webhook/"


@dataclasses.dataclass
class ZapSignResumeConfig:
    """Resume state for one endpoint's pagination.

    ``paginator_state`` holds whatever the framework paginator checkpoints: ``{"next_url": ...}``
    for the top-level list endpoints, or the fan-out state dict
    (``{"completed": [...], "current": ..., "child_state": ...}``) for signers.
    """

    endpoint: str
    paginator_state: dict[str, Any] | None = None


def base_url_for_environment(environment: str | None) -> str:
    return ZAPSIGN_SANDBOX_BASE_URL if environment == "sandbox" else ZAPSIGN_BASE_URL


def _to_created_from(value: Any) -> str | None:
    """Format the incremental watermark as ZapSign's ``created_from`` date (``YYYY-MM-DD``).

    The filter is date-granular and inclusive, so the watermark's own day is re-fetched on every
    incremental run — the merge on ``token`` dedupes those rows.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime | datetime.date):
        return value.strftime("%Y-%m-%d")
    parsed = dateutil_parser.parse(str(value))
    return parsed.strftime("%Y-%m-%d")


def _timestamp_columns(endpoint: str) -> dict[str, dict[str, Any]]:
    return {column: {"data_type": "timestamp"} for column in TIMESTAMP_COLUMNS.get(endpoint, ())}


def _documents_resource(should_use_incremental_field: bool) -> EndpointResource:
    return {
        "name": DOCUMENTS_RESOURCE,
        "table_name": DOCUMENTS_RESOURCE,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": ENDPOINT_PATHS[DOCUMENTS_RESOURCE],
            "params": {
                # Ascending creation order so the pipeline's incremental watermark advances safely.
                "sort_order": "asc",
                # Embeds each document's signer array — and guarantees the documented
                # `{count, next, previous, results}` envelope shape.
                "include_signers": "true",
                "created_from": {
                    "type": "incremental",
                    "cursor_path": "created_at",
                    "initial_value": None,
                    "convert": _to_created_from,
                }
                if should_use_incremental_field
                else None,
            },
            "data_selector": "results",
            # A missing `results` key means the response shape changed — fail loud instead of
            # silently syncing zero rows.
            "data_selector_required": True,
        },
        "columns": _timestamp_columns(DOCUMENTS_RESOURCE),
        "table_format": "delta",
    }


def _templates_resource() -> EndpointResource:
    # Templates expose no filter or sort params — full refresh only.
    return {
        "name": TEMPLATES_RESOURCE,
        "table_name": TEMPLATES_RESOURCE,
        "write_disposition": "replace",
        "endpoint": {
            "path": ENDPOINT_PATHS[TEMPLATES_RESOURCE],
            "data_selector": "results",
            "data_selector_required": True,
        },
        "columns": _timestamp_columns(TEMPLATES_RESOURCE),
        "table_format": "delta",
    }


def _signers_resources() -> list[EndpointResource]:
    """Parent documents list + per-document detail fan-out that extracts the signer arrays."""
    parent: EndpointResource = {
        "name": DOCUMENTS_RESOURCE,
        "table_name": DOCUMENTS_RESOURCE,
        "write_disposition": "replace",
        "endpoint": {
            "path": ENDPOINT_PATHS[DOCUMENTS_RESOURCE],
            "params": {"sort_order": "asc"},
            "data_selector": "results",
            "data_selector_required": True,
        },
        "table_format": "delta",
    }
    child: EndpointResource = {
        "name": SIGNERS_RESOURCE,
        "table_name": SIGNERS_RESOURCE,
        "write_disposition": "replace",
        "include_from_parent": ["token"],
        "endpoint": {
            "path": DOCUMENT_DETAIL_PATH,
            "params": {
                "token": {
                    "type": "resolve",
                    "resource": DOCUMENTS_RESOURCE,
                    "field": "token",
                },
            },
            "data_selector": "signers",
        },
        "columns": _timestamp_columns(SIGNERS_RESOURCE),
        "table_format": "delta",
    }
    return [parent, child]


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Reshape buffered webhook deliveries into document rows ready to merge on ``token``.

    ZapSign's document webhooks (``doc_created``/``doc_signed``/``doc_refused``/``doc_deleted``)
    carry the full document object plus event metadata. Delta merge only de-dupes across syncs, so
    one batch holding several events for the same document must be collapsed here — we keep the
    row with the greatest ``last_update_at``. Event-only fields are dropped so the row shape
    matches the pull API, and the timestamp columns are parsed to real datetimes to line up with
    the pull path's column types.
    """
    rows = table.to_pylist()
    best_by_token: dict[str, tuple[float, dict[str, Any]]] = {}

    for row in rows:
        token = row.get("token")
        if not token:
            continue

        row = dict(row)
        row.pop("event_type", None)
        row.pop("signer_who_signed", None)

        for column in TIMESTAMP_COLUMNS[DOCUMENTS_RESOURCE]:
            value = row.get(column)
            if isinstance(value, str):
                try:
                    row[column] = dateutil_parser.parse(value)
                except (ValueError, OverflowError):
                    row[column] = None

        updated = row.get("last_update_at") or row.get("created_at")
        sort_key = updated.timestamp() if isinstance(updated, datetime.datetime) else 0.0

        existing = best_by_token.get(token)
        if existing is None or sort_key >= existing[0]:
            best_by_token[token] = (sort_key, row)

    return table_from_py_list([row for _, row in best_by_token.values()])


def zapsign_source(
    api_token: str,
    environment: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZapSignResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    base_url = base_url_for_environment(environment)

    client_config: ClientConfig = {
        "base_url": base_url,
        "auth": {"type": "bearer", "token": api_token},
        # ZapSign paginates DRF-style: the envelope's `next` field carries the full next-page URL.
        "paginator": {"type": "json_response", "next_url_path": "next"},
        # Pin pagination/resume URLs to the API host so a tampered `next` link can't exfiltrate
        # the bearer token.
        "allowed_hosts": [],
    }

    resources: list[str | EndpointResource]
    if endpoint == SIGNERS_RESOURCE:
        resources = [*_signers_resources()]
    elif endpoint == DOCUMENTS_RESOURCE:
        resources = [_documents_resource(should_use_incremental_field)]
    elif endpoint == TEMPLATES_RESOURCE:
        resources = [_templates_resource()]
    else:
        raise ValueError(f"Unknown ZapSign endpoint: {endpoint}")

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": resources,
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only honor state written by this endpoint — replaying a documents cursor against
        # templates would skip rows.
        if resume is not None and resume.endpoint == endpoint and resume.paginator_state:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes on the
        # primary key) rather than skipping it. The Redis TTL handles cleanup on completion.
        if state:
            resumable_source_manager.save_state(ZapSignResumeConfig(endpoint=endpoint, paginator_state=state))

    framework_resources = rest_api_resources(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    resource = next(r for r in framework_resources if r.name == endpoint)

    webhook_enabled = False
    if endpoint == DOCUMENTS_RESOURCE:
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    def items() -> Any:
        if webhook_enabled:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)

        def pages() -> Iterator[list[dict[str, Any]]]:
            for page in resource:
                yield [row for row in page if isinstance(row, dict)]

        return pages()

    partition_keys = PARTITION_KEYS.get(endpoint)
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=PRIMARY_KEYS[endpoint],
        column_hints=resource.column_hints,
        sort_mode="asc",
        partition_keys=partition_keys,
        partition_mode="datetime" if partition_keys else None,
        partition_format="month" if partition_keys else None,
        partition_count=1 if partition_keys else None,
        partition_size=1 if partition_keys else None,
    )


def validate_credentials(api_token: str, environment: str | None) -> tuple[bool, str | None]:
    """One cheap probe against the documents list to confirm the token is genuine.

    ZapSign responds 403 (not 401) with a ``detail`` message when the token is missing or invalid.
    """
    base_url = base_url_for_environment(environment)
    session = make_tracked_session(redact_values=(api_token,))
    try:
        response = session.get(
            f"{base_url}/api/v1/docs/",
            params={"page": 1},
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except RequestException as e:
        return False, f"Could not reach ZapSign: {e}"

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, (
            "ZapSign rejected the API token. Copy a valid token from "
            "Settings > Integrations > ZapSign API and try again."
        )
    return False, f"ZapSign API returned an unexpected status ({response.status_code})."


def create_webhook(api_token: str, environment: str | None, webhook_url: str) -> WebhookCreationResult:
    """Register a ZapSign webhook pointing at ``webhook_url`` for all document events.

    ``type: ""`` subscribes to every document event (created, signed, refused, deleted) — it
    deliberately excludes email-bounce events, which aren't document-shaped. ZapSign echoes any
    custom headers on each delivery, so we generate a secret ``Authorization`` header value and
    return it via ``extra_inputs`` for the Hog template to verify.
    """
    base_url = base_url_for_environment(environment)
    header_value = f"Bearer {secrets.token_urlsafe(32)}"
    session = make_tracked_session(redact_values=(api_token, header_value))

    try:
        response = session.post(
            f"{base_url}{WEBHOOK_CREATE_PATH}",
            json={
                "url": webhook_url,
                "type": "",
                "headers": [{"name": "Authorization", "value": header_value}],
            },
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except HTTPError as e:
        LOGGER.warning("Failed to register ZapSign webhook", error=str(e))
        status_code = e.response.status_code if e.response is not None else None
        if status_code in (401, 403):
            return WebhookCreationResult(
                success=False,
                error="ZapSign rejected the API token while registering the webhook.",
            )
        return WebhookCreationResult(success=False, error=f"ZapSign API error ({status_code}).")
    except RequestException as e:
        LOGGER.warning("Could not reach ZapSign to register webhook", error=str(e))
        return WebhookCreationResult(success=False, error=f"Could not reach ZapSign: {e}")

    return WebhookCreationResult(success=True, extra_inputs={"authorization_header": header_value})


def delete_webhook() -> WebhookDeletionResult:
    # ZapSign's delete endpoint needs the webhook id returned at creation, and there is no list
    # endpoint to rediscover it — so automatic deletion isn't possible.
    return WebhookDeletionResult(
        success=False,
        error=(
            "ZapSign doesn't support looking up webhooks via its API, so PostHog can't remove it "
            "automatically. Delete it in ZapSign under Settings > Integrations > ZapSign API."
        ),
    )
