"""The only code that reads or writes the `Integration` rows that hold warehouse sources' typed-in credentials.

A row has the kind of the credential provider (`postgresql`, `stripe`, `ab-tasty`) and the auth type
that the typed-in fields have (`password`, `api_key`, `credentials`). See `credential_auth_types.py`.
The row holds the connection fields under `sensitive_config["fields"]`, and `config` holds the
`warehouse_source_type` marker. A source points at its row with the `credentials_integration_id`
key in its inputs. An OAuth source keeps its own `*_integration_id` key and has no row here.

Several sources (and later other products) can use one row. An edit of a shared row needs a
confirmation, and an edit that changes where the credentials connect makes a new row. The store
never deletes a row: a row that nothing uses stays in the integrations list.

No method returns a queryset or a model, so a later credentials service can sit behind the same
methods without a change to the callers.
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any, cast
from uuid import UUID, uuid4

from django.db import transaction

import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX, EncryptedJSONField
from posthog.models.integration import WAREHOUSE_SOURCE_TYPE_CONFIG_KEY, Integration, IntegrationQuerySet
from posthog.models.integration.auth_types import AUTH_TYPE_CONFIG_KEY
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.facade.contracts import SharedCredentialsError
from products.warehouse_sources.backend.logic.credential_auth_types import (
    credential_kind,
    typed_in_auth_type,
    typed_in_auth_types,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

CREDENTIALS_ORPHANED_COUNTER = Counter(
    "warehouse_source_credentials_orphaned_total",
    "Credentials rows that no object uses any more after a warehouse source released them",
)

# Fields that say where the credentials connect, and as which account. Each source adds its
# `connection_host_fields`. A change to one of them on a shared row makes a new row.
IDENTIFYING_FIELDS: frozenset[str] = frozenset(
    {
        "host",
        "port",
        "instance_url",
        "connection_string",
        "ssh_tunnel",
        "user",
        "username",
        "account",
        "account_id",
        "account_sid",
    }
)


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
        if pk is None:
            return None
        row = _rows_of(source).filter(id=pk).only("sensitive_config").first()
        if row is None:
            return None
        fields = _fields_of(row.sensitive_config)
        if fields is None:
            raise CredentialsUnreadableError(f"Credentials of source {source.id} are unreadable")
        return fields

    @staticmethod
    def get_many(
        pairs: Iterable[tuple[ExternalDataSource, int | str | None]],
    ) -> dict[UUID, dict[str, Any] | CredentialsUnreadable]:
        """`get` for each `(source, ref)` pair, keyed by source id, with one query per team.

        A source without a row is left out. A source whose row cannot be read maps to
        `CredentialsUnreadable`, so one bad row does not fail a whole list.
        """
        by_team: dict[int, list[tuple[ExternalDataSource, int]]] = {}
        for source, ref in pairs:
            pk = _pk(ref)
            if pk is not None:
                by_team.setdefault(source.team_id, []).append((source, pk))

        result: dict[UUID, dict[str, Any] | CredentialsUnreadable] = {}
        for team_id, team_pairs in by_team.items():
            auth_types = set().union(*(typed_in_auth_types(source.source_type) for source, _ in team_pairs))
            rows = {
                row.pk: row
                for row in Integration.objects.with_auth(*sorted(auth_types))
                .holding_warehouse_source_fields()
                .filter(
                    team_id=team_id,
                    id__in={pk for _, pk in team_pairs},
                    kind__in={credential_kind(source.source_type) for source, _ in team_pairs},
                )
                .only("id", "kind", "config", "sensitive_config")
            }
            for source, pk in team_pairs:
                row = rows.get(pk)
                if row is None or not _belongs_to(row, source):
                    continue
                fields = _fields_of(row.sensitive_config)
                result[source.id] = fields if fields is not None else CredentialsUnreadable()
        return result

    @staticmethod
    def create(source: ExternalDataSource, fields: Mapping[str, Any]) -> int:
        """Create a row with the connection fields of the source. Returns its pk, which the caller
        stores under `CREDENTIALS_REFERENCE_KEY` in the source's inputs."""
        source_type = str(source.source_type)
        row = Integration.objects.with_auth(typed_in_auth_type(source_type, fields)).create(
            team_id=source.team_id,
            kind=credential_kind(source_type),
            # Opaque, so a typed-in row never takes the natural key of a row that other code writes.
            integration_id=uuid4().hex,
            config={
                WAREHOUSE_SOURCE_TYPE_CONFIG_KEY: source_type,
                "display_name": f"{source_type} ({source.prefix})" if source.prefix else source_type,
            },
            sensitive_config={"fields": dict(fields)},
            created_by_id=source.created_by_id,
        )
        return row.pk

    @staticmethod
    def update(
        source: ExternalDataSource, ref: int | str, fields: Mapping[str, Any], *, allow_shared: bool = False
    ) -> int:
        """Write the connection fields to the row that `ref` points at. Returns the pk of the row that
        now holds them: `ref`, or a new row.

        When other sources or products also use the row, a change to an identifying field (host,
        account, auth type) makes a new row, so the other users keep their connection. A change to
        the other fields (a secret rotation) raises `SharedCredentialsError` with the other users,
        unless `allow_shared` confirms it. Raises `CredentialsNotFoundError` when there is no row.
        """
        pk = _pk(ref)
        if pk is None:
            raise CredentialsNotFoundError(f"Source {source.id} has no credentials reference")
        source_type = str(source.source_type)
        auth_type = typed_in_auth_type(source_type, fields)
        with transaction.atomic():
            row = _rows_of(source).select_for_update().filter(id=pk).first()
            if row is None:
                raise CredentialsNotFoundError(f"Credentials of source {source.id} do not exist")
            others = _other_usages(source, pk)
            if others:
                current = _fields_of(row.sensitive_config)
                same_connection = (
                    current is not None
                    and row.auth_type == auth_type.value
                    and _identity(source_type, current) == _identity(source_type, fields)
                )
                if not same_connection:
                    return WarehouseSourceCredentialsStore.create(source, fields)
                if not allow_shared:
                    raise SharedCredentialsError(pk, others)
            # `save` drops the key again when the auth type is the default of the kind.
            row.config = {**row.config, AUTH_TYPE_CONFIG_KEY: auth_type.value}
            row.sensitive_config = {"fields": dict(fields)}
            row.save(update_fields=["config", "sensitive_config"])
            return row.pk

    @staticmethod
    def release(source: ExternalDataSource, ref: int | str | None) -> bool:
        """Note that the source no longer uses the row. Returns True when nothing else uses it.

        The row stays, because a person may reuse it or delete it from the integrations list.
        """
        pk = _pk(ref)
        if pk is None or not _rows_of(source).filter(id=pk).exists():
            return False
        if _other_usages(source, pk):
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


