import type { Context } from '@/tools/types'

export interface McpToolResult {
    success: boolean
    content: string
}

/**
 * Invoke an MCP tool via the PostHog API.
 *
 * Goes through `context.api.request` rather than calling `fetch` directly. That is the seam a
 * re-routed client overrides (see lib/connection-forwarding.ts), so a tool built on this reaches
 * whichever project its context points at without the caller's bearer token ever going anywhere the
 * client did not build itself. It also picks up the shared 429 retry policy and the typed error
 * mapping (`PostHogRateLimitError`, `PostHogPermissionError`, `PostHogValidationError`) that error
 * classification reads.
 *
 * @param context - The MCP context containing API client and state
 * @param toolName - Name of the MCP tool to invoke (e.g., 'execute_sql')
 * @param args - Arguments to pass to the tool
 * @returns The tool result with success status and content
 */
export async function invokeMcpTool(
    context: Context,
    toolName: string,
    args: Record<string, any>
): Promise<McpToolResult> {
    const projectId = await context.stateManager.getProjectId()

    return await context.api.request<McpToolResult>({
        method: 'POST',
        path: `/api/environments/${projectId}/mcp_tools/${toolName}/`,
        body: { args },
    })
}
