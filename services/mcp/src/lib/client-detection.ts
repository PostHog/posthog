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
 * - `isCliModeEnabled()` matches clients that should default to single-exec
 *   ("CLI") mode and drop `structuredContent` when a `formatted_results`
 *   override is set. Every known Anthropic client qualifies — matched against
 *   the `x-anthropic-client` (`vendorClient`) header, since Anthropic pools MCP
 *   transports across all its products and reports the live one there. Other
 *   coding agents are matched by self-reported client name. Cursor is
 *   deliberately excluded from the name match — it reads text for the model and
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
 * - `isClaudeUiHost()` matches Claude web and desktop — MCP Apps hosts that
 *   render interactive UI (iframes). Used to put them in single-exec mode so the
 *   `render-ui` tool is available, gated behind the `mcp-render-ui` flag.
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
    // OpenCode is a terminal coding agent (and the engine behind clients like
    // OpenWork). It connects through OpenCode's MCP client, which self-reports
    // `clientInfo.name` as `opencode`. It renders text, not MCP Apps UI, so it
    // wants single-exec mode like the other coding agents.
    'opencode',
    // Amp is Sourcegraph's coding agent; its MCP client self-reports
    // `clientInfo.name` as `amp-mcp-client` and benefits from single-exec mode.
    'amp-mcp-client',
    // Poke is an LLM-driven assistant that renders text, not MCP Apps UI, so it
    // wants the same single-exec mode as the coding agents.
    'poke',
    // Grok (xAI) — both Grok Build (the terminal coding agent) and the grok.com
    // assistant connect custom MCP servers and render text rather than MCP Apps
    // UI, so they benefit from the same single-exec mode and formatted-text
    // rendering as the other coding agents.
    'grok',
    // Ando is an LLM-driven assistant (Slack, chat, calls) whose MCP client
    // self-reports `clientInfo.name` as `ando-mcp-gateway`; it renders text and
    // benefits from the same single-exec mode as the coding agents.
    'ando-mcp-gateway',
] as const

// Known `x-anthropic-client` (`vendorClient`) header values. Anthropic pools
// MCP transports across all its products and reports the live one in this
// header, so it's the reliable identifier for an Anthropic client (the
// `initialize` body's `clientName` is the pool owner, e.g. `Anthropic/ClaudeAI`).
// Every Anthropic product runs in CLI (single-exec) mode. Matched as normalized
// substrings, so vendor-prefixed shapes like `Anthropic/ClaudeAI` resolve to
// `claudeai`.
export const ANTHROPIC_CLIENT_NAME_FRAGMENTS = ['claudecode', 'claudeai', 'cowork', 'claudedesign'] as const

// Anthropic clients connect through a pooled MCP transport and usually omit the
// `initialize` body's `clientInfo.name`, reporting their live product only in the
// `x-anthropic-client` (`vendorClient`) header. Map that vendor value to the
// canonical client-name token the MCP analytics dashboard buckets on, so these
// sessions are attributed to a real client instead of falling into "Other".
// Mirrors the vendor→name mapping in the dashboard (harnessRegistry.ts and
// models-mcp.md) — keep the three in sync.
const VENDOR_CLIENT_TO_CLIENT_NAME: Readonly<Record<string, string>> = {
    claudecode: 'claude-code',
    claudeai: 'claude-ai',
    cowork: 'cowork',
    claudedesign: 'claude-design',
}

/**
 * Resolve the client name used for analytics (`$mcp_client_name`) and the API
 * client header. Prefers the self-reported `clientInfo.name`; when that's absent
 * — as it is for Anthropic clients on the pooled transport — it falls back to a
 * canonical name derived from the `x-anthropic-client` vendor header, keeping the
 * raw vendor value for any unrecognized Anthropic product. Returns undefined when
 * neither is available.
 */
export function resolveEffectiveClientName(
    clientName: string | undefined,
    vendorClient: string | undefined
): string | undefined {
    if (clientName) {
        return clientName
    }
    if (!vendorClient) {
        return undefined
    }
    return VENDOR_CLIENT_TO_CLIENT_NAME[normalizeClientName(vendorClient)] ?? vendorClient
}

// Value sent in `x-posthog-mcp-consumer` by PostHog Code (the Tasks sandbox
// wrapper around the Claude Agent SDK) when the task was launched from the
// PostHog Code UI. Used to force coding-agent behavior and to gate UI-apps
// emission in single-exec mode. Slack-launched runs send `"slack"` and
// posthog_ai (Max) runs send `"posthog_ai"`; only PostHog Code renders MCP UI
// apps, so this is the sole consumer that gates UI-apps payload emission.
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

