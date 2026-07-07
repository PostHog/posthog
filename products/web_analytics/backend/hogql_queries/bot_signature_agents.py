from dataclasses import dataclass

from products.web_analytics.backend.hogql_queries.bot_signature_agent_directory import SIGNATURE_AGENT_ENTRIES


@dataclass(frozen=True)
class SignatureAgentDefinition:
    name: str  # Display name: "ChatGPT agent"
    category: str  # Category, same vocabulary as BotDefinition: "ai_assistant", ...
    traffic_type: str  # Type, same vocabulary as BotDefinition: "AI Agent", ...
    operator: str  # Operator/company: "OpenAI"
    documentation_url: str | None = None


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
    )
    for entry in SIGNATURE_AGENT_ENTRIES
}
