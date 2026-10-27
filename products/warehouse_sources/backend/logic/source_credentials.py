"""The only code that reads or writes core ``Integration`` rows of kind ``warehouse-source``.

Each source has at most one row. It holds the connection fields of the source, encrypted, under
``sensitive_config["fields"]``. The row key is ``(team_id, kind, integration_id=str(source.id))``, so the
source needs no reference column. No method returns a queryset or a model, so a later storage can sit
behind an HTTP service without a change to the callers.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

KIND = Integration.IntegrationKind.WAREHOUSE_SOURCE.value


class CredentialsUnreadableError(ValueError):
    """A row exists but its ``sensitive_config`` does not hold readable fields. The cause is usually a
    decryption failure. The message never holds a value, because values are credentials."""


@frozen
class CredentialsUnreadable:
    """In a `get_many` result: a row exists for this source, but it cannot be read."""


@frozen
class CredentialRowRef:
    """The key of one row, without its fields."""

    team_id: int
    source_id: str


class WarehouseSourceCredentialsStore:
    @staticmethod
    def get(source: ExternalDataSource) -> dict[str, Any] | None:
        """The connection fields of the source, or None when the source has no row.

        Raises `CredentialsUnreadableError` when the row exists but cannot be read. Callers must not
        treat that as "no fields".
        """
        row = (
            Integration.objects.filter(team_id=source.team_id, kind=KIND, integration_id=str(source.id))
            .only("sensitive_config")
            .first()
        )
        if row is None:
            return None
        fields = _fields_of(row.sensitive_config)
        if fields is None:
            raise CredentialsUnreadableError(f"Credentials of source {source.id} are unreadable")
        return fields

    @staticmethod
    def get_many(sources: Iterable[ExternalDataSource]) -> dict[UUID, dict[str, Any] | CredentialsUnreadable]:
        """`get` for each source in one query, keyed by source id.

        A source without a row is left out. A source whose row cannot be read maps to
        `CredentialsUnreadable`, so one bad row does not fail a whole list. Sources of one team are
        the expected input; rows of other teams are never matched.
        """
        by_team: dict[int, dict[str, UUID]] = {}
        for source in sources:
            by_team.setdefault(source.team_id, {})[str(source.id)] = source.id
        if not by_team:
            return {}

        result: dict[UUID, dict[str, Any] | CredentialsUnreadable] = {}
        for team_id, ids in by_team.items():
            rows = Integration.objects.filter(team_id=team_id, kind=KIND, integration_id__in=list(ids)).only(
                "integration_id", "sensitive_config"
            )
            for row in rows:
                fields = _fields_of(row.sensitive_config)
                result[ids[str(row.integration_id)]] = fields if fields is not None else CredentialsUnreadable()
        return result

    @staticmethod
    def upsert(source: ExternalDataSource, connection_fields: Mapping[str, Any]) -> None:
        """Create or replace the row of the source. Safe to repeat."""
        Integration.objects.update_or_create(
            team_id=source.team_id,
            kind=KIND,
            integration_id=str(source.id),
            defaults={
                "config": {"source_type": str(source.source_type), "source_id": str(source.id)},
                "sensitive_config": {"fields": dict(connection_fields)},
            },
        )

    @staticmethod
    def delete(source: ExternalDataSource) -> int:
        """Delete the row of the source, if any. Returns the number of rows deleted."""
        return WarehouseSourceCredentialsStore.delete_for_source_ids(source.team_id, [source.id])

    @staticmethod
    def delete_for_source_ids(team_id: int, source_ids: Iterable[UUID | str]) -> int:
        ids = [str(source_id) for source_id in source_ids]
        if not ids:
            return 0
        deleted, _ = Integration.objects.filter(team_id=team_id, kind=KIND, integration_id__in=ids).delete()
        return deleted

    @staticmethod
    def list_row_refs(
        *, after_pk: int = 0, limit: int = 500, created_before: datetime | None = None
    ) -> list[tuple[int, CredentialRowRef]]:
        """One page of row keys in primary key order, as ``(cursor, ref)`` pairs. Pass the last cursor as
        ``after_pk`` for the next page. With ``created_before``, rows created at or after it are left out.
        Never decrypts a row."""
        queryset = Integration.objects.filter(kind=KIND, pk__gt=after_pk)
        if created_before is not None:
            queryset = queryset.filter(created_at__lt=created_before)
        rows = queryset.order_by("pk").values_list("pk", "team_id", "integration_id")[:limit]
        return [
            (pk, CredentialRowRef(team_id=team_id, source_id=str(integration_id)))
            for pk, team_id, integration_id in rows
        ]

    @staticmethod
    async def aget(source: ExternalDataSource) -> dict[str, Any] | None:
        return await database_sync_to_async_pool(WarehouseSourceCredentialsStore.get)(source)

    @staticmethod
    async def aupsert(source: ExternalDataSource, connection_fields: Mapping[str, Any]) -> None:
        await database_sync_to_async_pool(WarehouseSourceCredentialsStore.upsert)(source, connection_fields)


def _fields_of(sensitive_config: Any) -> dict[str, Any] | None:
    # `sensitive_config` ignores decrypt errors and then reads back as {}. A readable row always has a
    # "fields" mapping, even when the source has no connection fields.
    if not isinstance(sensitive_config, Mapping):
        return None
    fields = sensitive_config.get("fields")
    return dict(fields) if isinstance(fields, Mapping) else None
