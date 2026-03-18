import type { Context } from '@/tools/types'

export interface McpToolResult {
    success: boolean
    content: string
}

/**
 * Invoke an MCP tool via the PostHog API.
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

    const url = `${context.api.baseUrl}/api/environments/${projectId}/mcp_tools/${toolName}/`

    const response = await fetch(url, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${context.api.config.apiToken}`,
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ args }),
    })

    if (!response.ok) {
        const errorText = await response.text()
        let errorMessage: string
        try {
            const errorData = JSON.parse(errorText)
            errorMessage = errorData.content || errorText
        } catch {
            errorMessage = errorText
        }
        return {
            success: false,
            content: `Failed to invoke MCP tool '${toolName}': ${errorMessage}`,
        }
    }

    return response.json() as Promise<McpToolResult>
}
