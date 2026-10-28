"""The only code that reads or writes the `Integration` rows that hold warehouse sources' typed-in credentials.

A row has the kind of the credential provider (`postgresql`, `stripe`, `ab-tasty`) and the auth type
that the typed-in fields have (`token` or `credentials`). See `credential_auth_types.py`. The row holds
the connection fields under `sensitive_config["fields"]`, and `config` holds the
`warehouse_source_type` marker. A source points at its row with the `credentials_integration_id`
key in its inputs. An OAuth source keeps its own `*_integration_id` key and has no row here.

Every read and write goes through `IntegrationManager.source(kind)` of the integrations SDK, which sees
only marked rows of the kind and auth type.

Several sources (and later other products) can use one row. An edit of a shared row needs a
confirmation, and an edit that changes where the credentials connect makes a new row. The store
never deletes a row: a row that nothing uses stays in the integrations list.

No method returns a queryset or a model, so a later credentials service can sit behind the same
methods without a change to the callers.
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction

import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX, EncryptedJSONField
from posthog.models.integration import WAREHOUSE_SOURCE_TYPE_CONFIG_KEY
from posthog.sync import database_sync_to_async_pool

from products.integrations.backend.facade.api import AuthAccessor, IntegrationRecord
from products.integrations.backend.facade.contracts import IntegrationNotFound, IntegrationPatch, IntegrationUsage
from products.warehouse_sources.backend.facade.contracts import WAREHOUSE_SOURCE_USAGE_TYPE, SharedCredentialsError
from products.warehouse_sources.backend.logic.credential_auth_types import credentials_accessor
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

CREDENTIALS_ORPHANED_COUNTER = Counter(
    "warehouse_source_credentials_orphaned_total",
    "Credentials rows that no object uses any more after a warehouse source released them",
)

# Decrypts leaves with the same keys as `Integration.sensitive_config`. The keys come from the settings.
_SENSITIVE_CONFIG_FIELD = EncryptedJSONField(default=dict, ignore_decrypt_errors=True)


class CredentialsUnreadableError(ValueError):
    """A row exists but its `sensitive_config` does not hold readable fields. The cause is usually a
    decryption failure. The message never holds a value, because values are credentials."""


class CredentialsNotFoundError(LookupError):
    """The reference does not point at a credentials row of the source's team and kind."""


@frozen
class CredentialsUnreadable:
    """In a `get_many` result: the row exists, but it cannot be read."""


class WarehouseSourceCredentialsStore:
    @staticmethod
    def get(source: ExternalDataSource, ref: int | str | None) -> dict[str, Any] | None:
        """The connection fields in the row that `ref` points at, or None when there is no such row.

        Raises `CredentialsUnreadableError` when the row exists but cannot be read. Callers must not
        treat that as "no fields".
        """
        pk = _pk(ref)
        rows = _accessor_or_none(source)
        if pk is None or rows is None:
            return None
        try:
            row = rows.get(source.team_id, pk)
        except IntegrationNotFound:
            return None
        fields = _fields_of(row.sensitive_config)
        if fields is None:
            raise CredentialsUnreadableError(f"Credentials of source {source.id} are unreadable")
        return fields

    @staticmethod
    def get_many(
        pairs: Iterable[tuple[ExternalDataSource, int | str | None]],
    ) -> dict[UUID, dict[str, Any] | CredentialsUnreadable]:
        """`get` for each `(source, ref)` pair, keyed by source id, with one query per team and source type.

        A source without a row is left out. A source whose row cannot be read maps to
        `CredentialsUnreadable`, so one bad row does not fail a whole list.
        """
        groups: dict[tuple[int, str], list[tuple[ExternalDataSource, int]]] = {}
        for source, ref in pairs:
            pk = _pk(ref)
            if pk is not None:
                groups.setdefault((source.team_id, str(source.source_type)), []).append((source, pk))

        result: dict[UUID, dict[str, Any] | CredentialsUnreadable] = {}
        for (team_id, _source_type), group in groups.items():
            rows = _accessor_or_none(group[0][0])
            if rows is None:
                continue
            found = rows.get_many(team_id, {pk for _, pk in group})
            for source, pk in group:
                row = found.get(pk)
                if row is None:
                    continue
                fields = _fields_of(row.sensitive_config)
                result[source.id] = fields if fields is not None else CredentialsUnreadable()
        return result

    @staticmethod
    def create(source: ExternalDataSource, fields: Mapping[str, Any]) -> int:
        """Create a row with the connection fields of the source. Returns its pk, which the caller
        stores under `CREDENTIALS_REFERENCE_KEY` in the source's inputs.

        Raises ValueError for a source without typed-in credentials (an OAuth-only source, or Custom).
        """
        source_type = str(source.source_type)
        row = credentials_accessor(source_type).create(
            source.team_id,
            # Opaque, so a typed-in row never takes the natural key of a row that other code writes.
            external_id=uuid4().hex,
            config={
                WAREHOUSE_SOURCE_TYPE_CONFIG_KEY: source_type,
                "display_name": f"{source_type} ({source.prefix})" if source.prefix else source_type,
            },
            sensitive_config={"fields": dict(fields)},
            created_by_id=source.created_by_id,
        )
        return row.id

    @staticmethod
    def update(
        source: ExternalDataSource, ref: int | str, fields: Mapping[str, Any], *, allow_shared: bool = False
    ) -> int:
        """Write the connection fields to the row that `ref` points at. Returns the pk of the row that
        now holds them: `ref`, or a new row.

        When other sources or products also use the row, a change to an identifying field (host,
        account) makes a new row, so the other users keep their connection. A change to the other
        fields (a secret rotation) raises `SharedCredentialsError` with the other users, unless
        `allow_shared` confirms it. Raises `CredentialsNotFoundError` when there is no row.
        """
        pk = _pk(ref)
        if pk is None:
            raise CredentialsNotFoundError(f"Source {source.id} has no credentials reference")
        source_type = str(source.source_type)
        rows = credentials_accessor(source_type)
        needs_new_row = False

        def change(row: IntegrationRecord) -> IntegrationPatch:
            nonlocal needs_new_row
            others = _other_usages(rows, source, row.id)
            if others:
                current = _fields_of(row.sensitive_config)
                if current is None or _identity(source_type, current) != _identity(source_type, fields):
                    needs_new_row = True
                    return IntegrationPatch()
                if not allow_shared:
                    raise SharedCredentialsError(row.id, others)
            return IntegrationPatch(sensitive_config_patch={"fields": dict(fields)})

        # The outer transaction keeps the row locked until the new row exists.
        with transaction.atomic():
            try:
                rows.update_atomically(source.team_id, pk, change)
            except IntegrationNotFound as error:
                raise CredentialsNotFoundError(f"Credentials of source {source.id} do not exist") from error
            if needs_new_row:
                return WarehouseSourceCredentialsStore.create(source, fields)
            return pk

    @staticmethod
    def release(source: ExternalDataSource, ref: int | str | None) -> bool:
        """Note that the source no longer uses the row. Returns True when nothing else uses it.

        The row stays, because a person may reuse it or delete it from the integrations list.
        """
        pk = _pk(ref)
        rows = _accessor_or_none(source)
        if pk is None or rows is None:
            return False
        try:
            others = _other_usages(rows, source, pk)
        except IntegrationNotFound:
            return False
        if others:
            return False
        CREDENTIALS_ORPHANED_COUNTER.inc()
        logger.info("warehouse_source_credentials_orphaned", team_id=source.team_id, integration_id=pk)
        return True

    @staticmethod
    async def aget(source: ExternalDataSource, ref: int | str | None) -> dict[str, Any] | None:
        return await database_sync_to_async_pool(WarehouseSourceCredentialsStore.get)(source, ref)

    @staticmethod
    async def acreate(source: ExternalDataSource, fields: Mapping[str, Any]) -> int:
        return await database_sync_to_async_pool(WarehouseSourceCredentialsStore.create)(source, fields)

    @staticmethod
    async def aupdate(
        source: ExternalDataSource, ref: int | str, fields: Mapping[str, Any], *, allow_shared: bool = False
    ) -> int:
        def _update() -> int:
            return WarehouseSourceCredentialsStore.update(source, ref, fields, allow_shared=allow_shared)

        return await database_sync_to_async_pool(_update)()


