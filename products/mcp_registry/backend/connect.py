"""Connection instructions: how an agent gets from "found a server" to "using it".

The instruction set is a list of methods ordered by how hands-off they are for the
human, each made of actor-typed steps (``agent`` executes autonomously, ``human`` is
a step only a person can do). Agents should attempt the first method and read a
human step as "narrate this to the user, then wait", e.g. "Create an account at X
and paste the API key", which is exactly the walk-through UX the instructions exist
to drive.

Method taxonomy, most to least automated:

- ``agent_provisioning``: an agent can provision an account/credential itself,
  either through a vendor-specific API the server declares support for, or through
  Stripe Projects (https://docs.stripe.com/stripe-projects) for its partner
  providers: the Stripe CLI provisions the service in the user's own provider
  account and delivers agent-readable credentials to a secret store. Always
  preferred when available.
- ``remote_open``: hosted server, no auth. Agent connects instantly.
- ``cli_auth``: the vendor's own CLI can mint local credentials (``<vendor> login``)
  that the MCP server or agent then reuses; often one browser tap, sometimes zero if
  the user already logged in for other work.
- ``remote_oauth``: standard MCP OAuth (discovery + DCR); the human's only step is
  the consent click in the browser. An agent with browser control can even drive the
  consent page itself, subject to the user's approval.
- ``remote_api_key``: the human must mint a key on the vendor's site; the agent
  tells them exactly where and takes over from paste onward.
- ``local_package``: no hosted remote; the agent runs the published package locally.

Defaults are derived from probe results (auth_method, remotes, packages). Per-server
knowledge that probing can't discover (signup URLs, key locations, CLI commands,
agent-provisioning endpoints) lives in ``connect_overrides`` on the row, with a
small curated seed in KNOWN_CONNECT_OVERRIDES.
"""

import re
from typing import Any

from products.mcp_registry.backend.linking import normalize_name
from products.mcp_registry.backend.models import MCPRegistryServer

# Stripe Projects partner providers (developer preview), keyed by normalized server
# name and valued with the provider slug `stripe projects service add` expects. The
# CLI provisions from Stripe's own curated provider list, so a mis-attached entry can
# at worst show these steps on the wrong server row, never provision the wrong vendor.
# Partner list: https://docs.stripe.com/stripe-projects
STRIPE_PROJECTS_PROVIDERS: dict[str, str] = {
    "chroma": "chroma",
    "clerk": "clerk",
    "kernel": "kernel",
    "klaviyo": "klaviyo",
    "neon": "neon",
    "planetscale": "planetscale",
    "posthog": "posthog",
    "railway": "railway",
    "runloop": "runloop",
    "supabase": "supabase",
    "turso": "turso",
    "vercel": "vercel",
}


def _stripe_projects_provider(server: MCPRegistryServer) -> str | None:
    segment = server.registry_name.rsplit("/", 1)[-1] if server.registry_name else ""
    for candidate in (server.display_name, segment):
        provider = STRIPE_PROJECTS_PROVIDERS.get(normalize_name(candidate))
        if provider:
            return provider
    return None


# Curated per-server overrides, keyed by registry name. Same shape as the
# connect_overrides JSON field: {"methods": [...]} replaces the derived methods,
# {"extra_methods": [...]} prepends. Row-level overrides win over this seed.
KNOWN_CONNECT_OVERRIDES: dict[str, dict[str, Any]] = {
    "io.github.PostHog/mcp": {
        "extra_methods": [
            {
                "method": "remote_api_key",
                "automation": "human_required",
                "summary": "Fallback when OAuth is unavailable: connect with a personal API key.",
                "steps": [
                    {
                        "actor": "human",
                        "description": (
                            "Create a personal API key in PostHog under Settings -> Personal API keys, "
                            "with the scopes the agent asks for."
                        ),
                        "command": None,
                    },
                    {
                        "actor": "agent",
                        "description": "Add the server with the provided key as a Bearer token.",
                        "command": 'claude mcp add posthog --transport http https://mcp.posthog.com/mcp --header "Authorization: Bearer ${POSTHOG_API_KEY}"',
                    },
                ],
            }
        ],
    },
}


def _slug(server: MCPRegistryServer) -> str:
    base = server.registry_name.rsplit("/", 1)[-1] if server.registry_name else server.display_name
    return re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-") or "server"


def _remote_url(server: MCPRegistryServer) -> str:
    return server.canonical_url


