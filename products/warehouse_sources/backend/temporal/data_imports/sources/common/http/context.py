"""Backwards-compatible re-export of the transport-neutral job context.

`JobContext` and the bind/scoped/current helpers moved to
`products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context` so both the HTTP
and gRPC tracked transports can share them. This module re-exports the same
objects so existing `from ...common.http.context import ...` and
`from ...common.http import ...` imports keep working.
"""

from __future__ import annotations

from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import (
    JobContext,
    bind_job_context,
    current_job_context,
    scoped_job_context,
)

__all__ = [
    "JobContext",
    "bind_job_context",
    "current_job_context",
    "scoped_job_context",
]
