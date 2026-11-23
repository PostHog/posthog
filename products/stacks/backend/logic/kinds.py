"""What each definition kind needs from the rest of PostHog: API scopes, and where its entity opens in the app."""

from __future__ import annotations

from collections.abc import Iterable

from .. import engine_adapter
from ..facade.contracts import StackServiceError
from ..facade.enums import StackErrorKind

# App paths by kind, under the project. A kind whose page is not addressed by its entity id has none.
_ENTITY_PATHS: dict[str, str] = {
    "action": "data-management/actions/{entity_id}",
    "alert": "alerts?alert_type=insights&alert_id={entity_id}",
    "cohort": "cohorts/{entity_id}",
    "dashboard": "dashboard/{entity_id}",
    "destination": "functions/{entity_id}",
    "event": "data-management/events/{entity_id}",
    "experiment": "experiments/{entity_id}",
    "flag": "feature_flags/{entity_id}",
    "source": "data-management/sources/{entity_id}/schemas",
    "survey": "surveys/{entity_id}",
}


def _unsupported(kind: str) -> StackServiceError:
    return StackServiceError(
        StackErrorKind.INVALID,
        "kind_unsupported",
        f"Stacks cannot manage the kind {kind} yet. Remove it and run check.",
    )


def kind_scopes(kind: str) -> dict[str, list[str]]:
    """The kind's read and write scopes from its mapping. An unknown kind, or one with no scopes, is refused."""
    try:
        scopes = engine_adapter.kind_scopes(kind)
    except engine_adapter.EngineFailure as failure:
        raise _unsupported(kind) from failure
    if not scopes["read"] or not scopes["write"]:
        raise _unsupported(kind)
    return scopes


def run_scopes(kinds: Iterable[str], *, write: bool) -> list[str]:
    """The scopes a run over these kinds uses. A push's write list already holds the reads it needs."""
    half = "write" if write else "read"
    return sorted({scope for kind in sorted(set(kinds)) for scope in kind_scopes(kind)[half]})


def read_scopes(scopes: Iterable[str]) -> list[str]:
    """The read half of a scope list. A diff's readers need these."""
    return sorted({f"{scope.split(':', 1)[0]}:read" for scope in scopes})


def entity_path(kind: str, entity_id: str) -> str | None:
    path = _ENTITY_PATHS.get(kind)
    return path.format(entity_id=entity_id) if path else None


def scope_ceiling() -> list[str]:
    """Every scope a stack run may ever hold, from the mapping of every kind. The OAuth application has this ceiling."""
    return sorted(
        {scope for kind in engine_adapter.mapped_kinds() for scope in engine_adapter.kind_scopes(kind)["write"]}
    )
