import dataclasses
from collections.abc import AsyncIterable, Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

import orjson
import pyarrow as pa
import requests
from asgiref.sync import async_to_sync
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.settings import (
    PRODUCTION_BASE_URL,
    SANDBOX_BASE_URL,
    YOUSIGN_ENDPOINTS,
    YousignEndpointConfig,
    all_webhook_events,
)

REQUEST_TIMEOUT_SECONDS = 30

SANDBOX_ENVIRONMENT = "sandbox"

WEBHOOK_PERMISSION_ERROR = (
    "Your Yousign API key isn't allowed to manage webhook subscriptions. Use an API key with "
    "full-access permissions, or create the webhook manually."
)


@dataclasses.dataclass
class YousignResumeConfig:
    # `after` cursor of the next page to fetch on the endpoint being synced.
    cursor: str


def base_url_for_environment(environment: str | None) -> str:
    return SANDBOX_BASE_URL if environment == SANDBOX_ENVIRONMENT else PRODUCTION_BASE_URL


def _client_config(api_key: str, environment: str | None) -> ClientConfig:
    return {
        "base_url": base_url_for_environment(environment),
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
    }


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Yousign paginates with an `after` query param; the body carries `meta.next_cursor`
    # (null on the last page).
    return JSONResponseCursorPaginator(cursor_path="meta.next_cursor", cursor_param="after")


