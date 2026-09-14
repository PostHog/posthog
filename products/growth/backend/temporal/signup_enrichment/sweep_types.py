"""The shapes one enrichment sweep exposes to the generic sweep workflow.

A leaf module: it imports nothing from the sweeps, so a sweep module can import it while
sweep.py imports every sweep module to build its registry.
"""

import typing
import datetime as dt
import itertools
from collections.abc import Awaitable, Callable
from enum import StrEnum

from posthog.dataclasses import frozen


class SweepKind(StrEnum):
    ICP_REENRICHMENT = "icp_reenrichment"
    HARMONIC_STATUS_POLL = "harmonic_status_poll"


@frozen
class SweepInputs:
    kind: SweepKind
    # Overrides the sweep's daily cap setting when set (manual triggers).
    cap: int | None = None


@frozen
class SweepSelection:
    batches: list[list[dict[str, typing.Any]]]
    selected: int
    extra: dict[str, typing.Any]
    # Recorded as activity output so the workflow body never reads a registry or a setting.
    item_timeout_seconds: int
    item_max_attempts: int


@frozen
class SweepBatchInputs:
    kind: SweepKind
    items: list[dict[str, typing.Any]]


@frozen
class SweepRunReport:
    kind: SweepKind
    selected: int
    counters: dict[str, int]
    failed: int
    extra: dict[str, typing.Any]


@frozen
class SweepRunEvent:
    distinct_id: str
    event: str
    properties: dict[str, typing.Any]


SelectFn = Callable[[int | None], Awaitable[SweepSelection]]
ProcessFn = Callable[[list[dict[str, typing.Any]]], Awaitable[dict[str, int]]]
SummarizeFn = Callable[[SweepRunReport], SweepRunEvent]


@frozen
class SweepSpec:
    kind: SweepKind
    batch_size: int
    item_timeout: dt.timedelta
    item_max_attempts: int
    empty_extra: dict[str, typing.Any]
    select: SelectFn
    process: ProcessFn
    summarize: SummarizeFn

    def selection(
        self, items: list[dict[str, typing.Any]], *, extra: dict[str, typing.Any] | None = None
    ) -> SweepSelection:
        return SweepSelection(
            batches=[list(batch) for batch in itertools.batched(items, self.batch_size, strict=False)],
            selected=len(items),
            extra=extra if extra is not None else {},
            item_timeout_seconds=int(self.item_timeout.total_seconds()),
            item_max_attempts=self.item_max_attempts,
        )

    @property
    def empty_selection(self) -> SweepSelection:
        return self.selection([], extra=dict(self.empty_extra))
