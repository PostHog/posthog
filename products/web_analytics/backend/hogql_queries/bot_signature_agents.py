from dataclasses import dataclass

from products.web_analytics.backend.hogql_queries.bot_definitions import derive_agent_source_slug
from products.web_analytics.backend.hogql_queries.bot_signature_agent_directory import SIGNATURE_AGENT_ENTRIES


@dataclass(frozen=True)
class SignatureAgentDefinition:
    name: str  # Display name: "ChatGPT agent"
    category: str  # Category, same vocabulary as BotDefinition: "ai_assistant", ...
    traffic_type: str  # Type, same vocabulary as BotDefinition: "AI Agent", ...
    operator: str  # Operator/company: "OpenAI"
    documentation_url: str | None = None
    # Same vocabulary as BotDefinition.agent_source, so a signed agent classifies to the
    # same slug whichever signal (UA pattern, IP range, or signature) catches it.
    agent_source: str | None = None

    @property
    def agent_source_slug(self) -> str:
        return derive_agent_source_slug(self.name, self.category, self.traffic_type, self.agent_source)


# Radar names an agent differently from our UA definition for the same software, and the
# derived slug would then split one agent across two agent_source values depending on which
# signal caught it. Keyed by the Radar name, valued by the slug the UA definition already uses.
SIGNATURE_AGENT_SOURCE_OVERRIDES: dict[str, str] = {
    "Amazon Bedrock AgentCore Browser": "amazon-bedrock-agentcore",
}


# Web Bot Auth (RFC 9421 HTTP Message Signatures): agents that sign their requests send a
# Signature-Agent header naming the domain that publishes their public keys, e.g.
# `Signature-Agent: "https://chatgpt.com"`. Servers that forward that header as the
# $signature_agent event property get classification even when the agent uses a real
# browser user agent.
#
# Keys are the normalized hosts (lowercase, no scheme/quotes), sourced from Cloudflare's
# Radar bots directory — refresh with
# products/web_analytics/scripts/refresh_signature_agents.py.
#
# Presence of the header is treated as sufficient — signatures are not verified at query
# time. Spoofing it only reclassifies the spoofer's own traffic as a bot, which is the
# outcome bot filtering wants anyway.
SIGNATURE_AGENT_DEFINITIONS: dict[str, SignatureAgentDefinition] = {
    entry["host"]: SignatureAgentDefinition(
        entry["name"],
        entry["category"],
        entry["traffic_type"],
        entry["operator"],
        documentation_url=entry["documentation_url"] or None,
        agent_source=SIGNATURE_AGENT_SOURCE_OVERRIDES.get(entry["name"]),
    )
    for entry in SIGNATURE_AGENT_ENTRIES
}
