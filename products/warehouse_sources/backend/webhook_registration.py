"""Whether a source has the webhook that its webhook-sync tables need.

A webhook-sync table gets its rows from a `warehouse_source_webhook` hog function for its source.
When no such function is enabled, the import worker polls the source API instead, and the API
warns the user. Both read the rule from this module, so they agree about the same source.
"""

import uuid
from collections.abc import Collection, Iterable
from typing import Protocol

from django.db.models import QuerySet

from products.cdp.backend.facade.models import HogFunction
from products.warehouse_sources.backend.facade.types import ExternalDataSchemaSyncType

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
