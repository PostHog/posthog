import { parseExecCall, parseExecCommand, POSTHOG_EXEC_TOOL_RE } from './posthogExecDisplay'

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

/**
 * Resolves the registry key for a tool call. The single-exec `posthog` MCP server exposes one
 * outer `exec` tool; the inner tool name is parsed out of `rawInput.command`. Non-exec MCP tools
 * and Claude built-ins look up by their wire name directly. Claude built-ins carry no wire
 * `toolName`, so `claudeToolName` (from `_meta.claudeCode.toolName`) is preferred as the fallback.
 */
export function resolveToolKey(
    serverName: string,
    toolName: string,
    input: Record<string, unknown>,
    claudeToolName?: string
): ResolvedToolKey {
    const fullName = `mcp__${serverName}__${toolName}`
    const isPostHogExecTool =
        POSTHOG_EXEC_TOOL_RE.test(fullName) ||
        POSTHOG_EXEC_TOOL_RE.test(toolName) ||
        (claudeToolName ? POSTHOG_EXEC_TOOL_RE.test(claudeToolName) : false)

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
                // Leave malformed payloads renderable as generic tool calls.
            }
        }
        return { resolvedKey: subTool, innerToolName: subTool, innerInput }
    }

    return { resolvedKey: toolName || claudeToolName || '' }
}

/** Resolves renderer-facing fields from a raw streamed tool invocation. */
export function resolveToolCall(toolCall: ResolvableToolCall): ResolvedToolCall {
    const claudeToolName = extractClaudeToolName(toolCall.meta)
    return {
        ...resolveToolKey(toolCall.rawServerName, toolCall.rawToolName, toolCall.input, claudeToolName),
        claudeToolName,
    }
}
