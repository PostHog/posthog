"""Limits a sandbox run token to the connections its run selected. The products that start runs register a resolver,
because the MCP Store cannot import them. Loads on django.setup(), so keep it light."""

from collections.abc import Callable
from uuid import UUID

# Maps a sandbox token, by the task it is bound to and its own id, onto the installation ids its run may reach. None
# means nothing narrows it.
RunInstallationAllowlist = Callable[[UUID, str], list[str] | None]

_resolvers: list[RunInstallationAllowlist] = []


def register_run_installation_allowlist(resolver: RunInstallationAllowlist) -> None:
    if resolver not in _resolvers:
        _resolvers.append(resolver)


def get_run_installation_allowlist_resolvers() -> tuple[RunInstallationAllowlist, ...]:
    return tuple(_resolvers)


def run_installation_allowlist(sandbox_task_id: UUID, token_id: str) -> list[str] | None:
    """The installations the run behind a sandbox token may reach. When several resolvers narrow it, only the ids every
    one of them allows remain."""
    narrowed = [allowlist for resolver in _resolvers if (allowlist := resolver(sandbox_task_id, token_id)) is not None]
    if not narrowed:
        return None
    return sorted(set(narrowed[0]).intersection(*narrowed[1:]))