// Claude web and desktop are MCP Apps hosts that render interactive UI (iframes),
// so the `render-ui` tool is meaningful for them. They send `x-anthropic-client:
// ClaudeAI` (vs `ClaudeCode` for Claude Code, `Cowork` for Cowork) and
// `User-Agent: Claude-User`. The vendor client is authoritative when present:
// only `ClaudeAI` is a UI host, so Cowork and Claude Code are excluded even
// though they may share the `Claude-User` user-agent. The user-agent is a
// fallback solely for requests that omit the vendor header. We deliberately do
// NOT match `clientName` here — Anthropic pools transports, so Claude Code's
// `clientInfo.name` is also `Anthropic/ClaudeAI`, and matching it would
// misclassify Claude Code as a UI host.
export const ANTHROPIC_UI_HOST_VENDOR_FRAGMENTS = ['claudeai'] as const

// User-Agent Anthropic clients send when they connect without the
// `x-anthropic-client` header (Claude.ai web/desktop and internal Anthropic
// tooling). It's a generic Anthropic signal — Claude Code and Cowork can send it
// too — so it drives CLI-mode detection; the UI-host check reuses it as its own
// user-agent fallback.
export const ANTHROPIC_USER_AGENT_FRAGMENTS = ['claude-user'] as const
export const ANTHROPIC_UI_HOST_USER_AGENT_FRAGMENTS = ANTHROPIC_USER_AGENT_FRAGMENTS

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
    // Per-request `User-Agent` (e.g. `Claude-User` for Claude web/desktop).
    userAgent?: string | undefined
}

export class MCPClientProfile {
    readonly clientName: string | undefined
    readonly clientVersion: string | undefined
    readonly consumer: string | undefined
    readonly oauthClientName: string | undefined
    readonly vendorClient: string | undefined
    readonly userAgent: string | undefined

    private _capabilities: ClientCapabilities | undefined

    constructor(input: MCPClientProfileInput) {
        this.clientName = input.clientName
        this.clientVersion = input.clientVersion
        this.consumer = input.consumer
        this.oauthClientName = input.oauthClientName
        this.vendorClient = input.vendorClient
        this.userAgent = input.userAgent
    }

    isCliModeEnabled(): boolean {
        // Every Anthropic product runs in CLI (single-exec) mode.
        if (this.isAnthropicClient()) {
            return true
        }
        // Otherwise fall back to the self-reported client name for coding agents.
        return matchesAnyFragment(this.clientName, CODING_AGENT_CLIENT_NAME_FRAGMENTS)
    }

    isAnthropicClient(): boolean {
        // Anthropic pools MCP transports across all its products (Claude Code,
        // Claude.ai, Cowork, Claude Design, …), so the `x-anthropic-client` header
        // is the reliable signal of the live product when present. Some surfaces
        // (Claude.ai web/desktop, internal tools) connect without that header, so
        // also accept the `Claude-User` user-agent and the pooled `Anthropic/…`
        // `clientInfo.name`. Unlike `isClaudeUiHost`, matching the pooled name here
        // is safe and intended: every Anthropic product belongs in CLI mode, so
        // there is nothing to misclassify.
        return (
            matchesAnyFragment(this.vendorClient, ANTHROPIC_CLIENT_NAME_FRAGMENTS) ||
            matchesAnyFragment(this.userAgent, ANTHROPIC_USER_AGENT_FRAGMENTS) ||
            normalizeClientName(this.clientName ?? '').startsWith('anthropic')
        )
    }

    isPostHogCodeConsumer(): boolean {
        return this.consumer === POSTHOG_CODE_CONSUMER
    }

    isVibeCodingClient(): boolean {
        return matchesAnyFragment(this.oauthClientName, VIBE_CODING_OAUTH_CLIENT_NAME_FRAGMENTS)
    }

    isClaudeUiHost(): boolean {
        // The per-request vendor client (`x-anthropic-client`) is authoritative: it
        // distinguishes the Claude surfaces that pool the same MCP transport —
        // `ClaudeAI` (web/desktop, a UI-Apps host) from `Cowork` and `ClaudeCode`,
        // which render no MCP-Apps UI. When it's present, trust it exclusively; only
        // fall back to the `Claude-User` user-agent when the vendor header is absent.
        // Otherwise a non-UI surface like Cowork — which can share the `Claude-User`
        // user-agent with web/desktop — would be misclassified as a UI host.
        if (this.vendorClient) {
            return matchesAnyFragment(this.vendorClient, ANTHROPIC_UI_HOST_VENDOR_FRAGMENTS)
        }
        return matchesAnyFragment(this.userAgent, ANTHROPIC_UI_HOST_USER_AGENT_FRAGMENTS)
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

export function isCliModeEnabledClient(clientName: string | undefined): boolean {
    return new MCPClientProfile({ clientName }).isCliModeEnabled()
}

export function isPostHogCodeConsumer(mcpConsumer: string | undefined): boolean {
    return new MCPClientProfile({ consumer: mcpConsumer }).isPostHogCodeConsumer()
}

export function isVibeCodingClient(oauthClientName: string | undefined): boolean {
    return new MCPClientProfile({ oauthClientName }).isVibeCodingClient()
}

export function isClaudeUiHostClient(args: {
    vendorClient?: string | undefined
    userAgent?: string | undefined
}): boolean {
    return new MCPClientProfile(args).isClaudeUiHost()
}
