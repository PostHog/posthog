import { asRecord } from '@/lib/records'

import { extractAgentToolName, isPostHogExecTool, parseExecVerb, resolveToolCall, splitFirstToken } from './toolPolicy'

const TOOL_TITLE_CHARS = 80

const TOOL_VERBS: Record<string, string> = {
    Read: 'Reading',
    Edit: 'Editing',
    Write: 'Writing',
    Find: 'Finding',
    Fetch: 'Fetching',
    Search: 'Searching',
}

/** The parts of an ACP tool call that say which tool runs and with what input. */
export interface ToolCallSource {
    server: string
    tool: string
    input: Record<string, unknown>
    meta: unknown
}

export interface ToolCallDescription {
    title?: string
    /** The one-sentence intent the PostHog MCP asks the agent for on every call. */
    detail?: string
}

function capTitle(title: string): string {
    return title.length > TOOL_TITLE_CHARS ? `${title.slice(0, TOOL_TITLE_CHARS - 1).trimEnd()}…` : title
}

export function shortenToolTitle(title: string): string {
    const words = title
        .trim()
        .split(/\s+/)
        .map((word) =>
            word.includes('/') && !word.includes('://') ? (word.split('/').filter(Boolean).pop() ?? word) : word
        )
    const first = words[0]
    if (first && TOOL_VERBS[first]) {
        words[0] = TOOL_VERBS[first] as string
    }
    return capTitle(words.join(' '))
}

export function toolCallSource(update: Record<string, unknown>): ToolCallSource {
    return {
        server: String(update.serverName ?? 'posthog'),
        tool: String(update.toolName ?? ''),
        input: asRecord(update.rawInput) ?? asRecord(update.input) ?? {},
        meta: update._meta,
    }
}

/** An update carries only what changed, so the call's tool, input and meta persist from the frame that created it. */
export function mergeToolCallSource(previous: ToolCallSource | undefined, update: ToolCallSource): ToolCallSource {
    if (!previous) {
        return update
    }
    return {
        server: previous.server,
        tool: previous.tool || update.tool,
        input: Object.keys(update.input).length > 0 ? update.input : previous.input,
        meta: update.meta ?? previous.meta,
    }
}

// Matches the web labels in `products/posthog_ai/frontend/components/tool/posthogExecDisplay.ts`.
function postHogExecTitle(resolvedKey: string, innerToolName: string | undefined, command: string): string {
    if (innerToolName) {
        return `Call ${innerToolName}`
    }
    const { rest } = parseExecVerb(command)
    switch (resolvedKey) {
        case '__posthog_exec_tools__':
            return 'List tools'
        case '__posthog_exec_search__':
            return 'Search tools'
        case '__posthog_exec_info__':
            return rest ? `Read ${rest}` : 'Read tool'
        case '__posthog_exec_schema__': {
            const { head: tool, rest: path } = splitFirstToken(rest)
            if (!tool) {
                return 'Inspect schema'
            }
            return path ? `Inspect ${tool}.${path}` : `Inspect ${tool} fields`
        }
        default:
            return 'Run command'
    }
}

function rawToolNames(source: ToolCallSource): string[] {
    return [source.tool, extractAgentToolName(source.meta)].filter((name): name is string => !!name)
}

/** A row title for a tool call. A PostHog `exec` call is named after its command, never after the ACP title. */
export function describeToolCall(source: ToolCallSource, acpTitle?: string): ToolCallDescription {
    const { resolvedKey, innerToolName } = resolveToolCall({
        toolCallId: '',
        rawServerName: source.server,
        rawToolName: source.tool,
        input: source.input,
        meta: source.meta,
    })
    // A PostHog call whose input has not streamed yet resolves to the bare exec tool; it reads as "Run command" until then.
    if (innerToolName !== undefined || resolvedKey.startsWith('__posthog_exec_') || isPostHogExecTool(resolvedKey)) {
        const command = typeof source.input.command === 'string' ? source.input.command : ''
        const context = typeof source.input.context === 'string' ? source.input.context.trim() : ''
        return {
            title: capTitle(postHogExecTitle(resolvedKey, innerToolName, command)),
            ...(context ? { detail: context } : {}),
        }
    }
    const title = acpTitle?.trim()
    if (!title) {
        return {}
    }
    // Some harnesses send the bare tool name as the title (`exec` for `exec`). It says nothing, so the row shows the tool name.
    const lowered = title.toLowerCase()
    if (rawToolNames(source).some((name) => name.toLowerCase() === lowered)) {
        return {}
    }
    return { title: shortenToolTitle(title) }
}
