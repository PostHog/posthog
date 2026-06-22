from products.tasks.backend.repo_selection.types import RepoSelectionResult

__all__ = [
    "REPO_SELECTION_DUMMY_REPOSITORY",
    "RepoSelectionRejectedError",
    "RepoSelectionResult",
    "RepoSelectionUnavailableError",
    "resolve_team_github_integration",
    "select_repository",
]

# Everything except the leaf `RepoSelectionResult` DTO lives in `agent.py`, which pulls in the
# sandbox/LLM runtime on import. Load those lazily so importing this package just for the DTO
# (e.g. from the dependency-light Signals artefact schemas) stays cheap and cycle-free.
_LAZY_FROM_AGENT = frozenset(__all__) - {"RepoSelectionResult"}


def __getattr__(name: str) -> object:
    if name in _LAZY_FROM_AGENT:
        from products.tasks.backend.repo_selection import agent

        return getattr(agent, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
