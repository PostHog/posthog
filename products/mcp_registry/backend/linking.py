"""Entity resolution between measured servers and official-registry entries.

A measured signal arrives as (team_id, $mcp_server_name) with no URL, so linking is
name-based and deliberately conservative: an advertised name like "posthog" also
matches third-party repackages of the same product, and attaching real usage stats to
the wrong entry is worse than attaching them to none. Anything ambiguous becomes a
standalone measured row with the candidates recorded for human review.
"""

import re
from dataclasses import field

from django.db.models import Q

from posthog.dataclasses import frozen

from products.mcp_registry.backend.models import MCPRegistryServer

# Curated (measured server name -> registry name) links that skip matching entirely.
# The first entry is the motivating example: name-matching "PostHog" alone is ambiguous
# between the official server and third-party repackages of it.
KNOWN_MEASURED_LINKS: dict[str, str] = {
    "PostHog": "io.github.PostHog/mcp",
}


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


@frozen
class LinkResult:
    server: MCPRegistryServer | None
    method: str  # a LINK_METHOD_CHOICES key, or "" when unresolved/ambiguous
    candidates: list[str] = field(default_factory=list)


def find_registry_match(server_name: str) -> LinkResult:
    """Resolve a measured server name against registry entries, refusing ambiguity."""
    override = KNOWN_MEASURED_LINKS.get(server_name)
    if override:
        server = MCPRegistryServer.objects.filter(registry_name=override).first()
        if server is not None:
            return LinkResult(server=server, method="override")

    normalized = normalize_name(server_name)
    if not normalized:
        return LinkResult(server=None, method="")

    # Candidate pool: registry entries whose title or name segment could plausibly be
    # this server. The SQL filter over-fetches; exactness is decided in Python.
    pool = MCPRegistryServer.objects.filter(listed_in_registry=True).filter(
        Q(display_name__icontains=server_name) | Q(registry_name__icontains=server_name)
    )[:50]
    exact: list[MCPRegistryServer] = []
    for candidate in pool:
        segment = candidate.registry_name.rsplit("/", 1)[-1]
        if normalized in (normalize_name(candidate.display_name), normalize_name(segment)):
            exact.append(candidate)

    if len(exact) == 1:
        return LinkResult(server=exact[0], method="exact_name")
    if len(exact) > 1:
        return LinkResult(server=None, method="", candidates=[c.registry_name for c in exact])
    return LinkResult(server=None, method="")


@frozen
class MeasuredServerResolution:
    server: MCPRegistryServer
    link_method: str
    link_candidates: list[str] = field(default_factory=list)


def resolve_measured_server(server_name: str) -> MeasuredServerResolution:
    """Resolve a measured server name to its registry server row.

    Falls back to a standalone (non-registry) row when no unambiguous match exists,
    reusing a previous standalone row for the same name if one was already created.
    """
    result = find_registry_match(server_name)
    if result.server is not None:
        if not result.server.is_measured:
            result.server.is_measured = True
            result.server.save(update_fields=["is_measured", "updated_at"])
        return MeasuredServerResolution(server=result.server, link_method=result.method)

    standalone = MCPRegistryServer.objects.filter(
        listed_in_registry=False, is_measured=True, display_name=server_name
    ).first()
    if standalone is None:
        standalone = MCPRegistryServer.objects.create(
            display_name=server_name,
            description="Measured via MCP Analytics; not listed in the official registry.",
            is_measured=True,
        )
    return MeasuredServerResolution(server=standalone, link_method="standalone", link_candidates=result.candidates)
