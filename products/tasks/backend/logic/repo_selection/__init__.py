from typing import TYPE_CHECKING

from products.tasks.backend.logic.repo_selection.types import RepoSelectionResult

if TYPE_CHECKING:
    # Visible to type checkers (so re-exports keep their real types, e.g. the exception classes
    # used in `except` clauses) without triggering the heavy runtime import — `__getattr__` below
    # loads them lazily at runtime.
    from products.tasks.backend.logic.repo_selection.agent import (
        REPO_SELECTION_DUMMY_REPOSITORY,
        RepoSelectionRejectedError,
        RepoSelectionUnavailableError,
        resolve_team_github_integration,
        select_repository,
    )
    from products.tasks.backend.logic.repo_selection.cascade import select_repository_for_message

__all__ = [
    "REPO_SELECTION_DUMMY_REPOSITORY",
    "RepoSelectionRejectedError",
    "RepoSelectionResult",
    "RepoSelectionUnavailableError",
    "resolve_team_github_integration",
    "select_repository",
    "select_repository_for_message",
]

# Everything except the leaf `RepoSelectionResult` DTO lives in `agent.py` / `cascade.py`, which
# pull in the sandbox/LLM runtime on import. Load those lazily so importing this package just for
# the DTO (e.g. from the dependency-light Signals artefact schemas) stays cheap and cycle-free.
_LAZY_FROM_AGENT = frozenset(
    {
        "REPO_SELECTION_DUMMY_REPOSITORY",
        "RepoSelectionRejectedError",
        "RepoSelectionUnavailableError",
        "resolve_team_github_integration",
        "select_repository",
    }
)
_LAZY_FROM_CASCADE = frozenset({"select_repository_for_message"})


def __getattr__(name: str) -> object:
    if name in _LAZY_FROM_AGENT:
        from products.tasks.backend.logic.repo_selection import agent

        return getattr(agent, name)
    if name in _LAZY_FROM_CASCADE:
        from products.tasks.backend.logic.repo_selection import cascade

        return getattr(cascade, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
