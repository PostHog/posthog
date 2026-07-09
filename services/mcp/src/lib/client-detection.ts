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
 * - `isToolsModeClient()` matches the clients that keep the full per-tool
 *   roster ("tools" mode) instead of the single-exec CLI default. This is the
 *   only way a client lands in tools mode without an explicit `?mode=` /
 *   `x-posthog-mcp-mode` override — see `resolveMode`.
 *
 * - `isCliModeEnabled()` matches clients that should drop `structuredContent`
 *   when a `formatted_results` override is set. Every known Anthropic client
 *   qualifies — matched against the `x-anthropic-client` (`vendorClient`)
 *   header, since Anthropic pools MCP transports across all its products and
 *   reports the live one there. Other coding agents are matched by
 *   self-reported client name. Cursor is deliberately excluded from the name
 *   match — it reads text for the model and renders `structuredContent` in UI,
 *   so it does not need the formatted-results workaround.
 *
 * - `isPostHogCodeConsumer()` matches the `x-posthog-mcp-consumer` header
 *   sent by the PostHog Code Tasks wrapper.
 *
 * - `isClaudeUiHost()` matches Claude web/desktop and Cowork — MCP Apps hosts
 *   that render interactive UI (iframes). Used to advertise the `render-ui`
 *   tool to them, gated behind the `mcp-render-ui` flag.
 *
 * - `isClaudeChatHost()` matches Claude web/desktop only — the chat surfaces that
 *   report `supportsInstructions` but never surface the `instructions` payload to
 *   the model. Used to keep the env-context on the exec command description for
 *   them. Cowork surfaces instructions normally, so it is deliberately excluded.
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

