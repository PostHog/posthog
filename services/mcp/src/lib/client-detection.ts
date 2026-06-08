/**
 * MCP client profiling and capability detection.
 *
 * `clientInfo.name` is what a client self-reports during the `initialize`
 * handshake. We use substring matching (with separators stripped and case
 * normalized) so variants like "claude-code", "Claude Code", "claude-code-cli",
 * and "claude-code/1.2.3" all resolve to the same form.
 *
 * The `MCPClientProfile` class owns all per-client behavior decisions:
 *
 * - `isCodingAgent()` matches coding agents that should default to single-exec
 *   mode and drop `structuredContent` when a `formatted_results` override is
 *   set. Cursor is deliberately excluded — it reads text for the model and
 *   renders `structuredContent` in UI, so it does not need single-exec mode or
 *   the formatted-results workaround.
 *
 * - `isPostHogCodeConsumer()` matches the `x-posthog-mcp-consumer` header
 *   sent by the PostHog Code Tasks wrapper.
 *
 * - `isVibeCodingClient()` matches the OAuth application name (returned by
 *   token introspection — see `StateManager._fetchApiKey`). Vibe-coding
 *   platforms like Lovable and Replit connect through their own OAuth app
 *   while reporting a generic `clientInfo.name`, so the OAuth name is the
 *   reliable identifier. Used to force single-exec mode regardless of the
 *   self-reported MCP client name.
 *
 * - `capabilities` is a feature-flag-style object describing protocol
 *   features the client actually implements (e.g. `supportsInstructions` —
 *   Codex ignores the `instructions` field returned from `initialize`).
 */

function normalizeClientName(s: string): string {
    return s.toLowerCase().replace(/[-_\s]+/g, '')
}

function matchesAnyFragment(clientName: string | undefined, fragments: readonly string[]): boolean {
    if (!clientName) {
        return false
    }
    const normalized = normalizeClientName(clientName)
    if (!normalized) {
        return false
    }
    return fragments.some((fragment) => normalized.includes(normalizeClientName(fragment)))
}

export const CODING_AGENT_CLIENT_NAME_FRAGMENTS = [
    'claude-code',
    // Cursor sends `content[].text` to the model and displays `structuredContent` in UI,
    // so it doesn't need this workaround — leaving structuredContent available for the UI.
    // 'cursor',
    'cline',
    'roo-code',
    'roo-cline',
    'continue',
    'codex',
    'windsurf',
    'zed',
    'aider',
    'copilot',
    'gemini-cli',
    // Devin self-reports `clientInfo.name` as `Devin`; it's a coding agent and
    // benefits from the same single-exec mode.
    'devin',
    // LibreChat is a general MCP client, but benefits from the same CLI-shaped
    // single-exec mode as coding agents.
    'librechat',
    // Notion AI ships its own `notion-mcp-client` (not a coding agent per se,
    // but an LLM-driven consumer that benefits from the same single-exec mode
    // and formatted-text rendering as coding agents).
    'notion',
] as const

// Value sent in `x-posthog-mcp-consumer` by PostHog Code (the Tasks sandbox
// wrapper around the Claude Agent SDK) when the task was launched from the
// PostHog Code UI. Used to force coding-agent behavior and to gate UI-apps
// emission in single-exec mode. Slack-launched runs send `"slack"` instead.
export const POSTHOG_CODE_CONSUMER = 'posthog-code'

// OAuth application names (from token introspection) for upstream tools that
// should default to single-exec mode. These match against the OAuth
// `client_name` (the registered OAuth app name in PostHog), not the MCP
// `clientInfo.name` self-report — many of these platforms connect through a
// generic MCP client wrapper, so the OAuth name is what reliably identifies
// the upstream tool. Substring match is case-insensitive and separator-agnostic
// so "Lovable", "Lovable.dev", "Replit", and "Replit Agent" all resolve.
// Notion is included here because a sizeable share of sessions only carry the
// OAuth name without the `notion-mcp-client` self-report.
export const VIBE_CODING_OAUTH_CLIENT_NAME_FRAGMENTS = ['lovable', 'replit', 'notion'] as const

export type ClientCapabilities = {
    // MCP `initialize` response includes an `instructions` field that most
    // clients inject into the model's system prompt. Codex discards it, so
    // we skip sending it (saving the payload cost) for those sessions.
    supportsInstructions: boolean
}

export const DEFAULT_CLIENT_CAPABILITIES: ClientCapabilities = {
    supportsInstructions: true,
}

type CapabilityOverride = {
    fragments: readonly string[]
    capabilities: Partial<ClientCapabilities>
}

const CLIENT_CAPABILITY_OVERRIDES: readonly CapabilityOverride[] = [
    {
        fragments: ['codex'],
        capabilities: { supportsInstructions: false },
    },
]

type MCPClientProfileInput = {
    clientName?: string | undefined
    clientVersion?: string | undefined
    consumer?: string | undefined
    oauthClientName?: string | undefined
    // Per-request `x-anthropic-client` value (e.g. `ClaudeCode`, `ClaudeAI`).
    // Anthropic pools MCP transports across products, so the live inner client
    // can disagree with the session-pinned `clientName` from `initialize`.
    vendorClient?: string | undefined
}

export class MCPClientProfile {
    readonly clientName: string | undefined
    readonly clientVersion: string | undefined
    readonly consumer: string | undefined
    readonly oauthClientName: string | undefined
    readonly vendorClient: string | undefined

    private _capabilities: ClientCapabilities | undefined

    constructor(input: MCPClientProfileInput) {
        this.clientName = input.clientName
        this.clientVersion = input.clientVersion
        this.consumer = input.consumer
        this.oauthClientName = input.oauthClientName
        this.vendorClient = input.vendorClient
    }

    isCodingAgent(): boolean {
        return matchesAnyFragment(this.vendorClient ?? this.clientName, CODING_AGENT_CLIENT_NAME_FRAGMENTS)
    }

    isPostHogCodeConsumer(): boolean {
        return this.consumer === POSTHOG_CODE_CONSUMER
    }

    isVibeCodingClient(): boolean {
        return matchesAnyFragment(this.oauthClientName, VIBE_CODING_OAUTH_CLIENT_NAME_FRAGMENTS)
    }

    get capabilities(): ClientCapabilities {
        if (!this._capabilities) {
            this._capabilities = this._resolveCapabilities()
        }
        return this._capabilities
    }

    private _resolveCapabilities(): ClientCapabilities {
        const resolved: ClientCapabilities = { ...DEFAULT_CLIENT_CAPABILITIES }
        for (const override of CLIENT_CAPABILITY_OVERRIDES) {
            if (matchesAnyFragment(this.clientName, override.fragments)) {
                Object.assign(resolved, override.capabilities)
            }
        }
        return resolved
    }
}

export function isCodingAgentClient(clientName: string | undefined): boolean {
    return new MCPClientProfile({ clientName }).isCodingAgent()
}

export function isPostHogCodeConsumer(mcpConsumer: string | undefined): boolean {
    return new MCPClientProfile({ consumer: mcpConsumer }).isPostHogCodeConsumer()
}

export function isVibeCodingClient(oauthClientName: string | undefined): boolean {
    return new MCPClientProfile({ oauthClientName }).isVibeCodingClient()
}
