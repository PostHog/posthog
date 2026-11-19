"""Docs check callbacks for products the knowledge writer cannot import; loads on django.setup(), so keep it light."""

from collections.abc import Callable
from dataclasses import dataclass

from .contracts import IntakeStatus
from .enums import MergeCheckFailure


@dataclass(frozen=True, kw_only=True)
class FinishedDocsCheck:
    waiter_ids: tuple[str, ...] = ()
    status: IntakeStatus
    failure_reason: MergeCheckFailure | None
    pull_request_url: str | None


FinishedDocsCheckHook = Callable[[FinishedDocsCheck], None]

_finished_docs_check_hooks: list[FinishedDocsCheckHook] = []


def register_finished_docs_check_hook(hook: FinishedDocsCheckHook) -> None:
    if hook not in _finished_docs_check_hooks:
        _finished_docs_check_hooks.append(hook)


def get_finished_docs_check_hooks() -> tuple[FinishedDocsCheckHook, ...]:
    return tuple(_finished_docs_check_hooks)
