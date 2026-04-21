/**
 * Coding-agent MCP clients that surface `structuredContent` directly to the model
 * (in preference to `content[].text`). When we supply a `formattedResults` override
 * in `text`, we must drop `structuredContent` for these clients — otherwise the
 * raw JSON gets sent to the model instead of the formatted table.
 *
 * Match by lowercased substring to tolerate client-name variants
 * (e.g. "claude-code-cli", "cline-bot").
 */
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

/**
 * Lowercases and strips separators (`-`, `_`, whitespace) so that variants like
 * "claude-code", "claude code", and "Claude_Code" all reduce to "claudecode".
 */
function normalizeClientName(s: string): string {
    return s.toLowerCase().replace(/[-_\s]+/g, '')
}

export function isCodingAgentClient(clientName: string | undefined): boolean {
    if (!clientName) {
        return false
    }
    const normalized = normalizeClientName(clientName)
    if (!normalized) {
        return false
    }
    return CODING_AGENT_CLIENT_NAME_FRAGMENTS.some((fragment) => normalized.includes(normalizeClientName(fragment)))
}