// Coding agents and LLM-driven clients that render text rather than MCP Apps UI.
// Matched by `isCliModeEnabled()`, which gates dropping `structuredContent` when a
// `formatted_results` override is set. Mode selection does NOT read this list — CLI
// (single-exec) is the default for every client; `TOOLS_MODE_CLIENT_NAME_FRAGMENTS`
// is the tools-mode allow-list.
export const CODING_AGENT_CLIENT_NAME_FRAGMENTS = [
    'claude-code',
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

// Clients that keep the full per-tool roster ("tools" mode) instead of the
// single-exec CLI default.
// - Cursor self-reports `clientInfo.name`; it sends `content[].text` to the
//   model and renders `structuredContent` in its UI, so the full roster serves
//   it better than the exec wrapper.
// - ChatGPT connects through OpenAI's shared `openai-mcp` client whose
//   `clientInfo.name` is generic; the surface only shows up in the User-Agent
//   parenthetical (`openai-mcp/1.0.0 (ChatGPT)`), hence the user-agent fragment
//   list. Other openai-mcp surfaces (Codex, Agent Builder, Responses API) stay
//   on the CLI default.
export const TOOLS_MODE_CLIENT_NAME_FRAGMENTS = ['cursor', 'chatgpt'] as const
export const TOOLS_MODE_USER_AGENT_FRAGMENTS = ['chatgpt'] as const

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
// PostHog Code UI. Slack-launched runs send `"slack"` and posthog_ai (Max) runs
// send `"posthog_ai"`; only PostHog Code renders MCP UI apps, so this is the
// sole consumer that gates UI-apps payload emission in single-exec mode.
export const POSTHOG_CODE_CONSUMER = 'posthog-code'

// Claude web/desktop and Cowork are MCP Apps hosts that render interactive UI
// (iframes), so the `render-ui` tool is meaningful for them. They send
// `x-anthropic-client: ClaudeAI` / `Cowork` (vs `ClaudeCode` for Claude Code) and
// `User-Agent: Claude-User`. The vendor client is authoritative when present:
// Claude Code is excluded even though it may share the `Claude-User` user-agent.
// The user-agent is a fallback solely for requests that omit the vendor header.
// We deliberately do NOT match `clientName` here — Anthropic pools transports, so
// Claude Code's `clientInfo.name` is also `Anthropic/ClaudeAI`, and matching it
// would misclassify Claude Code as a UI host.
export const ANTHROPIC_UI_HOST_VENDOR_FRAGMENTS = ['claudeai', 'cowork'] as const

// Claude web/desktop report `supportsInstructions` but never surface the
// `instructions` payload to the model, so their env-context rides on the exec
// command description instead (`keepEnvContext`). Cowork surfaces instructions
// normally and gets env-context through them, so it is not a chat host even
// though it is a UI host.
export const ANTHROPIC_CHAT_HOST_VENDOR_FRAGMENTS = ['claudeai'] as const

// Anthropic coding-agent surfaces that render MCP UI apps inline through the
// single-exec `exec` tool. `ClaudeCode` and `Cowork` render UI apps on the exec
// response itself (`ClaudeAI` uses the separate `render-ui` tool instead;
// `Cowork` supports both), so they get the same treatment as the PostHog Code
// consumer.
export const INLINE_EXEC_UI_APP_VENDOR_FRAGMENTS = ['claudecode', 'cowork'] as const

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

    isToolsModeClient(): boolean {
        // The only clients that auto-select the full per-tool roster; everyone
        // else defaults to CLI (single-exec) mode — see `resolveMode`. Matched on
        // the self-reported `clientInfo.name` and the User-Agent (ChatGPT's
        // surface only appears in the UA parenthetical); never on the vendor
        // header, so Anthropic pooled transports can't land in tools mode.
        return (
            matchesAnyFragment(this.clientName, TOOLS_MODE_CLIENT_NAME_FRAGMENTS) ||
            matchesAnyFragment(this.userAgent, TOOLS_MODE_USER_AGENT_FRAGMENTS)
        )
    }

    isCliModeEnabled(): boolean {
        // Gates dropping `structuredContent` when a `formatted_results` override
        // is set — these clients read `content[].text`, so the structured copy
        // would only bloat the payload. Every Anthropic product qualifies.
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

    isClaudeUiHost(): boolean {
        // The per-request vendor client (`x-anthropic-client`) is authoritative: it
        // distinguishes the Claude surfaces that pool the same MCP transport —
        // `ClaudeAI` (web/desktop) and `Cowork`, both `render-ui` hosts, from
        // `ClaudeCode`, which only renders UI apps inline on the `exec` response
        // (see `isInlineExecUiHost`). When it's present, trust it exclusively; only
        // fall back to the `Claude-User` user-agent when the vendor header is
        // absent. Otherwise a non-render-ui surface like Claude Code — which can
        // share the `Claude-User` user-agent with web/desktop — would be
        // misclassified as a UI host.
        if (this.vendorClient) {
            return matchesAnyFragment(this.vendorClient, ANTHROPIC_UI_HOST_VENDOR_FRAGMENTS)
        }
        return matchesAnyFragment(this.userAgent, ANTHROPIC_UI_HOST_USER_AGENT_FRAGMENTS)
    }

    isInlineExecUiHost(): boolean {
        // Anthropic coding-agent surfaces that render MCP UI apps inline through the
        // single-exec `exec` tool (Claude Code, Cowork) — Claude.ai web/desktop
        // renders via the separate `render-ui` tool instead (Cowork supports both).
        // Like PostHog Code, these hosts surface `structuredContent` to the model, so
        // the exec UI-app branch suppresses it and re-homes the app data onto `_meta`.
        // The per-request vendor header (`ClaudeCode` / `Cowork`) is the reliable signal.
        return matchesAnyFragment(this.vendorClient, INLINE_EXEC_UI_APP_VENDOR_FRAGMENTS)
    }

    isClaudeChatHost(): boolean {
        // Same vendor-authoritative shape as `isClaudeUiHost`, narrowed to the chat
        // surfaces (Claude web/desktop) that ignore the `instructions` payload. The
        // `Claude-User` user-agent fallback is kept for requests without the vendor
        // header — those are predominantly chat sessions, and keeping env-context
        // for a misattributed surface only costs payload size, not correctness.
        if (this.vendorClient) {
            return matchesAnyFragment(this.vendorClient, ANTHROPIC_CHAT_HOST_VENDOR_FRAGMENTS)
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

export function isToolsModeClient(clientName: string | undefined, userAgent?: string | undefined): boolean {
    return new MCPClientProfile({ clientName, userAgent }).isToolsModeClient()
}

export function isClaudeUiHostClient(args: {
    vendorClient?: string | undefined
    userAgent?: string | undefined
}): boolean {
    return new MCPClientProfile(args).isClaudeUiHost()
}
