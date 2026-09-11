import { parseExecCall, parseExecCommand, POSTHOG_EXEC_TOOL_RE } from '../components/tool/posthogExecDisplay'
import type { PermissionRequestRecord } from '../types/streamTypes'

export interface ResolvedToolKey {
    resolvedKey: string
    innerToolName?: string
    innerInput?: Record<string, unknown>
}

export interface ResolvableToolCall {
    rawServerName: string
    rawToolName: string
    input: Record<string, unknown>
    meta?: unknown
}

export interface ResolvedToolCall extends ResolvedToolKey {
    claudeToolName?: string
}

/** Reads `_meta.claudeCode` off a tool frame's `_meta` without trusting its shape. */
export function getClaudeCodeMeta(meta: unknown): Record<string, unknown> | undefined {
    if (typeof meta !== 'object' || meta === null) {
        return undefined
    }
    const claudeCode = (meta as { claudeCode?: unknown }).claudeCode
    return typeof claudeCode === 'object' && claudeCode !== null ? (claudeCode as Record<string, unknown>) : undefined
}

/** Stable SDK tool name (`"Edit"`, `"TodoWrite"`) from `_meta.claudeCode.toolName`; undefined when absent. */
export function extractClaudeToolName(meta: unknown): string | undefined {
    const claudeCode = getClaudeCodeMeta(meta)
    return typeof claudeCode?.toolName === 'string' && claudeCode.toolName ? claudeCode.toolName : undefined
}

export function extractAgentToolName(meta: unknown): string | undefined {
    const posthog = typeof meta === 'object' && meta !== null ? (meta as { posthog?: unknown }).posthog : undefined
    if (typeof posthog === 'object' && posthog !== null) {
        const { toolName, mcp } = posthog as { toolName?: unknown; mcp?: unknown }
        if (typeof mcp === 'object' && mcp !== null) {
            const { server, tool } = mcp as { server?: unknown; tool?: unknown }
            if (typeof server === 'string' && server && typeof tool === 'string' && tool) {
                return `mcp__${server}__${tool}`
            }
        }
        if (typeof toolName === 'string' && toolName) {
            return toolName
        }
    }
    return extractClaudeToolName(meta)
}

/**
 * Resolves the registry key for a tool call. The single-exec `posthog` MCP server exposes one
 * outer `exec` tool; the inner tool name is parsed out of `rawInput.command`. Non-exec MCP tools
 * and built-ins look up by their wire name directly. Adapters can omit the wire `toolName`,
 * so the canonical name from adapter metadata is the fallback.
 */
export function resolveToolKey(
    serverName: string,
    toolName: string,
    input: Record<string, unknown>,
    agentToolName?: string
): ResolvedToolKey {
    const fullName = `mcp__${serverName}__${toolName}`
    const isPostHogExecTool =
        POSTHOG_EXEC_TOOL_RE.test(fullName) ||
        POSTHOG_EXEC_TOOL_RE.test(toolName) ||
        (agentToolName ? POSTHOG_EXEC_TOOL_RE.test(agentToolName) : false)

    if (isPostHogExecTool && typeof input.command === 'string') {
        const { verb, rest } = parseExecCommand(input.command)
        if (!verb) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }

        if (verb !== 'call') {
            return { resolvedKey: `__posthog_exec_${verb}__` }
        }

        // Resolve the inner sub-tool the same way the backend does (flags in any order). When it
        // can't be resolved, fall back to the unknown sentinel so the permission gate fails closed
        // instead of treating an unparsed `call` as a non-destructive tool.
        const { subTool, args } = parseExecCall(rest)
        if (!subTool) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }

        let innerInput: Record<string, unknown> = {}
        if (args) {
            try {
                innerInput = JSON.parse(args)
            } catch {
                return { resolvedKey: subTool, innerToolName: subTool }
            }
        }
        return { resolvedKey: subTool, innerToolName: subTool, innerInput }
    }

    return { resolvedKey: toolName || agentToolName || '' }
}

/** Resolves renderer-facing fields from a raw streamed tool invocation. */
export function resolveToolCall(toolCall: ResolvableToolCall): ResolvedToolCall {
    const claudeToolName = extractClaudeToolName(toolCall.meta)
    const agentToolName = extractAgentToolName(toolCall.meta)
    const mcp = agentToolName?.match(/^mcp__(.+?)__(.+)$/)
    return {
        ...resolveToolKey(
            mcp?.[1] ?? toolCall.rawServerName,
            mcp?.[0] ?? toolCall.rawToolName,
            toolCall.input,
            agentToolName
        ),
        claudeToolName,
    }
}

/**
 * The proposed inner tool input for a permission request — the args a tool renderer or a
 * `PermissionPreview` needs to preview what an approval will do. For a PostHog exec call this is
 * the command-embedded JSON args (`call <sub-tool> {…}`), falling back to the explicit `input` field
 * when the agent sends args out of band. Returns an empty object when neither is present.
 */
export function getPermissionRequestToolInput(record: PermissionRequestRecord): Record<string, unknown> {
    const resolved = resolveToolCall(record.rawToolCall)
    if (resolved.innerInput && Object.keys(resolved.innerInput).length > 0) {
        return resolved.innerInput
    }
    const explicit = (record.rawToolCall.input as { input?: unknown }).input
    return explicit && typeof explicit === 'object' && !Array.isArray(explicit)
        ? (explicit as Record<string, unknown>)
        : {}
}
