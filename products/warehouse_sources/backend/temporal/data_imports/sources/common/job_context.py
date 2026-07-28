"""Per-job context for warehouse-source telemetry.

The activity that runs a warehouse-source sync sets a `JobContext` once at
its entry point. The tracked transports (HTTP and gRPC) read it on every
outbound call to attach `team_id`, `source_type`, `external_data_schema_id`,
`external_data_source_id`, and `external_data_job_id` to logs, metrics and
sample-capture decisions.

Stored in a `contextvars.ContextVar` so it propagates across the source
generator's thread-pool boundary — see `pipelines/pipeline/pipeline.py`'s
`copy_context()` snapshot, which already preserves contextvars when calls
hop into the executor.

This module is transport-neutral: both `common/http` and `common/grpc`
import from here. `common/http/context.py` re-exports these names for
backwards compatibility.
"""

from __future__ import annotations

import contextvars
import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from structlog.contextvars import bind_contextvars, unbind_contextvars

from posthog.exceptions_capture import bind_exception_context, exception_context

if TYPE_CHECKING:
    import uuid


@dataclasses.dataclass(frozen=True)
class JobContext:
    team_id: int
    source_type: str
    external_data_source_id: str
    external_data_schema_id: str
    external_data_job_id: str
    # Optional, human-facing sync metadata. Not bound as log fields (transports keep their
    # existing label set) but attached to captured exceptions for debugging.
    schema_name: str | None = None
    sync_type: str | None = None
    pipeline_version: str | None = None

    def as_log_fields(self) -> dict[str, int | str]:
        return {
            "team_id": self.team_id,
            "source_type": self.source_type,
            "external_data_source_id": self.external_data_source_id,
            "external_data_schema_id": self.external_data_schema_id,
            "external_data_job_id": self.external_data_job_id,
        }

    def as_exception_properties(self) -> dict[str, str | int]:
        """Source/job identity attached to every exception captured during the sync, so a generic
        pipeline failure (e.g. a PyArrow type mismatch) can be attributed to a connector."""
        properties: dict[str, str | int] = {
            "warehouse_sources_source_type": self.source_type,
            "warehouse_sources_source_id": self.external_data_source_id,
            "warehouse_sources_schema_id": self.external_data_schema_id,
            "warehouse_sources_job_id": self.external_data_job_id,
            "team_id": self.team_id,
        }
        if self.schema_name is not None:
            properties["warehouse_sources_schema_name"] = self.schema_name
        if self.sync_type is not None:
            properties["warehouse_sources_sync_type"] = self.sync_type
        if self.pipeline_version is not None:
            properties["warehouse_sources_pipeline_version"] = self.pipeline_version
        return properties


_current_job_context: contextvars.ContextVar[JobContext | None] = contextvars.ContextVar(
    "data_imports_job_context", default=None
)


_BOUND_LOG_FIELD_NAMES: tuple[str, ...] = (
    "source_type",
    "external_data_source_id",
    "external_data_schema_id",
    "external_data_job_id",
)


def current_job_context() -> JobContext | None:
    return _current_job_context.get()


def _make_context(
    *,
    team_id: int,
    source_type: str,
    external_data_source_id: str | uuid.UUID,
    external_data_schema_id: str | uuid.UUID,
    external_data_job_id: str,
    schema_name: str | None = None,
    sync_type: str | None = None,
    pipeline_version: str | None = None,
) -> JobContext:
    return JobContext(
        team_id=team_id,
        source_type=source_type,
        external_data_source_id=str(external_data_source_id),
        external_data_schema_id=str(external_data_schema_id),
        external_data_job_id=external_data_job_id,
        schema_name=schema_name,
        sync_type=sync_type,
        pipeline_version=pipeline_version,
    )


def bind_job_context(
    *,
    team_id: int,
    source_type: str,
    external_data_source_id: str | uuid.UUID,
    external_data_schema_id: str | uuid.UUID,
    external_data_job_id: str,
    schema_name: str | None = None,
    sync_type: str | None = None,
    pipeline_version: str | None = None,
) -> JobContext:
    """Set the current `JobContext`, bind matching structlog contextvars, and attach the source
    to every exception captured for the rest of this sync.

    Mirrors the existing pattern in `import_data_activity_sync` where
    `bind_contextvars(team_id=...)` is called without an explicit unbind —
    each activity invocation rebinds before doing work. The contextvar is
    per-task / per-thread, so concurrent activities don't leak.
    """
    ctx = _make_context(
        team_id=team_id,
        source_type=source_type,
        external_data_source_id=external_data_source_id,
        external_data_schema_id=external_data_schema_id,
        external_data_job_id=external_data_job_id,
        schema_name=schema_name,
        sync_type=sync_type,
        pipeline_version=pipeline_version,
    )
    _current_job_context.set(ctx)
    bind_contextvars(
        source_type=ctx.source_type,
        external_data_source_id=ctx.external_data_source_id,
        external_data_schema_id=ctx.external_data_schema_id,
        external_data_job_id=ctx.external_data_job_id,
    )
    bind_exception_context(**ctx.as_exception_properties())
    return ctx


@contextmanager
def scoped_job_context(
    *,
    team_id: int,
    source_type: str,
    external_data_source_id: str | uuid.UUID,
    external_data_schema_id: str | uuid.UUID,
    external_data_job_id: str,
    schema_name: str | None = None,
    sync_type: str | None = None,
    pipeline_version: str | None = None,
) -> Iterator[JobContext]:
    """Context-manager variant for tests / synthetic call sites.

    Resets the contextvar, unbinds structlog contextvars, and clears the exception context on exit
    so test isolation isn't dependent on subsequent activities overwriting state.
    """
    ctx = _make_context(
        team_id=team_id,
        source_type=source_type,
        external_data_source_id=external_data_source_id,
        external_data_schema_id=external_data_schema_id,
        external_data_job_id=external_data_job_id,
        schema_name=schema_name,
        sync_type=sync_type,
        pipeline_version=pipeline_version,
    )
    token = _current_job_context.set(ctx)
    bind_contextvars(
        source_type=ctx.source_type,
        external_data_source_id=ctx.external_data_source_id,
        external_data_schema_id=ctx.external_data_schema_id,
        external_data_job_id=ctx.external_data_job_id,
    )
    try:
        with exception_context(**ctx.as_exception_properties()):
            yield ctx
    finally:
        _current_job_context.reset(token)
        unbind_contextvars(*_BOUND_LOG_FIELD_NAMES)