def _accessor_or_none(source: ExternalDataSource) -> AuthAccessor | None:
    # A source without typed-in credentials (OAuth-only, Custom) has no row to read.
    try:
        return credentials_accessor(str(source.source_type))
    except ValueError:
        return None


def _pk(ref: int | str | None) -> int | None:
    # Encrypted inputs store every leaf as a string, so "12" and 12 are the same reference.
    if ref is None or isinstance(ref, bool):
        return None
    try:
        return int(ref)
    except (TypeError, ValueError):
        return None


def _other_usages(rows: AuthAccessor, source: ExternalDataSource, pk: int) -> list[IntegrationUsage]:
    """The usages of the row other than this source. Raises `IntegrationNotFound` when the row is not in scope."""
    return [
        usage
        for usage in rows.usages(source.team_id, pk)
        if not (usage.type == WAREHOUSE_SOURCE_USAGE_TYPE and usage.id == str(source.id))
    ]


def _identity(source_type: str, fields: Mapping[str, Any]) -> str:
    # The registry loads every source, so keep it off this module's import path.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415 — heavy import
        SourceRegistry,
    )

    source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    return json.dumps(
        {key: _normalized(fields.get(key)) for key in sorted(source.credential_identity_fields)}, sort_keys=True
    )


def _normalized(value: Any) -> Any:
    # Encrypted fields store leaves as strings, so compare strings. An unset and a blank value match.
    if isinstance(value, Mapping):
        return {str(key): _normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return "" if value is None else str(value)


def _fields_of(sensitive_config: Any) -> dict[str, Any] | None:
    # `sensitive_config` ignores decrypt errors and then reads back as {}. A readable row always has a
    # "fields" mapping, even when the source has no connection fields.
    if not isinstance(sensitive_config, Mapping):
        return None
    fields = sensitive_config.get("fields")
    if not isinstance(fields, Mapping):
        return None
    # The field encrypts each leaf, and a leaf that fails to decrypt comes back as raw ciphertext
    # rather than raising. Peel extra layers a read-then-save added, and treat any leaf no key can
    # open as an unreadable row, so ciphertext is never handed out as a credential.
    try:
        return _recover_leaves(dict(fields))
    except _UndecryptableLeaf:
        return None


class _UndecryptableLeaf(Exception):
    pass


def _recover_leaves(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _recover_leaves(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_recover_leaves(item) for item in value]
    if isinstance(value, str) and value.startswith(FERNET_TOKEN_PREFIX):
        recovered = _SENSITIVE_CONFIG_FIELD.decrypt_all_layers(value)
        if recovered is None:
            raise _UndecryptableLeaf
        return recovered
    return value
