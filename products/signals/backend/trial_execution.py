from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from uuid import UUID


class TrialRunner(Protocol):
    def prepare(self) -> Sequence[UUID]: ...

    def start(self, execution_id: UUID) -> None: ...

    def finished(self, execution_id: UUID) -> bool: ...


class TrialCoordinator:
    def __init__(self, runner: TrialRunner) -> None:
        self.runner = runner

    def start(self) -> None:
        for execution_id in self.runner.prepare():
            self.runner.start(execution_id)

    def finished(self, execution_ids: Iterable[UUID]) -> bool:
        # A terminal TaskRun can still have agent-specific output to persist.
        return all(self.runner.finished(execution_id) for execution_id in execution_ids)