def _rows_of(source: ExternalDataSource) -> IntegrationQuerySet:
    """The typed-in rows that the source can use: its team, its kind, the auth types it can write."""
    source_type = str(source.source_type)
    return (
        Integration.objects.with_auth(*sorted(typed_in_auth_types(source_type)))
        .holding_warehouse_source_fields()
        .filter(team_id=source.team_id, kind=credential_kind(source_type))
    )


def _belongs_to(row: Integration, source: ExternalDataSource) -> bool:
    source_type = str(source.source_type)
    return row.kind == credential_kind(source_type) and row.auth_type in typed_in_auth_types(source_type)


def _pk(ref: int | str | None) -> int | None:
    # Encrypted inputs store every leaf as a string, so "12" and 12 are the same reference.
    if ref is None or isinstance(ref, bool):
        return None
    try:
        return int(ref)
    except (TypeError, ValueError):
        return None


def _other_usages(source: ExternalDataSource, pk: int) -> list[Any]:
    # `usages` imports the warehouse facade, which imports the source inputs store. Import it here so
    # the inputs store can import this module.
    from posthog.models.integration.usages import (  # noqa: PLC0415 — breaks a circular import
        IntegrationUsageType,
        integration_usages,
    )

    return [
        usage
        for usage in integration_usages(team_id=source.team_id, integration_pk=pk)
        if not (usage.type == IntegrationUsageType.WAREHOUSE_SOURCE and usage.id == str(source.id))
    ]


def _identity(source_type: str, fields: Mapping[str, Any]) -> str:
    # The registry loads every source, so keep it off this module's import path.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415 — heavy import
        SourceRegistry,
    )

    source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    keys = IDENTIFYING_FIELDS | set(source.connection_host_fields)
    return json.dumps({key: _normalized(fields.get(key)) for key in sorted(keys)}, sort_keys=True)


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
        # django-stubs can't see through `field_access_control`, so it doesn't know this field name.
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))  # type: ignore[misc]
        recovered = field.decrypt_all_layers(value)
        if recovered is None:
            raise _UndecryptableLeaf
        return recovered
    return value
