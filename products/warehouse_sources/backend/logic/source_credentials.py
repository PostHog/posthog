"""The only code that reads or writes the `Integration` rows that hold warehouse sources' typed-in credentials.

A row has the kind of the credential provider (`postgresql`, `stripe`, `ab-tasty`) and the auth type
that the typed-in fields have (`token` or `credentials`). See `credential_auth_types.py`. The row holds
the connection fields under `sensitive_config["fields"]`, and `config` holds the
`warehouse_source_type` marker. A source points at its row with its `credentials_integration_id`
column, in the string form of `IntegrationReference`. An OAuth source keeps its own `*_integration_id`
key in its inputs and has no row here.

Every read and write goes through `IntegrationManager.source(kind)` of the integrations SDK, which sees
only marked rows of the kind and auth type.

Several sources (and later other products) can use one row. An edit of a shared row needs a
confirmation, and an edit that changes where the credentials connect makes a new row. The store
never deletes a row that a source used: a row that nothing uses stays in the integrations list. The
one exception is `discard`, for the row of a source whose create did not finish.

No method returns a queryset or a model, so a later credentials service can sit behind the same
methods without a change to the callers.
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID, uuid4

import structlog

from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX, EncryptedJSONField
from posthog.integrations import (
    SOURCE_MARKER_CONFIG_KEY,
    AuthAccessor,
    IntegrationInUse,
    IntegrationNotFound,
    IntegrationReference,
    IntegrationUsage,
)
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.facade.contracts import WAREHOUSE_SOURCE_USAGE_TYPE, SharedCredentialsError
from products.warehouse_sources.backend.logic.credential_auth_types import credentials_accessor
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

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
    def get(source: ExternalDataSource) -> dict[str, Any] | None:
        """The connection fields in the row that the source points at, or None when there is no such row.

        Raises `CredentialsUnreadableError` when the row exists but cannot be read. Callers must not
        treat that as "no fields".
        """
        pk = _pk(source)
        if pk is None:
            return None
        return WarehouseSourceCredentialsStore.get_at(source, IntegrationReference.from_legacy_id(pk))

    @staticmethod
    def get_at(source: ExternalDataSource, reference: IntegrationReference) -> dict[str, Any] | None:
        """`get` for the row that ``reference`` points at, in place of the row in the source's column.

        Use it to check a row before the source points at it. Raises `CredentialsUnreadableError` as `get` does.
        """
        rows = _accessor_or_none(source)
        if reference.legacy_id is None or rows is None:
            return None
        try:
            row = rows.get(source.team_id, reference.legacy_id)
        except IntegrationNotFound:
            return None
        fields = _fields_of(row.sensitive_config)
        if fields is None:
            raise CredentialsUnreadableError(f"Credentials of source {source.id} are unreadable")
        return fields

    @staticmethod
    def get_many(sources: Iterable[ExternalDataSource]) -> dict[UUID, dict[str, Any] | CredentialsUnreadable]:
        """`get` for each source, keyed by source id, with one query per team and source type.

        A source without a row is left out. A source whose row cannot be read maps to
        `CredentialsUnreadable`, so one bad row does not fail a whole list.
        """
        groups: dict[tuple[int, str], list[tuple[ExternalDataSource, int]]] = {}
        for source in sources:
            pk = _pk(source)
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
    def create(source: ExternalDataSource, fields: Mapping[str, Any]) -> IntegrationReference:
        """Create a row with the connection fields of the source, and point the source at it.

        The source is not saved. The caller saves it with its inputs (`SourceInputsStore.save` or
        `create`, or a full model save), so the source never points at a row that its inputs do not use.

        Raises ValueError for a source without typed-in credentials (an OAuth-only source, or Custom).
        """
        source_type = str(source.source_type)
        row = credentials_accessor(source_type).create(
            source.team_id,
            # Opaque, so a typed-in row never takes the natural key of a row that other code writes.
            external_id=uuid4().hex,
            config={
                SOURCE_MARKER_CONFIG_KEY: source_type,
                "display_name": f"{source_type} ({source.prefix})" if source.prefix else source_type,
            },
            sensitive_config={"fields": dict(fields)},
            created_by_id=source.created_by_id,
        )
        return _point_at(source, row.id)

    @staticmethod
    def update(
        source: ExternalDataSource, fields: Mapping[str, Any], *, allow_shared: bool = False
    ) -> IntegrationReference:
        """Write the connection fields to the row that the source points at. Returns the reference of
        the row that now holds them: the same row, or a new row.

        When other sources or products also use the row, a change to an identifying field (host,
        account) makes a new row, so the other users keep their connection. The source then points at
        the new row, and the caller saves it as for `create`. A change to the other fields (a secret
        rotation) raises `SharedCredentialsError` with the other users, unless `allow_shared` confirms
        it. A write that changes no field writes nothing and needs no confirmation. Raises
        `CredentialsNotFoundError` when there is no row.
        """
        pk = _pk(source)
        if pk is None:
            raise CredentialsNotFoundError(f"Source {source.id} has no credentials reference")
        source_type = str(source.source_type)
        rows = credentials_accessor(source_type)
        try:
            row = rows.get(source.team_id, pk)
        except IntegrationNotFound as error:
            raise CredentialsNotFoundError(f"Credentials of source {source.id} do not exist") from error
        current = _fields_of(row.sensitive_config)
        # Each save of a source writes all its inputs again, so most writes change no field. Such a
        # write needs no confirmation, also when the row is shared.
        if current is not None and same_connection_fields(current, fields):
            return IntegrationReference.from_legacy_id(pk)
        try:
            others = _other_usages(rows, source, row.id)
        except IntegrationNotFound as error:
            raise CredentialsNotFoundError(f"Credentials of source {source.id} do not exist") from error
        if others:
            if current is None or _identity(source_type, current) != _identity(source_type, fields):
                return WarehouseSourceCredentialsStore.create(source, fields)
            if not allow_shared:
                raise SharedCredentialsError(row.id, others)
        # No lock spans the usages check and the write. When two sources edit one shared row at the
        # same time, the last write wins. The source lock serializes the edits of one source only.
        try:
            rows.update(source.team_id, pk, sensitive_config_patch={"fields": dict(fields)})
        except IntegrationNotFound as error:
            raise CredentialsNotFoundError(f"Credentials of source {source.id} do not exist") from error
        return IntegrationReference.from_legacy_id(pk)

    @staticmethod
    def other_usages(
        source: ExternalDataSource, reference: IntegrationReference | None = None
    ) -> list[IntegrationUsage]:
        """The objects other than the source that use the row at ``reference``, by default the row of the source.

        Empty when there is no such row in scope.
        """
        pk = _pk(source) if reference is None else reference.legacy_id
        rows = _accessor_or_none(source)
        if pk is None or rows is None:
            return []
        try:
            return _other_usages(rows, source, pk)
        except IntegrationNotFound:
            return []

    @staticmethod
    def discard(source: ExternalDataSource) -> bool:
        """Delete the row of a source whose create did not finish. Returns True when it deleted the row.

        Call it after the source row is gone. The row stays when another object uses it. The row of an
        OAuth source is out of scope, so it always stays.
        """
        pk = _pk(source)
        rows = _accessor_or_none(source)
        if pk is None or rows is None:
            return False
        try:
            rows.delete(source.team_id, pk)
        except (IntegrationNotFound, IntegrationInUse):
            return False
        return True

    @staticmethod
    async def aget(source: ExternalDataSource) -> dict[str, Any] | None:
        return await database_sync_to_async_pool(WarehouseSourceCredentialsStore.get)(source)

    @staticmethod
    async def acreate(source: ExternalDataSource, fields: Mapping[str, Any]) -> IntegrationReference:
        return await database_sync_to_async_pool(WarehouseSourceCredentialsStore.create)(source, fields)

    @staticmethod
    async def aupdate(
        source: ExternalDataSource, fields: Mapping[str, Any], *, allow_shared: bool = False
    ) -> IntegrationReference:
        def _update() -> IntegrationReference:
            return WarehouseSourceCredentialsStore.update(source, fields, allow_shared=allow_shared)

        return await database_sync_to_async_pool(_update)()


def _accessor_or_none(source: ExternalDataSource) -> AuthAccessor | None:
    # A source without typed-in credentials (OAuth-only, Custom) has no row to read.
    try:
        return credentials_accessor(str(source.source_type))
    except ValueError:
        return None


def _point_at(source: ExternalDataSource, pk: int) -> IntegrationReference:
    reference = IntegrationReference.from_legacy_id(pk)
    source.credentials_integration_id = str(reference)
    return reference


def _pk(source: ExternalDataSource) -> int | None:
    """The legacy id in the reference column, or None when the source points at no row the SDK can read."""
    stored = source.credentials_integration_id
    if stored is None:
        return None
    try:
        reference = IntegrationReference.parse(stored)
    except ValueError:
        # Only the store writes the column, so this is a bad write. The source then has no row: a read
        # finds no credentials and an update raises, and neither reads a row of another source.
        logger.warning("warehouse_source_credentials_reference_invalid", team_id=source.team_id, source_id=source.id)
        return None
    # A UUID points at a row in the credentials service, which the SDK cannot read yet.
    return reference.legacy_id


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
    return json.dumps(_identity_parts(fields, source.credential_identity_fields), sort_keys=True)


def _identity_parts(fields: Mapping[str, Any], names: frozenset[str], prefix: str = "") -> dict[str, Any]:
    # A source can declare an identity field inside a select option (Snowflake keeps `user` under
    # `auth_type`), so look at every depth. The path keeps two fields of one name apart.
    parts: dict[str, Any] = {}
    for key, value in fields.items():
        path = f"{prefix}{key}"
        if key in names:
            part = _identity_value(str(key), value)
            # An unset and a blank value match.
            if part not in ("", {}):
                parts[path] = part
        elif isinstance(value, Mapping):
            parts.update(_identity_parts(value, names, f"{path}."))
    return parts


def _identity_value(key: str, value: Any) -> Any:
    # These two fields also hold secrets. A secret change is a rotation, not a new connection, so
    # compare only the parts that say where the credentials connect and as which account.
    if key == "ssh_tunnel" and isinstance(value, Mapping):
        auth = value.get("auth_type")
        return {
            part: item
            for part, item in {
                "enabled": _normalized(value.get("enabled")).lower(),
                "host": _normalized(value.get("host")),
                "port": _normalized(value.get("port")),
                "username": _normalized(auth.get("username") if isinstance(auth, Mapping) else None),
            }.items()
            if item
        }
    if key == "connection_string" and isinstance(value, str):
        return _connection_string_identity(value)
    return _normalized(value)


# Keys of a `key=value;...` connection string (ADO.NET, libpq) that say where it connects and as whom.
_CONNECTION_STRING_IDENTITY_KEYS = frozenset(
    {
        "server",
        "host",
        "hostaddr",
        "address",
        "addr",
        "data source",
        "port",
        "user",
        "user id",
        "uid",
        "username",
        "database",
        "dbname",
        "initial catalog",
        "account",
    }
)


def _connection_string_identity(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        uri = urlsplit(value)
        userinfo, _, hosts = uri.netloc.rpartition("@")
        identity = {
            "scheme": uri.scheme.lower(),
            "user": unquote(userinfo.partition(":")[0]),
            "hosts": hosts.lower(),
            "database": uri.path.removeprefix("/"),
        }
        if uri.scheme.lower() in ("mongodb", "mongodb+srv"):
            options = {key.lower(): item for key, item in parse_qsl(uri.query)}
            identity["auth_source"] = options.get("authsource", unquote(uri.path.removeprefix("/")) or "admin")
        return identity
    # ADO.NET separates pairs with ";" and has keys with spaces ("User Id"). libpq separates with spaces.
    pairs = [pair.partition("=") for pair in (value.split(";") if ";" in value else value.split()) if "=" in pair]
    parts = {
        key.strip().lower(): item.strip()
        for key, _, item in pairs
        if key.strip().lower() in _CONNECTION_STRING_IDENTITY_KEYS
    }
    # A format this does not know compares whole, so a change can only make a new row.
    return parts or value


def _normalized(value: Any) -> Any:
    # Encrypted fields store leaves as strings, so compare strings. An unset and a blank value match.
    if isinstance(value, Mapping):
        return {str(key): _normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return "" if value is None else str(value)


def same_connection_fields(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    """True when two sets of connection fields hold the same values. A missing key, None and a blank value
    are equal, and `5432` equals `"5432"`, because encrypted fields store each leaf as a string. Every compare
    of a row with `job_inputs` uses this rule, so a row that `update` does not rewrite also compares equal."""
    return _set_values(first) == _set_values(second)


def _set_values(fields: Mapping[str, Any]) -> dict[str, Any]:
    # A parsed config writes its unset optional fields as None, so a missing key and an empty value match.
    return {key: value for key, value in _normalized(fields).items() if value not in ("", {}, [])}


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
    return recover_encrypted_leaves(fields)


def recover_encrypted_leaves(fields: Mapping[str, Any]) -> dict[str, Any] | None:
    """``fields`` with every ciphertext leaf decrypted through all its layers, or None when a leaf
    cannot be opened by any configured key."""
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
