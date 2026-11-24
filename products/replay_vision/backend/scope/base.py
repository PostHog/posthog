"""What a scope is: which sessions a scanner watches, and the label it gives each one.

A scope replaces the two older stores that only ever answered "which experiment": `scanner_config`
for the native experiment type and the `experiment_targeting` column for every other type. Those stay
readable through `scope_for` until the cleanup PR drops them.
"""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from posthog.schema import RecordingsQuery


class Resolution(BaseModel, frozen=True):
    """What a scope decided about one session: the label it earns, or that it earns none.

    `key` is `None` for a session the scope watches but cannot label, which is how an experiment
    scope reports a session whose person was never exposed. The caller decides whether an
    unlabeled session is stored or dropped.
    """

    key: str | None = None
    context: dict[str, Any] | None = None


@runtime_checkable
class ScopeSource(Protocol):
    """Anything that can carry a scanner's scope: the live `ReplayScanner` row, or the
    `ScannerSnapshot` frozen onto an observation.

    Both hold the same three stores, so `scope_for` reads either through this rather than branching
    on the concrete type. The snapshot matters because the pipeline resolves a scope against the
    config that produced an observation, not against the scanner as it looks now.
    """

    @property
    def scope(self) -> dict[str, Any] | None: ...

    @property
    def scanner_config(self) -> dict[str, Any]: ...

    @property
    def experiment_targeting(self) -> dict[str, Any] | None: ...

    @property
    def scanner_type(self) -> Any: ...


class Scope(Protocol):
    """One kind of scope. The registry maps `scope.kind` to an implementation."""

    kind: str

    def recordings_filter(self, query: RecordingsQuery) -> RecordingsQuery:
        """Narrow a recordings query to the sessions this scope watches."""
        ...

    def as_stored(self) -> dict[str, Any]:
        """The blob to persist in `ReplayScanner.scope`, including its `kind`."""
        ...
