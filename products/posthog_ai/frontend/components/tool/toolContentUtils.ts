import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

/** Compact single-line preview length for a generic MCP tool's input JSON. */
export const INPUT_PREVIEW_MAX_LENGTH = 60
/** Max characters of a Bash command rendered inline before truncation. */
export const MAX_COMMAND_LENGTH = 120
/** Max characters of a fetched URL rendered inline before truncation. */
export const MAX_URL_LENGTH = 60

export interface ToolCallStatusFlags {
    isLoading: boolean
    isFailed: boolean
    wasCancelled: boolean
    isComplete: boolean
}

/**
 * Resolves the four visual states a tool card can be in from its wire status plus the turn-level
 * signals. A tool left `pending`/`in_progress` is *loading* while the turn is live, but *cancelled*
 * once the turn was cancelled, and simply idle once the turn completed without it finishing. Pure —
 * not a hook despite reading like one, so it is safe to call conditionally.
 */
export function resolveToolCallStatus(
    status: ToolCallMessage['status'],
    turnCancelled: boolean,
    turnComplete: boolean
): ToolCallStatusFlags {
    const incomplete = status === 'pending' || status === 'in_progress'
    return {
        isLoading: incomplete && !turnCancelled && !turnComplete,
        wasCancelled: incomplete && turnCancelled,
        isFailed: status === 'failed',
        isComplete: status === 'completed',
    }
}

/** Unwraps the ACP `{ type: 'content', content: {...} }` envelope; flat blocks pass through. */
function unwrapBlock(block: unknown): unknown {
    if (!block || typeof block !== 'object') {
        return block
    }
    if ((block as { type?: unknown }).type === 'content' && 'content' in block) {
        return (block as { content: unknown }).content
    }
    return block
}

/** Text of every text content block (ACP-nested or flat), in order. */
export function getAllText(content: unknown[]): string[] {
    const texts: string[] = []
    for (const block of content) {
        const inner = unwrapBlock(block)
        if (inner && typeof inner === 'object' && (inner as { type?: unknown }).type === 'text') {
            const text = (inner as { text?: unknown }).text
            if (typeof text === 'string') {
                texts.push(text)
            }
        }
    }
    return texts
}

/** Text of the first text content block (ACP-nested or flat), or '' when none carries text. */
export function getContentText(content: unknown[]): string {
    return getAllText(content)[0] ?? ''
}

/**
 * Output of a Bash-style command. The agent prepends the executed command as its own content block
 * (or a `command\n…` prefix), so drop a leading line that echoes the command — leaving just stdout.
 * Falls back to a string `rawOutput` when the command produced no content blocks.
 */
export function getCommandOutput(content: unknown[], command: string, rawOutput: unknown): string {
    const blocks = getAllText(content)
    const cmd = command.trim()
    const trimmed = cmd && blocks[0]?.trim() === cmd ? blocks.slice(1) : blocks
    let output = trimmed.join('\n')
    if (cmd && output.trimStart().startsWith(cmd)) {
        output = output.trimStart().slice(cmd.length).replace(/^\n+/, '')
    }
    if (!output.trim() && typeof rawOutput === 'string') {
        output = rawOutput
    }
    return output
}

export interface ToolImageContent {
    base64: string
    mimeType: string
}

/** First image content block decoded to its base64 + mime type, or null when none is present. */
export function getContentImage(content: unknown[]): ToolImageContent | null {
    for (const block of content) {
        const inner = unwrapBlock(block)
        if (inner && typeof inner === 'object' && (inner as { type?: unknown }).type === 'image') {
            const { data, mimeType } = inner as { data?: unknown; mimeType?: unknown }
            if (typeof data === 'string' && typeof mimeType === 'string') {
                return { base64: data, mimeType }
            }
        }
    }
    return null
}

export interface ToolResourceLink {
    uri: string
    name?: string
    description?: string
}

/** First `resource_link` content block (a fetched/linked resource), or null. */
export function findResourceLink(content: unknown[]): ToolResourceLink | null {
    for (const block of content) {
        const inner = unwrapBlock(block)
        if (inner && typeof inner === 'object' && (inner as { type?: unknown }).type === 'resource_link') {
            const { uri, name, description } = inner as { uri?: unknown; name?: unknown; description?: unknown }
            if (typeof uri === 'string') {
                return {
                    uri,
                    name: typeof name === 'string' ? name : undefined,
                    description: typeof description === 'string' ? description : undefined,
                }
            }
        }
    }
    return null
}

/** Strips a leading ```lang fence and a trailing ``` fence from a fenced code block. */
export function stripCodeFences(text: string): string {
    return text
        .trim()
        .replace(/^```[^\n]*\n?/, '')
        .replace(/\n?```$/, '')
        .trim()
}

// eslint-disable-next-line no-control-regex
const ANSI_ESCAPE_RE = /\x1b\[[0-9;]*m/g

/** Removes ANSI SGR colour codes from terminal output so it reads cleanly in a card. */
export function stripAnsi(text: string): string {
    return text.replace(ANSI_ESCAPE_RE, '')
}

const SYSTEM_REMINDER_RE = /<system-reminder>[\s\S]*?<\/system-reminder>/g
// `cat -n`-style gutter the Read tool prepends to each line: optional indent, line number, then either a
// U+2192 arrow (`NNN→`) or a tab (`NNN⇥`). Anchored per line so only the leading marker is stripped.
const READ_LINE_MARKER_RE = /^\s*\d+[→\t]/gm

/**
 * Cleans the Read tool's output for display: drops injected `<system-reminder>` blocks, the code
 * fences the agent wraps file contents in, and the per-line line-number gutter (`NNN→` or tab form) —
 * leaving the raw file text.
 */
export function getReadToolContent(content: unknown[]): string {
    return stripCodeFences(getContentText(content).replace(SYSTEM_REMINDER_RE, ''))
        .replace(READ_LINE_MARKER_RE, '')
        .trim()
}

/** Basename of a path (everything after the last slash). */
export function getFilename(path: string): string {
    const segments = path.split('/')
    return segments[segments.length - 1] || path
}

/** Number of lines in a block of text; empty/whitespace-only text counts as zero. */
export function getLineCount(text: string): number {
    if (!text.trim()) {
        return 0
    }
    return text.split('\n').length
}

/** Number of non-empty lines — the search-result count for Grep/Glob/LS output. */
export function getResultCount(text: string): number {
    return text.split('\n').filter((line) => line.trim().length > 0).length
}

/** Truncates `text` to `max` characters, appending an ellipsis when it overflows. */
export function truncateText(text: string, max: number, suffix = '…'): string {
    if (text.length <= max) {
        return text
    }
    return text.slice(0, max) + suffix
}

/** Pretty-prints a tool input object as indented JSON for the expanded body. */
export function formatInput(input: unknown): string {
    try {
        return JSON.stringify(input, null, 2)
    } catch {
        return String(input)
    }
}

/** Single-line, truncated JSON preview of a tool input — the generic MCP card's header hint. */
export function compactInput(input: unknown, max = INPUT_PREVIEW_MAX_LENGTH): string {
    try {
        return truncateText(JSON.stringify(input) ?? '', max)
    } catch {
        return ''
    }
}
