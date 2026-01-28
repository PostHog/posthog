import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js'

import { getPostHogClient } from '@/integrations/mcp/utils/client'

export class MCPToolError extends Error {
    public readonly tool: string
    public readonly originalError: unknown
    public readonly timestamp: Date

    constructor(message: string, tool: string, originalError?: unknown) {
        super(message)
        this.name = 'MCPToolError'
        this.tool = tool
        this.originalError = originalError
        this.timestamp = new Date()
    }
}

/**
 * Handles tool errors and returns a structured error message.
 * Any errors that originate from the tool SHOULD be reported inside the result
 * object, with `isError` set to true, _not_ as an MCP protocol-level error
 * response. Otherwise, the LLM would not be able to see that an error occurred
 * and self-correct.
 *
 * @param error - The error object.
 * @param tool - Tool that caused the error.
 * @param distinctId - User's distinct ID for tracking.
 * @param sessionId - Session UUID for tracking.
 *
 * @returns A structured error message.
 */
export function handleToolError(error: any, tool?: string, distinctId?: string, sessionUuid?: string): CallToolResult {
    const mcpError =
        error instanceof MCPToolError
            ? error
            : new MCPToolError(error instanceof Error ? error.message : String(error), tool || 'unknown', error)

    const properties: Record<string, any> = {
        team: 'growth',
        tool: mcpError.tool,
        is_mcp_tool_error: error instanceof MCPToolError,
        $exception_fingerprint: mcpError.tool,
    }

    if (sessionUuid) {
        properties.$session_id = sessionUuid
    }

    getPostHogClient().captureException(mcpError, distinctId, properties)

    return {
        content: [
            {
                type: 'text',
                text: `Error: [${mcpError.tool}]: ${mcpError.message}`,
            },
        ],
        isError: true,
    }
}