def _derived_methods(server: MCPRegistryServer) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    slug = _slug(server)
    url = _remote_url(server)

    stripe_provider = _stripe_projects_provider(server)
    if stripe_provider:
        methods.append(
            {
                "method": "agent_provisioning",
                "automation": "one_click",
                "summary": "Stripe Projects partner: the agent provisions the account and credentials via the "
                "Stripe CLI; the human only approves the one-time Stripe prompt (and any paid plan).",
                "steps": [
                    {
                        "actor": "agent",
                        "description": "Provision the service into the user's own provider account; credentials "
                        "land in the project's secret store, agent-readable.",
                        "command": f"stripe projects service add {stripe_provider}",
                    },
                    {
                        "actor": "human",
                        "description": "Approve the Stripe prompt if this is the first provisioned service or a "
                        "paid plan is selected.",
                        "command": None,
                    },
                    {
                        "actor": "agent",
                        "description": "Connect the MCP server using the provisioned credential from the secret "
                        "store, then verify with a test call.",
                        "command": None,
                    },
                ],
            }
        )

    if server.supports_agent_provisioning and url:
        methods.append(
            {
                "method": "agent_provisioning",
                "automation": "full",
                "summary": "The vendor lets agents provision an account/credential via API, with no human steps.",
                "steps": [
                    {
                        "actor": "agent",
                        "description": "Provision a credential through the vendor's agent-signup API, then connect.",
                        "command": None,
                    }
                ],
            }
        )

    if url and server.liveness == "alive_open":
        methods.append(
            {
                "method": "remote_open",
                "automation": "full",
                "summary": "Hosted server with no auth; connects instantly.",
                "steps": [
                    {
                        "actor": "agent",
                        "description": "Add the server and start calling tools.",
                        "command": f"claude mcp add {slug} --transport http {url}",
                    }
                ],
            }
        )
    elif url and server.auth_method == "oauth":
        methods.append(
            {
                "method": "remote_oauth",
                "automation": "one_click",
                "summary": "OAuth server; the only human step is the consent click in the browser.",
                "steps": [
                    {
                        "actor": "agent",
                        "description": "Add the server; the client runs OAuth discovery and registration.",
                        "command": f"claude mcp add {slug} --transport http {url}",
                    },
                    {
                        "actor": "human",
                        "description": "Approve the consent screen that opens in the browser.",
                        "command": None,
                    },
                ],
            }
        )
    elif url and server.auth_method == "api_key":
        methods.append(
            {
                "method": "remote_api_key",
                "automation": "human_required",
                "summary": "Requires an API key minted by the user on the vendor's site.",
                "steps": [
                    {
                        "actor": "human",
                        "description": (
                            f"Create an account / API key with the vendor"
                            + (f" (docs: {server.website_url})" if server.website_url else "")
                            + ", then hand the key to the agent."
                        ),
                        "command": None,
                    },
                    {
                        "actor": "agent",
                        "description": "Add the server with the provided key and verify the connection.",
                        "command": f'claude mcp add {slug} --transport http {url} --header "Authorization: Bearer ${{API_KEY}}"',
                    },
                ],
            }
        )
    elif url:
        methods.append(
            {
                "method": "remote_oauth",
                "automation": "one_click",
                "summary": "Hosted server behind auth (method unverified); attempt the standard OAuth flow first.",
                "steps": [
                    {
                        "actor": "agent",
                        "description": "Add the server and attempt OAuth; fall back to asking the user for a key.",
                        "command": f"claude mcp add {slug} --transport http {url}",
                    },
                    {
                        "actor": "human",
                        "description": "Approve the consent screen if one opens; otherwise provide a key when asked.",
                        "command": None,
                    },
                ],
            }
        )

    package = next((p for p in server.packages if p.get("registry_type") in (None, "npm")), None)
    if package:
        methods.append(
            {
                "method": "local_package",
                "automation": "full",
                "summary": "Run the published package locally (auth requirements may still apply at runtime).",
                "steps": [
                    {
                        "actor": "agent",
                        "description": "Add the server as a local process.",
                        "command": f"claude mcp add {slug} -- npx -y {package['identifier']}",
                    }
                ],
            }
        )
    return methods


def build_connect_instructions(server: MCPRegistryServer) -> dict[str, Any]:
    """Full connection profile for one server, overrides applied."""
    overrides = server.connect_overrides or KNOWN_CONNECT_OVERRIDES.get(server.registry_name, {})
    if overrides.get("methods"):
        methods = list(overrides["methods"])
    else:
        methods = _derived_methods(server)
        if overrides.get("extra_methods"):
            methods = methods + list(overrides["extra_methods"])

    return {
        "recommended": methods[0]["method"] if methods else None,
        "methods": methods,
        "auth_method": server.auth_method,
        "liveness": server.liveness,
        "notes": overrides.get("notes", ""),
    }
