/**
 * MCP client-name detection helpers.
 *
 * `clientInfo.name` is what a client self-reports during the `initialize`
 * handshake. We use substring matching (with separators stripped and case
 * normalized) so variants like "claude-code", "Claude Code", "claude-code-cli",
 * and "claude-code/1.2.3" all resolve to the same form.
 *
 * `isCodingAgentClient` matches coding agents that surface `structuredContent`
 * to the model in preference to `content[].text`. Used to drop
 * `structuredContent` when a `formatted_results` override is set, otherwise
 * Claude Code (and friends) show raw JSON instead of the formatted table.
 * Cursor is deliberately excluded — it reads text for the model and renders
 * `structuredContent` in UI, so it does not need the workaround.
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
] as const

export function isCodingAgentClient(clientName: string | undefined): boolean {
    return matchesAnyFragment(clientName, CODING_AGENT_CLIENT_NAME_FRAGMENTS)
}

// Value sent in `x-posthog-mcp-consumer` by PostHog Code (the Tasks sandbox
// wrapper around the Claude Agent SDK) when the task was launched from the
// PostHog Code UI. Used to force coding-agent behavior and to gate UI-apps
// emission in single-exec mode. Slack-launched runs send `"slack"` instead.
export const POSTHOG_CODE_CONSUMER = 'posthog-code'

export function isPostHogCodeConsumer(mcpConsumer: string | undefined): boolean {
    return mcpConsumer === POSTHOG_CODE_CONSUMER
}
