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
 * - `isCodingAgent()` matches coding agents that surface `structuredContent`
 *   to the model in preference to `content[].text`. Used to drop
 *   `structuredContent` when a `formatted_results` override is set, otherwise
 *   Claude Code (and friends) show raw JSON instead of the formatted table.
 *   Cursor is deliberately excluded — it reads text for the model and renders
 *   `structuredContent` in UI, so it does not need the workaround.
 *
 * - `isPostHogCodeConsumer()` matches the `x-posthog-mcp-consumer` header
 *   sent by the PostHog Code Tasks wrapper.
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
] as const

// Value sent in `x-posthog-mcp-consumer` by PostHog Code (the Tasks sandbox
// wrapper around the Claude Agent SDK) when the task was launched from the
// PostHog Code UI. Used to force coding-agent behavior and to gate UI-apps
// emission in single-exec mode. Slack-launched runs send `"slack"` instead.
export const POSTHOG_CODE_CONSUMER = 'posthog-code'

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
}

export class MCPClientProfile {
    readonly clientName: string | undefined
    readonly clientVersion: string | undefined
    readonly consumer: string | undefined

    private _capabilities: ClientCapabilities | undefined

    constructor(input: MCPClientProfileInput) {
        this.clientName = input.clientName
        this.clientVersion = input.clientVersion
        this.consumer = input.consumer
    }

    isCodingAgent(): boolean {
        return matchesAnyFragment(this.clientName, CODING_AGENT_CLIENT_NAME_FRAGMENTS)
    }

    isPostHogCodeConsumer(): boolean {
        return this.consumer === POSTHOG_CODE_CONSUMER
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
