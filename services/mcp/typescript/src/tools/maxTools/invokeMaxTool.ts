import type { Context } from '@/tools/types'

export interface MaxToolResult {
    success: boolean
    content: string
    data?: Record<string, any> | null
    error?: string | null
}

/**
 * Invoke a Max AI tool via the PostHog API.
 *
 * @param context - The MCP context containing API client and state
 * @param toolName - Name of the Max tool to invoke (e.g., 'execute_sql')
 * @param args - Arguments to pass to the tool
 * @returns The tool result
 */
export async function invokeMaxTool(
    context: Context,
    toolName: string,
    args: Record<string, any>
): Promise<MaxToolResult> {
    const projectId = await context.stateManager.getProjectId()

    const url = `${context.api.baseUrl}/api/environments/${projectId}/max_tools/invoke/${toolName}/`

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
            errorMessage = errorData.content || errorData.error || errorText
        } catch {
            errorMessage = errorText
        }
        return {
            success: false,
            content: `Failed to invoke Max tool '${toolName}': ${errorMessage}`,
            error: 'api_error',
        }
    }

    return response.json() as Promise<MaxToolResult>
}
