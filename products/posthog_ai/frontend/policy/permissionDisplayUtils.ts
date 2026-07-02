import {
    POSTHOG_EXEC_TOOL_RE,
    formatPostHogExecBody,
    getPostHogExecDisplay,
} from '../components/tool/posthogExecDisplay'
import { resolveToolCall } from '../components/tool/toolResolver'
import type { PermissionRequestRecord } from '../types/streamTypes'

// Re-exported so existing importers (and tests) keep resolving the exec display from here.
export { getPostHogExecDisplay } from '../components/tool/posthogExecDisplay'

export interface PermissionDisplay {
    title?: string
    payload?: string
}

function parseMcpToolKey(toolName: string): { serverName: string; toolName: string } | null {
    const parts = toolName.split('__')
    if (parts.length < 3 || parts[0] !== 'mcp') {
        return null
    }
    return {
        serverName: parts[1],
        toolName: parts.slice(2).join('__'),
    }
}

function formatInput(rawInput: unknown): string | undefined {
    if (!rawInput || typeof rawInput !== 'object') {
        return undefined
    }
    try {
        const json = JSON.stringify(rawInput, null, 2)
        return json === '{}' ? undefined : json
    } catch {
        return undefined
    }
}

export function getPermissionDisplay(request: PermissionRequestRecord): PermissionDisplay {
    const mcpTool = parseMcpToolKey(request.toolName)
    if (!mcpTool) {
        return {
            title: request.title ?? request.rawToolCall.title ?? request.toolName,
            payload: formatInput(request.rawToolCall.input),
        }
    }

    if (POSTHOG_EXEC_TOOL_RE.test(request.toolName)) {
        const posthogDisplay = getPostHogExecDisplay(request.rawToolCall.input)
        if (posthogDisplay) {
            return {
                title: `posthog - ${posthogDisplay.label} (MCP)`,
                payload: formatPostHogExecBody(posthogDisplay.input),
            }
        }
        const resolved = resolveToolCall(request.rawToolCall)
        const resolvedName =
            resolved.innerToolName ??
            (resolved.resolvedKey.startsWith('__posthog_exec_') ? undefined : resolved.resolvedKey)
        if (resolvedName) {
            return {
                title: `posthog - ${resolvedName} (MCP)`,
                payload: formatInput(resolved.innerInput ?? request.rawToolCall.input),
            }
        }
    }

    return {
        title: `${mcpTool.serverName} - ${mcpTool.toolName} (MCP)`,
        payload: formatInput(request.rawToolCall.input),
    }
}
