/**
 * Shared display helpers for the PostHog single-exec MCP tool. The `posthog` MCP server exposes one
 * outer `exec` tool whose `command` string carries the real intent (`tools` / `search` / `info` /
 * `schema` / `call <sub-tool>`). Both the thread tool-card renderer and the permission card need the
 * same human-friendly label + input preview, so the parsing lives here — one source of truth.
 */

/** Matches the PostHog single-exec MCP tool (`mcp__posthog__exec`, plus plugin/regional variants). */
export const POSTHOG_EXEC_TOOL_RE = /^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$/

export function isPostHogExecTool(toolName: string): boolean {
    return POSTHOG_EXEC_TOOL_RE.test(toolName)
}

/** The verbs the single-exec tool accepts. `call` runs a sub-tool; the rest are read-only. */
export type PostHogExecVerb = 'tools' | 'search' | 'info' | 'schema' | 'call'
const POSTHOG_EXEC_VERBS = new Set<PostHogExecVerb>(['tools', 'search', 'info', 'schema', 'call'])

/**
 * Splits the leading whitespace-delimited token off a command and returns it plus the trimmed
 * remainder. Mirrors the backend exec `parseCommand` (`services/mcp/src/tools/exec.ts`)
 * token-for-token — single-space split, trimmed remainder — so the client tokenizes a command
 * exactly the way the server that runs it does. This is a security boundary: any divergence lets a
 * crafted command resolve to a different (safer-looking) inner tool here than the backend executes.
 */
export function splitFirstToken(input: string): { head: string; rest: string } {
    const trimmed = input.trim()
    const idx = trimmed.indexOf(' ')
    if (idx === -1) {
        return { head: trimmed, rest: '' }
    }
    return { head: trimmed.slice(0, idx), rest: trimmed.slice(idx + 1).trim() }
}

/**
 * Parses an exec `command` into its verb and remainder. `verb` is null when the leading token isn't
 * a recognized verb (the backend rejects such a command as `Unknown command`).
 */
export function parseExecCommand(command: string): { verb: PostHogExecVerb | null; rest: string } {
    const { head, rest } = splitFirstToken(command)
    return POSTHOG_EXEC_VERBS.has(head as PostHogExecVerb)
        ? { verb: head as PostHogExecVerb, rest }
        : { verb: null, rest }
}

/**
 * Parses the body of a `call` command (everything after the `call` verb) into its inner sub-tool,
 * its remaining args, and the boolean flags. Strips leading `--json` / `--confirm` flags in any
 * order, mirroring the backend `parseCallFlags`, then takes the next token as the sub-tool.
 * `subTool` is null when no sub-tool remains, or when the next token still looks like a flag — a real
 * sub-tool name never starts with `-`. The permission gate keys destructive-tool detection off
 * `subTool`, so this MUST match the server's flag grammar: what the server strips, we strip; what it
 * can't resolve, we fail closed on.
 */
export function parseExecCall(callBody: string): {
    subTool: string | null
    args: string
    forceJson: boolean
    confirmed: boolean
} {
    let rest = callBody.trim()
    let forceJson = false
    let confirmed = false
    while (rest) {
        const { head, rest: next } = splitFirstToken(rest)
        if (head === '--json') {
            forceJson = true
            rest = next
            continue
        }
        if (head === '--confirm') {
            confirmed = true
            rest = next
            continue
        }
        break
    }
    const { head: subTool, rest: args } = splitFirstToken(rest)
    if (!subTool || subTool.startsWith('-')) {
        return { subTool: null, args, forceJson, confirmed }
    }
    return { subTool, args, forceJson, confirmed }
}

export interface PostHogExecDisplay {
    label: string
    input?: string
}

function readExplicitInput(value: unknown): string | undefined {
    if (value === undefined || value === null) {
        return undefined
    }
    if (typeof value === 'string') {
        return value.trim() || undefined
    }
    try {
        return JSON.stringify(value)
    } catch {
        return undefined
    }
}

/**
 * Unwraps an `exec` invocation's `command` (and optional explicit `input`) into a friendly label and
 * input preview. Returns null when the payload isn't a recognizable `exec` command, so callers can
 * fall back to generic rendering.
 */
export function getPostHogExecDisplay(toolInput: unknown): PostHogExecDisplay | null {
    if (!toolInput || typeof toolInput !== 'object') {
        return null
    }
    const obj = toolInput as { command?: unknown; input?: unknown }
    if (typeof obj.command !== 'string') {
        return null
    }

    const { verb, rest } = parseExecCommand(obj.command)
    if (!verb) {
        return null
    }
    const explicitInput = readExplicitInput(obj.input)

    switch (verb) {
        case 'tools':
            return { label: 'List tools', input: undefined }
        case 'search':
            return {
                label: 'Search tools',
                input: explicitInput ?? (rest.length > 0 ? rest : undefined),
            }
        case 'info':
            return rest.length > 0
                ? { label: `Read ${rest}`, input: undefined }
                : { label: 'Read tool', input: undefined }
        case 'schema': {
            const { head: subTool, rest: fieldPath } = splitFirstToken(rest)
            if (!subTool) {
                return { label: 'Inspect schema', input: undefined }
            }
            const path = explicitInput ?? (fieldPath.length > 0 ? fieldPath : undefined)
            return {
                label: path ? `Inspect ${subTool}.${path}` : `Inspect ${subTool} fields`,
                input: undefined,
            }
        }
        case 'call': {
            const { subTool, args } = parseExecCall(rest)
            if (!subTool) {
                return null
            }
            return {
                label: subTool,
                input: explicitInput ?? (args.length > 0 ? args : undefined),
            }
        }
    }
}

export function formatPostHogExecBody(input: string | undefined): string | undefined {
    if (!input) {
        return undefined
    }
    try {
        const parsed = JSON.parse(input)
        if (parsed && typeof parsed === 'object') {
            return JSON.stringify(parsed, null, 2)
        }
    } catch {
        // Non-JSON args, such as a search regex, are already displayable.
    }
    return input
}
