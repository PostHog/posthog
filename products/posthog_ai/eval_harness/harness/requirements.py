"""Suite kinds and the shared infrastructure each one requires.

Django-free on purpose: ``env_preflight`` (on ``__main__``'s top-level import
chain) reads the kind → env-model mapping before ``django.setup()`` runs.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable


class Infra(enum.Enum):
    """One bootable piece of shared eval infrastructure."""

    DATABASE = "database"
    """The eval test database (Postgres + persons DB + ClickHouse)."""

    PERSONHOG = "personhog"
    """The personhog replica/router pair person reads route through."""

    LIVE_SERVER = "live_server"
    """The Django live server sandboxes and the MCP server call back into."""

    LLM_GATEWAY = "llm_gateway"
    """The gateway proxying the sandboxed agent's model calls."""

    MCP_SERVER = "mcp_server"
    """The MCP server the sandboxed agent's tools talk to."""

    DEMO_DATA = "demo_data"
    """The master Hedgebox seed team and per-case team factory."""

    SANDBOX = "sandbox"
    """The sandbox provider, local skills build, and the Temporal environment."""


class SuiteKind(enum.Enum):
    """How a suite's cases execute; declared per module via ``SUITE_KIND``."""

    SANDBOXED = "sandboxed"
    """The coding agent runs in a real sandbox; the default when unset."""

    ONE_SHOT = "one-shot"
    """One in-process model invocation per case — no sandbox, no servers."""


_IMPLIES: dict[Infra, frozenset[Infra]] = {
    Infra.LIVE_SERVER: frozenset({Infra.DATABASE}),
    # Both services take the live server URL as their upstream.
    Infra.LLM_GATEWAY: frozenset({Infra.LIVE_SERVER}),
    Infra.MCP_SERVER: frozenset({Infra.LIVE_SERVER}),
    # Demo seeding's person/group reads go through the personhog router; a dead
    # router would poison its 30s negative group-types cache for the whole run.
    Infra.DEMO_DATA: frozenset({Infra.DATABASE, Infra.PERSONHOG}),
    Infra.SANDBOX: frozenset({Infra.LLM_GATEWAY, Infra.MCP_SERVER, Infra.DEMO_DATA}),
}

INFRA_BY_KIND: dict[SuiteKind, frozenset[Infra]] = {
    SuiteKind.SANDBOXED: frozenset(Infra),
    SuiteKind.ONE_SHOT: frozenset({Infra.DATABASE, Infra.PERSONHOG, Infra.DEMO_DATA}),
}


def expand(infra: Iterable[Infra]) -> frozenset[Infra]:
    """Close a requirement set over implications, so a kind can never request
    a service without the things that service needs to come up."""
    result = set(infra)
    pending = list(result)
    while pending:
        for implied in _IMPLIES.get(pending.pop(), ()):
            if implied not in result:
                result.add(implied)
                pending.append(implied)
    return frozenset(result)


def infra_union(kinds: Iterable[SuiteKind]) -> frozenset[Infra]:
    """The infrastructure the harness must boot for a run over these suite kinds."""
    required: set[Infra] = set()
    for kind in kinds:
        required |= INFRA_BY_KIND[kind]
    return expand(required)
