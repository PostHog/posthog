"""Durable, source-defined sync cursors.

A cursor is a position that only the source knows how to read from, such as a Postgres xmin ceiling
or a set of Kafka partition offsets. The source defines its shape as a dataclass. The pipeline
persists it on the schema after the rows of the run are durable, so a run that fails before its
load finishes reads the same window again instead of skipping it.

Unlike the incremental field, the pipeline does not derive a cursor from the rows. Unlike resumable
state, a cursor outlives the job: it is the starting point of the next run.
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Protocol, TypeVar, cast

from structlog.types import FilteringBoundLogger

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs


# The key in `ExternalDataSchema.sync_type_config` that holds the promoted cursor.
SOURCE_CURSOR_KEY = "source_cursor"


class SourceCursor(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]
    # Stored beside the cursor, so a stored cursor of another shape is never loaded into this class.
    # It must stay stable: a changed kind discards every stored cursor of this class.
    cursor_kind: ClassVar[str]


CursorT = TypeVar("CursorT", bound=SourceCursor)


class SourceCursorManager(Generic[CursorT]):
    """The cursor one run reads from, and the cursor it stages for the pipeline to persist."""

    def __init__(self, cursor_class: type[CursorT], stored: CursorT | None, source: CursorSource[CursorT]) -> None:
        self._cursor_class = cursor_class
        self._stored = stored
        self._source = source
        self._staged: CursorT | None = None

    @classmethod
    def from_sync_type_config(
        cls,
        source: CursorSource[CursorT],
        sync_type_config: Mapping[str, Any] | None,
        logger: FilteringBoundLogger,
    ) -> SourceCursorManager[CursorT]:
        """Build a manager from the stored schema config, or with no cursor when `sync_type_config` is None."""
        cursor_class = source.cursor_class()
        stored: CursorT | None = None
        if sync_type_config is not None:
            payload = sync_type_config.get(SOURCE_CURSOR_KEY)
            if payload is None:
                stored = source.cursor_from_legacy(sync_type_config)
            else:
                stored = _cursor_from_payload(cursor_class, payload, logger)
        return cls(cursor_class, stored, source)

    def load(self) -> CursorT | None:
        return self._stored

    def stage(self, cursor: CursorT) -> None:
        """Hold `cursor` for the pipeline to persist after this run's rows are written.

        Staging again replaces the earlier staged cursor. The source's `merge_cursors` runs against
        the cursor this run loaded, so a run that read less never moves the stored cursor back.
        """
        self._staged = cursor if self._stored is None else self._source.merge_cursors(self._stored, cursor)

    @property
    def staged(self) -> CursorT | None:
        return self._staged

    def staged_payload(self) -> dict[str, Any] | None:
        if self._staged is None:
            return None
        return cursor_to_payload(self._staged)


class CursorSource(ABC, Generic[CursorT]):
    """Capability for a source that keeps a durable cursor of its own between runs."""

    @abstractmethod
    def cursor_class(self) -> type[CursorT]: ...

    def merge_cursors(self, current: CursorT, candidate: CursorT) -> CursorT:
        """The cursor to store when a run stages `candidate` over the stored `current`."""
        return candidate

    def cursor_from_legacy(self, sync_type_config: Mapping[str, Any]) -> CursorT | None:
        """Read a cursor that an earlier release stored under source-specific keys."""
        return None

    def get_cursor_manager(self, inputs: SourceInputs) -> SourceCursorManager[CursorT]:
        if inputs.source_cursor is None:
            raise ValueError(f"{type(self).__name__} ran without a source cursor manager")
        return cast(SourceCursorManager[CursorT], inputs.source_cursor)


def build_cursor_manager(
    source: object, sync_type_config: Mapping[str, Any] | None, logger: FilteringBoundLogger
) -> SourceCursorManager[Any] | None:
    """The cursor manager for a `CursorSource`, or None for any other source."""
    if not isinstance(source, CursorSource):
        return None
    return SourceCursorManager.from_sync_type_config(source, sync_type_config, logger)


def cursor_to_payload(cursor: SourceCursor) -> dict[str, Any]:
    return {"kind": cursor.cursor_kind, "data": dataclasses.asdict(cast(Any, cursor))}


def merge_cursor_payloads(
    source: object, current_payload: Any, candidate_payload: Any, logger: FilteringBoundLogger
) -> dict[str, Any]:
    """Merge a staged cursor against the cursor stored at promotion time."""
    if not isinstance(source, CursorSource):
        raise ValueError(f"{type(source).__name__} does not support source cursors")
    cursor_class = source.cursor_class()
    candidate = _cursor_from_payload(cursor_class, candidate_payload, logger)
    if candidate is None:
        raise ValueError("The staged source cursor is invalid")
    current = _cursor_from_payload(cursor_class, current_payload, logger)
    return cursor_to_payload(candidate if current is None else source.merge_cursors(current, candidate))


def _cursor_from_payload(cursor_class: type[CursorT], payload: Any, logger: FilteringBoundLogger) -> CursorT | None:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), Mapping):
        logger.warning("Discarding a stored source cursor that is not a mapping")
        return None
    if payload.get("kind") != cursor_class.cursor_kind:
        logger.warning(
            "Discarding a stored source cursor of another kind",
            stored_kind=payload.get("kind"),
            expected_kind=cursor_class.cursor_kind,
        )
        return None

    # Fields the running code does not know come from a cursor that a newer deploy wrote. Dropping
    # them lets a rollback keep running. Passing them through raises TypeError on every run.
    data: Mapping[str, Any] = payload["data"]
    known = {field.name for field in dataclasses.fields(cast(Any, cursor_class))}
    try:
        return cursor_class(**{name: value for name, value in data.items() if name in known})
    except TypeError:
        logger.warning("Discarding a stored source cursor that is missing fields", kind=cursor_class.cursor_kind)
        return None
