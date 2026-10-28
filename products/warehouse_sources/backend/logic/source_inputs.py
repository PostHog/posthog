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

from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.facade.contracts import (
    CONNECTION_FIELDS_STRIPPED_KEY,
    CREDENTIALS_REFERENCE_KEY,
    SharedCredentialsEdit,
    UnreadableSourceInputsError,
)
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    is_stripped,
    mirror_connection_fields,
    needs_credentials_row,
    preload_connection_fields,
    read_connection_fields,
    read_connection_fields_many,
    strip_on_create_enabled,
    stripped_at_now,
    stripped_job_inputs,
    write_stripped_connection_fields,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
        SplitJobInputs,
    )

DEFAULT_EXTRA_UPDATE_FIELDS: tuple[str, ...] = ("updated_at",)


class SourceInputsStore:
    @staticmethod
    def load(source: ExternalDataSource) -> dict[str, Any]:
        """All inputs of the source: connection fields, sync settings and runtime state.

        The result is a new dict, so a change to it has no effect until a write method saves it. With the
        read flag on, the connection fields come from the credentials row of the source, so the model field
        can hold other values. A stripped source always reads the row, and raises
        `SourceCredentialsMissingError` (an `UnreadableSourceInputsError`) when the row is missing or unreadable.
        """
        return read_connection_fields(source, _decode(source.job_inputs))

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
        return read_connection_fields_many(sources, loaded)

    @staticmethod
    def preload(sources: Iterable[ExternalDataSource]) -> None:
        """Fetch what `load` needs for these sources in one batch, so that later `load` calls on the same
        instances add no query. Use it before a loop that calls `load` once per table of a source."""
        pairs = []
        for source in sources:
            try:
                pairs.append((source, _decode(source.job_inputs).get(CREDENTIALS_REFERENCE_KEY)))
            except UnreadableSourceInputsError:
                continue
        preload_connection_fields(pairs)

    @staticmethod
    def load_stored(source: ExternalDataSource) -> dict[str, Any]:
        """The decoded `job_inputs` as stored, never merged with the credentials row.

        Only a tool that copies or checks the stored data should use it, such as the backfill. Raises
        `UnreadableSourceInputsError` like `load`. For a stripped source the result holds no connection fields,
        and it holds the strip marker.
        """
        return _decode(source.job_inputs)

    @staticmethod
    def write_credentials_reference(source: ExternalDataSource, ref: int) -> None:
        """Set the reference to the credentials row in the stored inputs of the source, and change nothing else.

        Only a tool that links existing sources to their rows should use it, such as the backfill. It never
        copies fields to the row, and it does not change `updated_at`.
        """
        inputs = _decode(source.job_inputs)
        inputs[CREDENTIALS_REFERENCE_KEY] = ref
        _stage(source, inputs)
        source.save(update_fields=["job_inputs"])

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
        runtime = {key: value for key, value in split.runtime.items() if key != CONNECTION_FIELDS_STRIPPED_KEY}
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
    ) -> None:
        """Stage all inputs on the source without a database write. The caller must save the model.

        Use it when the caller saves the model for other reasons too, for example a DRF serializer
        update, so that the source row gets one write. The connection fields go to the credentials row
        now (behind the dual-write flag), before the caller saves the source. The staged inputs keep the
        stored reference to that row when ``inputs`` has none, and get a reference when the copy creates
        the row. ``shared_credentials`` decides what an edit of a row that other objects use does.

        For a stripped source the connection fields go only to the credentials row, and the write raises
        when that fails. `job_inputs` then gets only the references, selectors, sync settings and runtime state.
        """
        stripped_at = _stored_stripped_at(source)
        if stripped_at is not None:
            _assign_stripped(source, _with_stored_reference(source, inputs), stripped_at, shared_credentials)
            return
        staged = mirror_connection_fields(
            source, _with_stored_reference(source, inputs), shared_credentials=shared_credentials
        )
        _stage(source, staged)

    @staticmethod
    def save(
        source: ExternalDataSource,
        inputs: Mapping[str, Any],
        *,
        extra_update_fields: Sequence[str] = DEFAULT_EXTRA_UPDATE_FIELDS,
    ) -> None:
        """Replace all inputs of the source and save them."""
        # One transaction, so a failed save also undoes the copy to the credentials row.
        with transaction.atomic():
            SourceInputsStore.assign(source, inputs)
            source.save(update_fields=["job_inputs", *extra_update_fields])

    @staticmethod
    def create(*, inputs: Mapping[str, Any], **fields: Any) -> ExternalDataSource:
        """Create a source with these inputs in one insert. ``fields`` are the other model fields.

        The credentials row is created before the insert, so the insert saves the reference to it. Both
        writes are in one transaction, so a failed insert leaves no row. With the strip flag on for the team,
        a source with typed-in credentials is stripped from the start.
        """
        source = ExternalDataSource(**fields)
        with transaction.atomic():
            if strip_on_create_enabled(source.team_id) and needs_credentials_row(source, inputs):
                _assign_stripped(source, inputs, stripped_at_now(), SharedCredentialsEdit.SKIP)
            else:
                SourceInputsStore.assign(source, inputs)
            source.save(force_insert=True)
        return source

    @staticmethod
    def update_runtime(
        source: ExternalDataSource,
        updates: Mapping[str, Any] | None = None,
        *,
        remove: Iterable[str] = (),
        extra_update_fields: Sequence[str] = DEFAULT_EXTRA_UPDATE_FIELDS,
    ) -> dict[str, Any]:
        """Set and remove runtime keys (``cdc_*``, file upload keys) and save. Returns all inputs.

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
        source.save(update_fields=["job_inputs", *extra_update_fields])
        return inputs

    @staticmethod
    def is_stripped(source: ExternalDataSource) -> bool:
        """True when the connection fields of the source live only in its credentials row."""
        return _stored_stripped_at(source) is not None

    @staticmethod
    def write_stripped(source: ExternalDataSource, *, stripped_at: str) -> None:
        """Remove the connection fields from the stored `job_inputs` and set the strip marker.

        Only the strip command calls it, after it has verified the credentials row and written a backup.
        It does not change `updated_at`, because the inputs that a reader sees do not change.
        """
        _stage(source, stripped_job_inputs(source.source_type, _decode(source.job_inputs), stripped_at))
        source.save(update_fields=["job_inputs"])

    @staticmethod
    def write_restored(source: ExternalDataSource, inputs: Mapping[str, Any]) -> None:
        """Store full inputs again on a stripped source and remove the strip marker.

        Only the restore command calls it. It skips `assign`, which would strip the inputs again.
        """
        _stage(source, {key: value for key, value in inputs.items() if key != CONNECTION_FIELDS_STRIPPED_KEY})
        source.save(update_fields=["job_inputs"])

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


def _assign_stripped(
    source: ExternalDataSource,
    inputs: Mapping[str, Any],
    stripped_at: str,
    shared_credentials: SharedCredentialsEdit,
) -> None:
    staged = write_stripped_connection_fields(source, inputs, shared_credentials=shared_credentials)
    _stage(source, stripped_job_inputs(source.source_type, staged, stripped_at))


def _with_stored_reference(source: ExternalDataSource, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    # Many writers build the inputs from a parsed config, which has no reference key. The stored value
    # decides the row, so such a write cannot drop the reference and make a second row.
    if CREDENTIALS_REFERENCE_KEY in inputs:
        return inputs
    try:
        stored = _decode(source.job_inputs).get(CREDENTIALS_REFERENCE_KEY)
    except UnreadableSourceInputsError:
        return inputs
    return inputs if stored is None else {**inputs, CREDENTIALS_REFERENCE_KEY: stored}


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

    return split_job_inputs(ExternalDataSourceType(source_type), inputs)


def _has_runtime_prefix(key: str) -> bool:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (  # noqa: PLC0415
        RUNTIME_KEY_PREFIXES,
    )

    return key.startswith(RUNTIME_KEY_PREFIXES)


def _check_runtime_keys(source_type: str, keys: Iterable[str]) -> None:
    keys = list(keys)
    if not keys:
        return
    try:
        split = _split(source_type, dict.fromkeys(keys))
        non_runtime = sorted({*split.connection, *split.references, *split.selectors, *split.settings})
    except ValueError:
        non_runtime = sorted(key for key in keys if not _has_runtime_prefix(key))
    if non_runtime:
        raise ValueError(f"Not runtime keys for a {source_type} source: {', '.join(non_runtime)}")
