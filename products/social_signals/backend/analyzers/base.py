"""Analyzer protocol shared by every mention analyzer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..models import Mention


@runtime_checkable
class MentionAnalyzer(Protocol):
    """Run-on-mention work that produces a single structured result row.

    Implementations are stateless — :meth:`run` may be called concurrently for
    different mentions. Side effects (LLM calls, network) are fine; persistence
    of the result row is the task runner's job.
    """

    kind: ClassVar[str]
    enabled_by_default: ClassVar[bool]
    model_used: ClassVar[str]

    def run(self, mention: "Mention") -> dict[str, Any]: ...
