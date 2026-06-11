"""Execution backend contract.

The coordinator's HTTP server hides which backend runs candidate SQL. The
sandbox sees the same response shape regardless of whether the bytes ran
on the test cluster (via Metabase) or on a local ClickHouse (via
`sync_execute`). This is what lets the coordinator swap targets without
the agent noticing.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionResult:
    rows: list[list[Any]]
    elapsed_ms: float
    rows_read: int | None
    bytes_read: int | None
    query_id: str | None


class BackendError(RuntimeError):
    """Raised by backends when ClickHouse / Metabase rejected the SQL.

    The coordinator turns this into a 502 with the backend's message —
    we don't want to leak server-side stack traces to the sandbox, but
    a focused error string is useful for the agent to react to (e.g.
    syntax error, unknown column).
    """


class ExecutionBackend(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @property
    @abc.abstractmethod
    def target(self) -> str:
        """Short identifier surfaced in `/v1/info` (e.g. `test_cluster`, `local`)."""

    @abc.abstractmethod
    def run(self, sql: str, *, timeout_s: int) -> ExecutionResult: ...

    def prompt_addendum(self) -> str:
        """Extra guidance the agent must read before issuing any query.

        Default is the empty string. Override to inject backend-specific
        instructions (e.g. team_id rewrite for the test cluster).
        """
        return ""
