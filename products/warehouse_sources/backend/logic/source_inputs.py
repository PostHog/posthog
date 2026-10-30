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
    CREDENTIALS_REFERENCE_KEY,
    SharedCredentialsEdit,
    UnreadableSourceInputsError,
)
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    mirror_connection_fields,
    shadow_compare,
    shadow_compare_many,
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

        The result is a new dict, so a change to it has no effect until a write method saves it.
        """
        inputs = _decode(source.job_inputs)
        shadow_compare(source, inputs)
        return inputs

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
        shadow_compare_many(sources, loaded)
        return loaded

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
        return {**split.settings, **split.runtime}

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
        the row. Inputs without connection fields keep no reference. ``shared_credentials`` decides what an
        edit of a row that other objects use does.
        """
        if not _has_connection_fields(source.source_type, inputs):
            # The write removes the typed-in credentials (a select switched to its OAuth option, or a managed
            # source that now gets its credentials elsewhere). A kept reference would leave the source a user
            # of its old row, so the row could not be deleted.
            _stage(source, {key: value for key, value in inputs.items() if key != CREDENTIALS_REFERENCE_KEY})
            return
        staged = mirror_connection_fields(source, inputs, shared_credentials=shared_credentials)
        _stage(source, _with_stored_reference(source, staged))

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
        writes are in one transaction, so a failed insert leaves no row.
        """
        source = ExternalDataSource(**fields)
        with transaction.atomic():
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


def _with_stored_reference(source: ExternalDataSource, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    # Many writers build the inputs from a parsed config, which has no reference key. The stored value
    # decides the row, so such a write cannot drop the reference and make a second row. The copy reads
    # the value from the database; this covers a write that skips the copy (for example, the flag is off).
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


def _has_connection_fields(source_type: str, inputs: Mapping[str, Any]) -> bool:
    try:
        return bool(_split(source_type, inputs).connection)
    except ValueError:
        # An unknown source type: keep the reference, because nothing can tell what its inputs hold.
        return True


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
