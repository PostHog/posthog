from dataclasses import dataclass


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
# browser user agent. Keys here are the normalized hosts (lowercase, no scheme/quotes).
#
# Presence of the header is treated as sufficient — signatures are not verified at query
# time. Spoofing it only reclassifies the spoofer's own traffic as a bot, which is the
# outcome bot filtering wants anyway.
SIGNATURE_AGENT_DEFINITIONS: dict[str, SignatureAgentDefinition] = {
    "chatgpt.com": SignatureAgentDefinition(
        "ChatGPT agent",
        "ai_assistant",
        "AI Agent",
        "OpenAI",
        documentation_url="https://help.openai.com/en/articles/11845367-chatgpt-agent-allowlisting",
    ),
    "operator.openai.com": SignatureAgentDefinition(
        "OpenAI Operator",
        "ai_assistant",
        "AI Agent",
        "OpenAI",
        documentation_url="https://help.openai.com/en/articles/11845367-chatgpt-agent-allowlisting",
    ),
}
