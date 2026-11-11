"""The only code that reads or writes ``ExternalDataSource.job_inputs``.

``job_inputs`` holds connection fields, sync settings and runtime state in one blob. Callers go
through ``SourceInputsStore`` so that the storage of each part can change without a change to the
callers. A semgrep rule (`warehouse-source-inputs-go-through-store`) blocks raw access elsewhere.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction

from posthog.integrations import IntegrationReference
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.facade.contracts import (
    CONNECTION_FIELDS_STRIPPED_KEY,
    DEAD_CREDENTIALS_CLEARED_KEY,
    STRIPPED_STORE_KEYS,
    SharedCredentialsEdit,
    UnreadableSourceInputsError,
)
from products.warehouse_sources.backend.logic.credential_auth_types import has_typed_in_credentials
from products.warehouse_sources.backend.logic.source_credentials import WarehouseSourceCredentialsStore
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    assign_credentials_reference,
    is_stripped,
    preload_connection_fields,
    read_connection_fields,
    read_connection_fields_many,
    strippable,
    stripped_at_now,
    stripped_job_inputs,
    write_stripped_credentials,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import source_key

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
        SplitJobInputs,
    )

DEFAULT_EXTRA_UPDATE_FIELDS: tuple[str, ...] = ("updated_at",)
# The model fields that `assign` stages. A caller that saves with `update_fields` after `assign` lists them all.
INPUTS_UPDATE_FIELDS: tuple[str, ...] = ("job_inputs", "credentials_integration_id")


class SourceInputsStore:
    @staticmethod
    def load(source: ExternalDataSource) -> dict[str, Any]:
        """All inputs of the source: connection fields, sync settings and runtime state.

        The result is a new dict, so a change to it has no effect until a write method saves it. The connection
        fields come from the credentials row of the source and the OAuth pointer from its reference column, never
        from the model field. Raises `SourceCredentialsMissingError` (an `UnreadableSourceInputsError`) when the
        row or the column that the source needs is missing or unreadable.
        """
        inputs = read_connection_fields(source, _decode(source.job_inputs))
        return {key: value for key, value in inputs.items() if key != DEAD_CREDENTIALS_CLEARED_KEY}

    @staticmethod
    def load_many(sources: Iterable[ExternalDataSource]) -> dict[UUID, dict[str, Any]]:
        """`load` for each source, keyed by source id. Use it on list paths, so that a later
        storage can fetch all sources in one batch.

        A source whose inputs do not decode is left out, so one bad row does not fail a whole list.
        A caller that needs that source calls `load` and handles the error.
        """
        sources = list(sources)
        loaded: dict[UUID, dict[str, Any]] = {}
        for source in sources:
            try:
                loaded[source.id] = _decode(source.job_inputs)
            except UnreadableSourceInputsError:
                continue
        return {
            source_id: {key: value for key, value in inputs.items() if key != DEAD_CREDENTIALS_CLEARED_KEY}
            for source_id, inputs in read_connection_fields_many(sources, loaded).items()
        }

    @staticmethod
    def preload(sources: Iterable[ExternalDataSource]) -> None:
        """Fetch what `load` needs for these sources in one batch, so that later `load` calls on the same
        instances add no query. Use it before a loop that calls `load` once per table of a source."""
        preload_connection_fields(sources)

    @staticmethod
    def load_stored(source: ExternalDataSource) -> dict[str, Any]:
        """The decoded `job_inputs` as stored, never merged with the credentials row.

        Only a tool that copies or checks the stored data should use it, such as the backfill. Raises
        `UnreadableSourceInputsError` like `load`. For a stripped source the result holds no connection fields
        and no OAuth pointer, and it holds the strip marker.
        """
        return _decode(source.job_inputs)

    @staticmethod
    def write_credentials_reference(source: ExternalDataSource, reference: IntegrationReference | None) -> None:
        """Point the source at a credentials row, and change nothing else.

        Only a tool that links existing sources to their rows should use it, such as the backfill. It never
        copies fields to the row, never changes `job_inputs`, and does not change `updated_at`.
        """
        source.credentials_integration_id = None if reference is None else str(reference)
        source.save(update_fields=["credentials_integration_id"])

    @staticmethod
    def adopt_oauth_pointer(
        source: ExternalDataSource, inputs: Mapping[str, Any], reference: IntegrationReference
    ) -> None:
        """Save adopted OAuth inputs and their reference together, without the typed-in credentials mirror.

        The caller must hold the source lock and create the integration in the same transaction.
        """
        _stage(source, inputs)
        source.credentials_integration_id = str(reference)
        source.save(update_fields=[*INPUTS_UPDATE_FIELDS])

    @staticmethod
    def load_settings(source: ExternalDataSource) -> dict[str, Any]:
        """Only the sync settings and runtime state of the source, never a connection field.

        Use it for reads such as the default ``schema`` or the ``cdc_*`` keys. The result does not
        need the connection storage, so it stays cheap on hot paths.
        """
        inputs = _decode(source.job_inputs)
        try:
            split = _split(source.source_type, inputs)
        except ValueError:
            # An unknown source type declares no settings. Every key except the runtime prefixes is then a
            # connection field, which is the safe side for a reader that must not see credentials.
            return {key: value for key, value in inputs.items() if _has_runtime_prefix(key)}
        runtime = {
            key: value
            for key, value in split.runtime.items()
            if key not in STRIPPED_STORE_KEYS and key != DEAD_CREDENTIALS_CLEARED_KEY
        }
        return {**split.settings, **runtime}

    @staticmethod
    def stored_as_string(source: ExternalDataSource) -> bool:
        """True when the inputs were stored as one JSON string instead of a mapping.

        EncryptedJSONField encrypts a string value whole, so such a row reads back as a string on every
        read. A caller can rewrite it once as a mapping with `save`.
        """
        return isinstance(source.job_inputs, str)

    @staticmethod
    def assign(
        source: ExternalDataSource,
        inputs: Mapping[str, Any],
        *,
        shared_credentials: SharedCredentialsEdit = SharedCredentialsEdit.SKIP,
        credentials_reference: IntegrationReference | None = None,
    ) -> None:
        """Stage all inputs on the source without a database write. The caller must save the model, with
        every field in `INPUTS_UPDATE_FIELDS`.

        Use it when the caller saves the model for other reasons too, for example a DRF serializer
        update, so that the source row gets one write. ``credentials_reference`` is a row that an API edit
        picked. ``shared_credentials`` decides what an edit of a row that other objects use does.

        The write strips the source when it is stripped already or when ``inputs`` hold typed-in connection fields
        or an OAuth pointer: the connection fields go only to the credentials row and the OAuth pointer only to the
        `credentials_integration_id` column, and the write raises when that fails. `job_inputs` then keeps
        neither. Other inputs clear the column. See `assign_credentials_reference`.
        """
        inputs = {key: value for key, value in inputs.items() if key != DEAD_CREDENTIALS_CLEARED_KEY}
        try:
            stored = _decode(source.job_inputs)
        except UnreadableSourceInputsError:
            stored = {}
        if DEAD_CREDENTIALS_CLEARED_KEY in stored:
            inputs[DEAD_CREDENTIALS_CLEARED_KEY] = stored[DEAD_CREDENTIALS_CLEARED_KEY]
        stripped_at = _stored_stripped_at(source)
        if stripped_at is None and _strippable(source, inputs):
            stripped_at = stripped_at_now()
        if stripped_at is not None:
            _assign_stripped(source, inputs, stripped_at, shared_credentials, credentials_reference)
            return
        assign_credentials_reference(source, inputs, reference=credentials_reference)
        _stage(source, inputs)

    @staticmethod
    def save(
        source: ExternalDataSource,
        inputs: Mapping[str, Any],
        *,
        extra_update_fields: Sequence[str] = DEFAULT_EXTRA_UPDATE_FIELDS,
    ) -> None:
        """Replace all inputs of the source and save them.

        The same write saves `credentials_integration_id`, which `assign` and `WarehouseSourceCredentialsStore`
        set on the source. So the source points at its credentials row only together with its inputs. A caller
        that holds the source for a long time must not use it: its copy of the column can be older than the
        row. See `update_oauth_inputs`.
        """
        # One transaction, so a failed save also undoes the copy to the credentials row.
        with transaction.atomic():
            SourceInputsStore.assign(source, inputs)
            source.save(update_fields=[*INPUTS_UPDATE_FIELDS, *extra_update_fields])

    @staticmethod
    def create(*, inputs: Mapping[str, Any], **fields: Any) -> ExternalDataSource:
        """Create a source with these inputs in one insert. ``fields`` are the other model fields.

        The credentials row is created before the insert, so the insert saves the reference to it. Both
        writes are in one transaction, so a failed insert leaves no row. A source with typed-in credentials or
        an OAuth pointer is stripped from the start.
        """
        source = ExternalDataSource(**fields)
        with transaction.atomic():
            SourceInputsStore.assign(source, inputs)
            source.save(force_insert=True)
        return source

    @staticmethod
    def discard_created(source: ExternalDataSource) -> None:
        """Delete a source that `create` made when a later step of the same create fails.

        One transaction deletes the source and its credentials row. The row stays when another object
        uses it. Do not use this for a source that was in use: the store keeps the credentials rows of those.
        """
        with transaction.atomic():
            source.delete()
            WarehouseSourceCredentialsStore.discard(source)

    @staticmethod
    def update_runtime(
        source: ExternalDataSource,
        updates: Mapping[str, Any] | None = None,
        *,
        remove: Iterable[str] = (),
        extra_update_fields: Sequence[str] = DEFAULT_EXTRA_UPDATE_FIELDS,
    ) -> dict[str, Any]:
        """Set and remove runtime keys (``cdc_*``, file upload keys) and save. Returns the stored `job_inputs`.

        A runtime write never touches a connection field. A key that is not a runtime key of the source
        raises ValueError, because a credential written here would skip the connection storage.
        """
        updates = dict(updates or {})
        remove = list(remove)
        _check_runtime_keys(source.source_type, [*updates, *remove])

        inputs = _decode(source.job_inputs)
        inputs.update(updates)
        for key in remove:
            inputs.pop(key, None)
        _stage(source, inputs)
        # A runtime write never changes the credentials, so it leaves the reference column alone. A sync
        # holds its source for a long time, and its copy of the column can be older than the row.
        source.save(update_fields=["job_inputs", *extra_update_fields])
        return inputs

    @staticmethod
    def update_oauth_inputs(
        source: ExternalDataSource,
        updates: Mapping[str, Any],
        *,
        extra_update_fields: Sequence[str] = DEFAULT_EXTRA_UPDATE_FIELDS,
    ) -> dict[str, Any]:
        """Set keys of a source without typed-in credentials and save only `job_inputs`. Returns all inputs.

        For a sync that refreshes a token that an OAuth source keeps in its inputs. The write never changes
        the reference column: the sync holds its source for a long time, and its copy of the column can be
        older than the row. Raises ValueError for a source with typed-in credentials, because its
        credentials row must get each change.
        """
        if has_typed_in_credentials(str(source.source_type)):
            raise ValueError(f"A {source.source_type} source has typed-in credentials. Use `save`.")
        inputs = _decode(source.job_inputs)
        inputs.update(updates)
        _stage(source, inputs)
        source.save(update_fields=["job_inputs", *extra_update_fields])
        return inputs

    @staticmethod
    def is_stripped(source: ExternalDataSource) -> bool:
        """True when the credentials of the source live only in its credentials row and its reference column."""
        return _stored_stripped_at(source) is not None

    @staticmethod
    async def aload(source: ExternalDataSource) -> dict[str, Any]:
        return await database_sync_to_async_pool(SourceInputsStore.load)(source)

    @staticmethod
    async def asave(
        source: ExternalDataSource,
        inputs: Mapping[str, Any],
        *,
        extra_update_fields: Sequence[str] = DEFAULT_EXTRA_UPDATE_FIELDS,
    ) -> None:
        await database_sync_to_async_pool(SourceInputsStore.save)(
            source, inputs, extra_update_fields=extra_update_fields
        )


def _stage(source: ExternalDataSource, inputs: Mapping[str, Any]) -> None:
    source.job_inputs = dict(inputs)


def _stored_stripped_at(source: ExternalDataSource) -> str | None:
    # The stored value decides, not the inputs of the write: a caller passes what `load` returned, which never
    # holds the marker.
    try:
        stored = _decode(source.job_inputs)
    except UnreadableSourceInputsError:
        return None
    if not is_stripped(stored):
        return None
    return str(stored[CONNECTION_FIELDS_STRIPPED_KEY])


def _strippable(source: ExternalDataSource, inputs: Mapping[str, Any]) -> bool:
    try:
        return strippable(source, inputs)
    except ValueError:
        # A shape that the OAuth walk does not read cannot be stripped. `assign_credentials_reference` logs it.
        return False


def _assign_stripped(
    source: ExternalDataSource,
    inputs: Mapping[str, Any],
    stripped_at: str,
    shared_credentials: SharedCredentialsEdit,
    reference: IntegrationReference | None,
) -> None:
    write_stripped_credentials(source, inputs, shared_credentials=shared_credentials, reference=reference)
    _stage(source, stripped_job_inputs(source.source_type, inputs, stripped_at))


def _decode(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str):
        raise UnreadableSourceInputsError(f"job_inputs is a {type(raw).__name__}, expected a mapping")
    try:
        decoded = json.loads(raw)
    except ValueError as e:
        raise UnreadableSourceInputsError("job_inputs is a string that does not decode as JSON") from e
    if not isinstance(decoded, Mapping):
        raise UnreadableSourceInputsError(f"job_inputs decoded to a {type(decoded).__name__}, expected a mapping")
    return dict(decoded)


def _split(source_type: str, inputs: Mapping[str, Any]) -> "SplitJobInputs":
    # noqa below: the classification loads the source registry and the generated source configs. The
    # store sits on the model import path (HogQL database build, managed warehouse checks), so it loads
    # them only when a settings read or a runtime write needs them.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415
        split_job_inputs,
    )

    return split_job_inputs(source_key(source_type), inputs)


def _has_runtime_prefix(key: str) -> bool:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415
        RUNTIME_KEY_PREFIXES,
    )

    return key.startswith(RUNTIME_KEY_PREFIXES)


def _check_runtime_keys(source_type: str, keys: Iterable[str]) -> None:
    keys = list(keys)
    if DEAD_CREDENTIALS_CLEARED_KEY in keys:
        raise ValueError("The cleanup marker is not a runtime key")
    if not keys:
        return
    try:
        split = _split(source_type, dict.fromkeys(keys))
        non_runtime = sorted({*split.connection, *split.references, *split.selectors, *split.settings})
    except ValueError:
        non_runtime = sorted(key for key in keys if not _has_runtime_prefix(key))
    if non_runtime:
        raise ValueError(f"Not runtime keys for a {source_type} source: {', '.join(non_runtime)}")
