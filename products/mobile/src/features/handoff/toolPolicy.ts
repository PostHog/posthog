import { asRecord } from '@/lib/records'

import type { PermissionRecord, PermissionToolCall } from './types'

// An interactive run waits for the client to answer each approval, so a client that never answers stalls the agent.

export type PermissionDecision = 'auto_allow' | 'prompt'

const POSTHOG_EXEC_TOOL_RE = /^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$/

const POSTHOG_EXEC_VERBS = new Set(['tools', 'search', 'info', 'schema', 'call'])

const CONNECTED_PROJECT_SUB_TOOLS = new Set(['posthog-connection-call', 'posthog-connection-forward'])

export function isPostHogExecTool(toolName: string): boolean {
    return POSTHOG_EXEC_TOOL_RE.test(toolName)
}

// Mirrors the backend exec `parseCommand` (`services/mcp/src/tools/exec.ts`) token for token. Security: a divergence
// lets a crafted command resolve here to a safer-looking inner tool than the one the server runs.
export function splitFirstToken(input: string): { head: string; rest: string } {
    const trimmed = input.trim()
    const index = trimmed.indexOf(' ')
    if (index === -1) {
        return { head: trimmed, rest: '' }
    }
    return { head: trimmed.slice(0, index), rest: trimmed.slice(index + 1).trim() }
}

export function parseExecVerb(command: string): { verb: string | null; rest: string } {
    const { head, rest } = splitFirstToken(command)
    return POSTHOG_EXEC_VERBS.has(head) ? { verb: head, rest } : { verb: null, rest }
}

// Strips leading `--json` and `--confirm` flags in any order, like the backend `parseCallFlags`. A token that still
// starts with `-` is not a sub-tool, so the gate fails closed on it.
function parseExecSubTool(callBody: string): string | null {
    let rest = callBody.trim()
    while (rest) {
        const { head, rest: next } = splitFirstToken(rest)
        if (head !== '--json' && head !== '--confirm') {
            break
        }
        rest = next
    }
    const { head } = splitFirstToken(rest)
    return head && !head.startsWith('-') ? head : null
}

function extractClaudeToolName(meta: unknown): string | undefined {
    const toolName = asRecord(asRecord(meta)?.claudeCode)?.toolName
    return typeof toolName === 'string' && toolName ? toolName : undefined
}

export function extractAgentToolName(meta: unknown): string | undefined {
    const posthog = asRecord(asRecord(meta)?.posthog)
    if (posthog) {
        const mcp = asRecord(posthog.mcp)
        if (mcp && typeof mcp.server === 'string' && mcp.server && typeof mcp.tool === 'string' && mcp.tool) {
            return `mcp__${mcp.server}__${mcp.tool}`
        }
        if (typeof posthog.toolName === 'string' && posthog.toolName) {
            return posthog.toolName
        }
    }
    return extractClaudeToolName(meta)
}

export interface ResolvedToolCall {
    resolvedKey: string
    innerToolName?: string
}

// The PostHog MCP server exposes one `exec` tool, so the inner tool comes from `input.command`. An unparsable `call`
// resolves to the unknown sentinel so the gate fails closed instead of treating it as harmless.
export function resolveToolCall(toolCall: PermissionToolCall): ResolvedToolCall {
    const agentToolName =
        extractAgentToolName(toolCall.meta) ??
        (typeof toolCall.input.toolName === 'string' ? toolCall.input.toolName : undefined)
    const mcp = agentToolName?.match(/^mcp__(.+?)__(.+)$/)
    const serverName = mcp?.[1] ?? toolCall.rawServerName
    const toolName = mcp?.[0] ?? toolCall.rawToolName
    const isExec =
        POSTHOG_EXEC_TOOL_RE.test(`mcp__${serverName}__${toolName}`) ||
        POSTHOG_EXEC_TOOL_RE.test(toolName) ||
        (agentToolName ? POSTHOG_EXEC_TOOL_RE.test(agentToolName) : false)
    const command = toolCall.input.command
    if (isExec && typeof command === 'string') {
        const { verb, rest } = parseExecVerb(command)
        if (!verb) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }
        if (verb !== 'call') {
            return { resolvedKey: `__posthog_exec_${verb}__` }
        }
        const subTool = parseExecSubTool(rest)
        if (!subTool) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }
        return { resolvedKey: subTool, innerToolName: subTool }
    }
    return { resolvedKey: toolName || agentToolName || '' }
}

function isConnectedProjectSubTool(subTool: string): boolean {
    return CONNECTED_PROJECT_SUB_TOOLS.has(subTool.toLowerCase())
}

/** A PostHog call into a connected project, which the task did not authorize. */
export function isConnectedProjectTool(record: PermissionRecord): boolean {
    const { innerToolName } = resolveToolCall(record.rawToolCall)
    return innerToolName !== undefined && isConnectedProjectSubTool(innerToolName)
}

// The agent server sends an `ExitPlanMode` approval with no top-level tool name and `kind: 'switch_mode'`, with the
// tool name inside the input; other adapters tag it directly.
export function isPlanPermissionRequest(record: PermissionRecord): boolean {
    return (
        record.toolName === 'ExitPlanMode' ||
        record.rawToolCall.rawToolName === 'ExitPlanMode' ||
        record.rawToolCall.input.toolName === 'ExitPlanMode' ||
        extractAgentToolName(record.rawToolCall.meta) === 'ExitPlanMode' ||
        record.rawToolCall.kind === 'plan'
    )
}

export function isFullAutoMode(mode: string | null | undefined): boolean {
    return mode === 'bypassPermissions'
}

/** Any permission request the server relays still needs a person's answer, regardless of tool name or mode. */
export function defaultPermissionDecision(_record: PermissionRecord): PermissionDecision {
    return 'prompt'
}

export function findAllowOptionId(record: PermissionRecord): string | null {
    const allowOnce = record.options.find((option) => option.kind === 'allow_once')
    if (allowOnce) {
        return allowOnce.optionId
    }
    return record.options.find((option) => option.kind.startsWith('allow'))?.optionId ?? null
}

// A replayed request is never answered automatically because the run may have moved on.
export function routePermissionRequest(
    record: PermissionRecord,
    context: { mode?: string; replayed: boolean }
): { action: 'auto_allow'; optionId: string } | { action: 'prompt' } {
    if (context.replayed) {
        return { action: 'prompt' }
    }
    if (isPlanPermissionRequest(record)) {
        return { action: 'prompt' }
    }
    const decision = defaultPermissionDecision(record)
    if (decision === 'auto_allow') {
        const optionId = findAllowOptionId(record)
        if (optionId) {
            return { action: 'auto_allow', optionId }
        }
    }
    return { action: 'prompt' }
}