def _date_filter_value(value: Any) -> str | None:
    """Format an incremental watermark for Yousign's `<field>[after]=yyyy-mm-dd` filters.

    The filters are date-granular and it's undocumented whether `after` is inclusive, so back
    off one day from the watermark — the overlap re-syncs at most one extra day and merge
    dedupes on the primary key.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        as_date = value.date()
    elif isinstance(value, date):
        as_date = value
    elif isinstance(value, int | float):
        as_date = datetime.fromtimestamp(value, tz=UTC).date()
    else:
        try:
            as_date = dateutil_parser.parse(str(value)).date()
        except (ValueError, OverflowError):
            return None
    return (as_date - timedelta(days=1)).isoformat()


# Signer fields that let the holder act as the signer. `signature_link` is the URL a signer
# follows to sign, and Yousign's `no_otp` authentication mode makes it directly usable without
# any second factor — so anyone granted access to the warehouse table (a broader set than the
# Yousign account) could open it and sign. Strip these before any row reaches the warehouse.
SIGNER_CAPABILITY_FIELDS = ("signature_link",)


def _scrub_signer_capabilities(signer: dict[str, Any]) -> dict[str, Any]:
    for field_name in SIGNER_CAPABILITY_FIELDS:
        signer.pop(field_name, None)
    return signer


def _scrub_signature_request_row(row: dict[str, Any]) -> dict[str, Any]:
    # Signature request rows embed a `signers` array whose entries carry the same signing links.
    signers = row.get("signers")
    if isinstance(signers, list):
        for signer in signers:
            if isinstance(signer, dict):
                _scrub_signer_capabilities(signer)
    return row


def _row_transform_for(config: YousignEndpointConfig) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if config.name == "signers":
        return _scrub_signer_capabilities
    if config.name == "signature_requests":
        return _scrub_signature_request_row
    return None


def get_resource(
    config: YousignEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: str | None,
) -> EndpointResource:
    params: dict[str, Any] = {"limit": config.page_size, **config.params}

    if should_use_incremental_field:
        allowed_fields = {f["field"] for f in config.incremental_fields}
        field = incremental_field or config.default_incremental_field
        if field not in allowed_fields:
            raise ValueError(f"Yousign endpoint '{config.name}' does not support incremental field '{field}'")
        params[f"{field}[after]"] = {
            "type": "incremental",
            "cursor_path": field,
            "initial_value": None,
            "convert": _date_filter_value,
        }

    endpoint: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": config.data_selector,
        "paginator": _cursor_paginator() if config.paginated else SinglePagePaginator(),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _make_source_response(
    config: YousignEndpointConfig, items_fn: Callable[[], Iterable[Any] | AsyncIterable[Any]]
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_key if isinstance(config.primary_key, list) else [config.primary_key],
        # Yousign exposes no sort param and pages arrive newest-first (observed, undocumented),
        # so never declare "asc" — the pipeline would checkpoint the incremental watermark at
        # ≈now after the first batch.
        sort_mode="desc",
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def yousign_source(
    api_key: str,
    environment: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[YousignResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = YOUSIGN_ENDPOINTS[endpoint]
    client_config = _client_config(api_key, environment)
    row_transform = _row_transform_for(config)

    if webhook_source_manager is not None and config.supports_webhooks:
        if async_to_sync(webhook_source_manager.webhook_enabled)():
            manager = webhook_source_manager
            return _make_source_response(
                config, lambda: manager.get_items(table_transformer=make_webhook_table_transformer())
            )

    if config.fanout is not None:
        parent_config = YOUSIGN_ENDPOINTS[config.fanout.parent_name]
        # Fan-out syncs are full refresh (child endpoints have no timestamp filter) and are not
        # resumable — build_dependent_resource re-fetches the parent list on retry and merge
        # dedupes re-pulled rows.
        dependent_resource = cast(
            Resource,
            build_dependent_resource(
                endpoint_configs=YOUSIGN_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
                page_size_param="limit",
                parent_endpoint_extra={
                    "paginator": _cursor_paginator(),
                    "data_selector": parent_config.data_selector,
                },
                child_endpoint_extra={
                    "paginator": SinglePagePaginator(),
                    "data_selector": config.data_selector,
                },
            ),
        )
        if row_transform is not None:
            dependent_resource = dependent_resource.add_map(row_transform)
        items = cast(Iterable[Any], dependent_resource)
        return _make_source_response(config, lambda: items)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [get_resource(config, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(YousignResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    if row_transform is not None:
        resource = resource.add_map(row_transform)
    return _make_source_response(config, lambda: resource)


def validate_credentials(
    api_key: str, environment: str | None, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Probe the users list — a cheap organization-scoped read available on every plan."""
    if not api_key:
        return False, "Missing Yousign API key"

    base_url = base_url_for_environment(environment)
    try:
        response = _make_session(api_key).get(f"{base_url}/users", params={"limit": 1}, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        return False, f"Could not connect to Yousign: {e}"

    if response.status_code == 401:
        return False, (
            "Yousign rejected the API key. Check the key is correct, has not been revoked, and "
            "matches the selected environment — sandbox keys cannot access the production API "
            "and vice versa."
        )
    if response.status_code == 403:
        # Workspace-scoped keys may lack access to some endpoints; don't block source-create on
        # one missing permission.
        if schema_name is not None:
            return False, "Your Yousign API key does not have permission to read this data."
        return True, None
    if not response.ok:
        return False, f"Yousign returned an unexpected status ({response.status_code})"
    return True, None


def _make_session(api_key: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
    )


def _maybe_json_loads(value: Any) -> Any:
    """Nested webhook payload fields round-trip through parquet as JSON strings."""
    if isinstance(value, str):
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError:
            return value
    return value


def _event_time(row: dict[str, Any]) -> int:
    try:
        return int(row.get("event_time") or 0)
    except (TypeError, ValueError):
        return 0


def make_webhook_table_transformer() -> Callable[[pa.Table], pa.Table]:
    def transform(table: pa.Table) -> pa.Table:
        # Webhook rows are full event envelopes; reshape each to the signature request object so
        # they merge into the same table as pulled rows. Delta merge only dedupes across syncs,
        # so keep one row per id within the batch — the one with the greatest event_time (ties
        # go to arrival order, which the manager reads oldest-first).
        best_by_id: dict[Any, tuple[int, dict[str, Any]]] = {}
        for raw_row in table.to_pylist():
            data = _maybe_json_loads(raw_row.get("data"))
            if not isinstance(data, dict):
                continue
            signature_request = _maybe_json_loads(data.get("signature_request"))
            if not isinstance(signature_request, dict) or signature_request.get("id") is None:
                continue
            _scrub_signature_request_row(signature_request)
            event_time = _event_time(raw_row)
            existing = best_by_id.get(signature_request["id"])
            if existing is None or event_time >= existing[0]:
                best_by_id[signature_request["id"]] = (event_time, signature_request)
        return table_from_py_list([row for _, row in best_by_id.values()])

    return transform


def _webhooks_url(environment: str | None) -> str:
    # Webhook management is documented against the production API (sandbox subscriptions are
    # created with `sandbox: true`), but keys are environment-scoped, so a sandbox key can only
    # reach the sandbox host. Use the host matching the source's environment; if Yousign rejects
    # management calls there, the failure surfaces and the user follows the manual setup steps.
    return f"{base_url_for_environment(environment)}/webhooks"


def _list_webhooks(api_key: str, environment: str | None) -> list[dict[str, Any]]:
    response = _make_session(api_key).get(_webhooks_url(environment), timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def _find_webhook_by_url(api_key: str, environment: str | None, webhook_url: str) -> dict[str, Any] | None:
    return next((wh for wh in _list_webhooks(api_key, environment) if wh.get("endpoint") == webhook_url), None)


def create_webhook(
    api_key: str, environment: str | None, webhook_url: str, logger: FilteringBoundLogger
) -> WebhookCreationResult:
    try:
        body = {
            "endpoint": webhook_url,
            "description": "PostHog data warehouse",
            "sandbox": environment == SANDBOX_ENVIRONMENT,
            "subscribed_events": all_webhook_events(),
            "scopes": ["*"],
            "auto_retry": True,
            "enabled": True,
        }
        response = _make_session(api_key).post(_webhooks_url(environment), json=body, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code in (401, 403):
            return WebhookCreationResult(success=False, error=WEBHOOK_PERMISSION_ERROR)
        if not response.ok:
            raise Exception(f"Yousign webhook creation failed with HTTP {response.status_code}")

        data = response.json() if response.content else {}
        secret = data.get("secret_key") if isinstance(data, dict) else None
        if secret:
            return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
        # The signing key is visible on the subscription in the Yousign app if the API response
        # didn't carry it.
        return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])
    except Exception as e:
        logger.exception(f"Yousign: failed to create webhook: {e}")
        return WebhookCreationResult(success=False, error=f"Failed to create Yousign webhook automatically: {e}")


def update_webhook_events(
    api_key: str, environment: str | None, webhook_url: str, desired_events: list[str], logger: FilteringBoundLogger
) -> WebhookSyncResult:
    try:
        existing = _find_webhook_by_url(api_key, environment, webhook_url)
        if existing is None or existing.get("id") is None:
            return WebhookSyncResult(success=False, error="No Yousign webhook found for this source's webhook URL.")

        if sorted(existing.get("subscribed_events") or []) == sorted(desired_events):
            return WebhookSyncResult(success=True)

        response = _make_session(api_key).patch(
            f"{_webhooks_url(environment)}/{existing['id']}",
            json={"subscribed_events": desired_events},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code in (401, 403):
            return WebhookSyncResult(success=False, error=WEBHOOK_PERMISSION_ERROR)
        if not response.ok:
            raise Exception(f"Yousign webhook update failed with HTTP {response.status_code}")
        return WebhookSyncResult(success=True)
    except Exception as e:
        logger.exception(f"Yousign: failed to sync webhook events: {e}")
        return WebhookSyncResult(success=False, error=f"Failed to update Yousign webhook events: {e}")


def get_external_webhook_info(api_key: str, environment: str | None, webhook_url: str) -> ExternalWebhookInfo:
    try:
        existing = _find_webhook_by_url(api_key, environment, webhook_url)
        if existing is None:
            return ExternalWebhookInfo(exists=False)
        subscribed_events = existing.get("subscribed_events")
        return ExternalWebhookInfo(
            exists=True,
            url=existing.get("endpoint"),
            enabled_events=subscribed_events if isinstance(subscribed_events, list) else None,
            status="enabled" if existing.get("enabled") else "disabled",
            description=existing.get("description"),
            created_at=existing.get("created_at"),
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=f"Failed to check Yousign webhook: {e}")


def delete_webhook(
    api_key: str, environment: str | None, webhook_url: str, logger: FilteringBoundLogger
) -> WebhookDeletionResult:
    try:
        existing = _find_webhook_by_url(api_key, environment, webhook_url)
        if existing is None or existing.get("id") is None:
            # Nothing to delete — the desired end state already holds.
            return WebhookDeletionResult(success=True)

        response = _make_session(api_key).delete(
            f"{_webhooks_url(environment)}/{existing['id']}", timeout=REQUEST_TIMEOUT_SECONDS
        )
        if response.status_code in (401, 403):
            return WebhookDeletionResult(success=False, error=WEBHOOK_PERMISSION_ERROR)
        if not response.ok and response.status_code != 404:
            raise Exception(f"Yousign webhook deletion failed with HTTP {response.status_code}")
        return WebhookDeletionResult(success=True)
    except Exception as e:
        logger.exception(f"Yousign: failed to delete webhook: {e}")
        return WebhookDeletionResult(success=False, error=f"Failed to delete Yousign webhook: {e}")
