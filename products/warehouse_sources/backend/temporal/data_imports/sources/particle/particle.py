"""Particle IoT device cloud source.

Particle's Cloud API lives at https://api.particle.io and authenticates with a bearer access token.
The recommended credential is an API user token: it can be scoped to one product and never expires.

Two tables:
- `devices` is pulled from the device list. Without a product ID it reads the devices the token's
  user owns (`/v1/devices`, not paginated). With a product ID it reads the product fleet
  (`/v1/products/:id/devices`, paginated with `page`/`perPage` and `meta.total_pages`).
- `events` only fills from webhooks. Particle keeps no event history to page through, so
  `create_webhook` registers one Particle webhook per event name prefix (Particle matches on prefix
  and has no wildcard). The webhook template also captures each delivery as a PostHog event.

Particle delivers webhooks at least once and retries a failed delivery twice before dropping it.
"""

import logging
import secrets
from typing import Any, cast

import pyarrow as pa
from requests import Response, Session

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.particle import (
    ParticleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.particle.settings import (
    DEVICES_PAGE_SIZE,
    DEVICES_SCHEMA_NAME,
    PARTICLE_BASE_URL,
    WEBHOOK_BODY,
    WEBHOOK_QUERY,
    WEBHOOK_SECRET_HEADER,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 30

WEBHOOK_AUTH_ERROR = (
    "Your Particle access token can't manage integrations. Use an API user token with the "
    "`integrations:list`, `integrations:create` and `integrations:remove` scopes, then try again."
)

NO_PREFIXES_ERROR = "Add at least one Particle event name prefix so PostHog knows which events to receive."


def _product_id(config: ParticleSourceConfig) -> str | None:
    product_id = (config.product_id or "").strip()
    return product_id or None


def event_prefixes(config: ParticleSourceConfig) -> list[str]:
    """Configured prefixes, in order, without any that a broader prefix already covers.

    Particle matches on prefix, so a hook for `env/` already receives `env/temp`; a second hook
    for `env/temp` would deliver (and capture) every such publish twice.
    """
    requested = [prefix.strip() for prefix in (config.event_prefixes or "").split(",")]
    requested = [prefix for prefix in requested if prefix]
    prefixes: list[str] = []
    for prefix in requested:
        if any(other != prefix and prefix.startswith(other) for other in requested):
            continue
        if prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def _devices_path(config: ParticleSourceConfig) -> str:
    product_id = _product_id(config)
    return f"/v1/products/{product_id}/devices" if product_id else "/v1/devices"


def _integrations_url(config: ParticleSourceConfig) -> str:
    product_id = _product_id(config)
    if product_id:
        return f"{PARTICLE_BASE_URL}/v1/products/{product_id}/integrations"
    return f"{PARTICLE_BASE_URL}/v1/integrations"


def _session(config: ParticleSourceConfig) -> Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {config.access_token}"},
        # Integration objects echo back the headers we set, which carry the shared secret.
        capture=False,
        redact_values=(config.access_token,),
    )


def probe_devices(config: ParticleSourceConfig) -> int | None:
    """Status of a one-device read, or `None` when Particle can't be reached."""
    params = {"perPage": 1} if _product_id(config) else None
    try:
        response = _session(config).get(
            f"{PARTICLE_BASE_URL}{_devices_path(config)}", params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return None
    return response.status_code


def particle_source(config: ParticleSourceConfig, team_id: int, job_id: str) -> SourceResponse:
    endpoint: Endpoint
    if _product_id(config):
        endpoint = {
            "path": _devices_path(config),
            "params": {"perPage": DEVICES_PAGE_SIZE},
            "data_selector": "devices",
            "paginator": cast(
                PaginatorConfig, {"type": "page_number", "base_page": 1, "total_path": "meta.total_pages"}
            ),
        }
    else:
        endpoint = {"path": _devices_path(config), "paginator": "single_page"}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PARTICLE_BASE_URL,
            "auth": {"type": "bearer", "token": config.access_token},
            "allow_redirects": False,
            "allowed_hosts": [],
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
        },
        "resources": [{"name": DEVICES_SCHEMA_NAME, "endpoint": endpoint, "write_disposition": "replace"}],
    }
    resource = rest_api_resource(rest_config, team_id, job_id, None)
    return SourceResponse(name=DEVICES_SCHEMA_NAME, items=lambda: resource, primary_keys=["id"])


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Keep the first delivery of each Particle event.

    Delta merge de-dupes across syncs on the primary key, but a retried delivery can land in the
    same batch as the original. A row without an event ID has nothing to merge on, so it is dropped.
    """
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for row in table.to_pylist():
        event_id = row.get("event_id")
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        rows.append(row)
    return table_from_py_list(rows)


def _list_our_hooks(session: Session, config: ParticleSourceConfig, webhook_url: str) -> list[dict[str, Any]]:
    response = session.get(_integrations_url(config), timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, list):
        return []
    return [
        hook
        for hook in body
        if isinstance(hook, dict)
        and hook.get("integration_type") == "Webhook"
        and hook.get("url") == webhook_url
        and hook.get("id") is not None
    ]


def _raise_for_status(response: Response, action: str) -> None:
    if not response.ok:
        raise Exception(f"Particle webhook {action} failed with HTTP {response.status_code}: {response.text[:200]}")


def _is_auth_error(response: Response) -> bool:
    return response.status_code in (401, 403)


def create_webhook(config: ParticleSourceConfig, webhook_url: str) -> WebhookCreationResult:
    prefixes = event_prefixes(config)
    if not prefixes:
        return WebhookCreationResult(success=False, error=NO_PREFIXES_ERROR)

    created_ids: list[str] = []
    session = _session(config)
    base_url = _integrations_url(config)
    try:
        stale_hooks = _list_our_hooks(session, config, webhook_url)

        # The secret is only stored when every hook exists, so a hook created before a later
        # failure would deliver with a secret PostHog never accepts. Create first, and remove the
        # earlier setup's hooks last, so a failed setup leaves the previous configuration working.
        secret = secrets.token_urlsafe(32)
        for prefix in prefixes:
            response = session.post(
                base_url,
                json={
                    "integration_type": "Webhook",
                    "name": f"PostHog ({prefix})",
                    "event": prefix,
                    "url": webhook_url,
                    "requestType": "POST",
                    "noDefaults": True,
                    "query": WEBHOOK_QUERY,
                    "body": WEBHOOK_BODY,
                    "headers": {"Content-Type": "application/json", WEBHOOK_SECRET_HEADER: secret},
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if _is_auth_error(response):
                _delete_hooks(session, base_url, created_ids)
                return WebhookCreationResult(success=False, error=WEBHOOK_AUTH_ERROR)
            _raise_for_status(response, "creation")
            hook_id = response.json().get("id") if response.content else None
            if hook_id is not None:
                created_ids.append(str(hook_id))

        # Every hook carries the same fresh secret, so hooks left by an earlier setup are removed
        # rather than left delivering with a secret the webhook function no longer accepts.
        for hook in stale_hooks:
            response = session.delete(f"{base_url}/{hook['id']}", timeout=REQUEST_TIMEOUT_SECONDS)
            if _is_auth_error(response):
                _delete_hooks(session, base_url, created_ids)
                return WebhookCreationResult(success=False, error=WEBHOOK_AUTH_ERROR)
            _raise_for_status(response, "cleanup")

        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
    except Exception as e:
        logger.exception(f"Particle: failed to create webhook: {e}")
        _delete_hooks(session, base_url, created_ids)
        return WebhookCreationResult(
            success=False, error=f"Failed to create the Particle webhook: {e}. Please create it manually below."
        )


def _delete_hooks(session: Session, base_url: str, hook_ids: list[str]) -> None:
    """Best-effort removal of hooks this setup created before it failed."""
    for hook_id in hook_ids:
        try:
            session.delete(f"{base_url}/{hook_id}", timeout=REQUEST_TIMEOUT_SECONDS)
        except Exception as e:
            logger.warning(f"Particle: failed to remove webhook {hook_id} after a failed setup: {e}")


def get_external_webhook_info(config: ParticleSourceConfig, webhook_url: str) -> ExternalWebhookInfo:
    try:
        hooks = _list_our_hooks(_session(config), config, webhook_url)
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=f"Failed to check the Particle webhook: {e}")
    if not hooks:
        return ExternalWebhookInfo(exists=False)
    return ExternalWebhookInfo(
        exists=True,
        url=webhook_url,
        enabled_events=[str(hook.get("event")) for hook in hooks],
        status="enabled",
    )


def delete_webhook(config: ParticleSourceConfig, webhook_url: str) -> WebhookDeletionResult:
    try:
        session = _session(config)
        base_url = _integrations_url(config)
        for hook in _list_our_hooks(session, config, webhook_url):
            response = session.delete(f"{base_url}/{hook['id']}", timeout=REQUEST_TIMEOUT_SECONDS)
            if _is_auth_error(response):
                return WebhookDeletionResult(success=False, error=WEBHOOK_AUTH_ERROR)
            _raise_for_status(response, "deletion")
        return WebhookDeletionResult(success=True)
    except Exception as e:
        logger.exception(f"Particle: failed to delete webhook: {e}")
        return WebhookDeletionResult(success=False, error=f"Failed to delete the Particle webhook: {e}")
