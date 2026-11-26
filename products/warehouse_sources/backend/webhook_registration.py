"""Whether a source has the webhook that its webhook-sync tables need.

A webhook-sync table gets its rows from a `warehouse_source_webhook` hog function for its source.
When no such function is enabled, the import worker polls the source API instead, and the API
warns the user. Both read the rule from this module, so they agree about the same source.
"""

import uuid
from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING, Any, Protocol

from django.db.models import QuerySet

from products.cdp.backend.facade.models import HogFunction
from products.warehouse_sources.backend.facade.types import ExternalDataSchemaSyncType, WebhookIssue

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookSource

WAREHOUSE_SOURCE_WEBHOOK_TYPE = "warehouse_source_webhook"


class WebhookSchemaState(Protocol):
    @property
    def source_id(self) -> uuid.UUID: ...

    @property
    def sync_type(self) -> str | None: ...

    @property
    def should_sync(self) -> bool: ...

    @property
    def deleted(self) -> bool | None: ...


def schema_needs_webhook(schema: WebhookSchemaState) -> bool:
    return schema.sync_type == ExternalDataSchemaSyncType.WEBHOOK and schema.should_sync and not schema.deleted


def _enabled_webhook_functions(team_id: int) -> QuerySet[HogFunction]:
    return HogFunction.objects.filter(team_id=team_id, type=WAREHOUSE_SOURCE_WEBHOOK_TYPE, enabled=True, deleted=False)


def source_has_enabled_webhook(team_id: int, source_id: uuid.UUID | str) -> bool:
    return _enabled_webhook_functions(team_id).filter(inputs__source_id__value=str(source_id)).exists()


def source_ids_with_enabled_webhook(team_id: int, source_ids: Collection[uuid.UUID | str]) -> set[str]:
    """The ids, as strings, of the given sources that have an enabled webhook. One query."""
    if not source_ids:
        return set()
    found = _enabled_webhook_functions(team_id).filter(
        inputs__source_id__value__in=[str(source_id) for source_id in source_ids]
    )
    return {str(value) for value in found.values_list("inputs__source_id__value", flat=True)}


def sources_missing_webhook(team_id: int, schemas: Iterable[WebhookSchemaState]) -> dict[uuid.UUID, bool]:
    """For each source with a table that needs a webhook, whether that source has no enabled webhook.

    Sources with no such table are left out. At most one query, whatever the number of sources.
    """
    candidates = {schema.source_id for schema in schemas if schema_needs_webhook(schema)}
    registered = source_ids_with_enabled_webhook(team_id, candidates)
    return {source_id: str(source_id) not in registered for source_id in candidates}


class WebhookIssueSchemaState(WebhookSchemaState, Protocol):
    @property
    def id(self) -> uuid.UUID: ...

    @property
    def name(self) -> str: ...


def _function_inputs(function: HogFunction) -> dict[str, Any]:
    """The function's inputs as its API shows them: a set secret reads `{"secret": True}`, an unset input is absent.

    `HogFunction.move_secret_inputs` stores an unset input as None, and the source helpers expect a dict or nothing.
    """
    inputs = {key: value for key, value in (function.inputs or {}).items() if isinstance(value, dict)}
    secrets = {
        key: {"secret": True}
        for key, value in (function.encrypted_inputs or {}).items()
        if isinstance(value, dict) and value.get("value") not in (None, "")
    }
    return {**inputs, **secrets}


def route_table_on_enabled_webhook(
    team_id: int, source_id: uuid.UUID, route_key: str, schema_id: uuid.UUID
) -> str | None:
    """Add one table's route to its source's enabled webhook and return the webhook's id, or None without one.

    Only `schema_mapping` changes, so the webhook's other inputs (an auth user, a pinned repository) stay as set.
    """
    from django.db import transaction  # noqa: PLC0415

    with transaction.atomic():
        function = (
            _enabled_webhook_functions(team_id)
            .select_for_update()
            .filter(inputs__source_id__value=str(source_id))
            .first()
        )
        if function is None:
            return None
        inputs = dict(function.inputs or {})
        routes = dict((inputs.get("schema_mapping") or {}).get("value") or {})
        if routes.get(route_key) != str(schema_id):
            routes[route_key] = str(schema_id)
            inputs["schema_mapping"] = {"value": routes}
            function.inputs = inputs
            function.save(update_fields=["inputs", "encrypted_inputs"])
        return str(function.id)


def _webhook_source(source_type: str | None) -> "WebhookSource | None":
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (  # noqa: PLC0415
        WebhookSource,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415
        SourceRegistry,
        known_source_key,
    )

    if source_type is None:
        return None
    try:
        source = SourceRegistry.get_source(known_source_key(source_type))
    except ValueError:
        return None
    return source if isinstance(source, WebhookSource) else None


def webhook_issues(team_id: int, schemas: Iterable[WebhookIssueSchemaState]) -> dict[uuid.UUID, WebhookIssue | None]:
    """Why each table gets no webhook rows, or None when nothing stops them; every given table has an entry.

    The webhook answers a delivery it cannot use with a 200 and drops it, so without this the table
    looks healthy while its rows never arrive. Two queries, whatever the number of schemas.
    """
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource  # noqa: PLC0415

    schemas = list(schemas)
    issues: dict[uuid.UUID, WebhookIssue | None] = {schema.id: None for schema in schemas}
    needing = [schema for schema in schemas if schema_needs_webhook(schema)]
    if not needing:
        return issues
    source_ids = {schema.source_id for schema in needing}
    functions = {
        str((function.inputs or {}).get("source_id", {}).get("value")): function
        for function in _enabled_webhook_functions(team_id).filter(
            inputs__source_id__value__in=[str(source_id) for source_id in source_ids]
        )
    }
    source_types = dict(
        ExternalDataSource.objects.filter(team_id=team_id, id__in=source_ids).values_list("id", "source_type")
    )
    inputs_by_source: dict[uuid.UUID, dict[str, Any]] = {}
    for schema in needing:
        function = functions.get(str(schema.source_id))
        if function is None:
            issues[schema.id] = WebhookIssue.NOT_REGISTERED
            continue
        source = _webhook_source(source_types.get(schema.source_id))
        if source is None:
            continue
        if schema.source_id not in inputs_by_source:
            inputs_by_source[schema.source_id] = _function_inputs(function)
        inputs = inputs_by_source[schema.source_id]
        routes = (inputs.get("schema_mapping") or {}).get("value") or {}
        if source.missing_webhook_inputs(inputs):
            issues[schema.id] = WebhookIssue.MISSING_INPUTS
        # The template routes on the stored id, so a route left by a deleted table of the same name drops events too.
        elif routes.get(source.webhook_mapping_key(schema.name)) != str(schema.id):
            issues[schema.id] = WebhookIssue.NOT_ROUTED
    return issues
