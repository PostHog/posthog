import {
    parseRetryAfterSeconds,
    PostHogApiError,
    PostHogPermissionError,
    PostHogRateLimitError,
    PostHogValidationError,
} from '@/lib/errors'
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

    const method = 'POST'
    const url = `${context.api.baseUrl}/api/environments/${projectId}/mcp_tools/${toolName}/`

    const response = await fetch(url, {
        method,
        headers: {
            Authorization: `Bearer ${context.api.config.apiToken}`,
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ args }),
    })

    if (!response.ok) {
        // Surface the typed errors the main ApiClient throws so error
        // classification can tell a rate limit apart from a server fault.
        throw await buildInvokeError(response, method, url)
    }

    return response.json() as Promise<McpToolResult>
}

async function buildInvokeError(response: Response, method: string, url: string): Promise<Error> {
    const body = await response.text()

    if (response.status === 429) {
        return new PostHogRateLimitError({
            body,
            url,
            method,
            retryAfterSeconds: parseRetryAfterSeconds(response.headers.get('Retry-After')),
        })
    }

    let errorData: any
    try {
        errorData = JSON.parse(body)
    } catch {
        errorData = { detail: body }
    }

    if (response.status === 403 && errorData?.code === 'permission_denied') {
        const scopeMatch = /required scope ['"]([^'"]+)['"]/.exec(errorData.detail || '')
        return new PostHogPermissionError({
            detail: errorData.detail || 'permission denied',
            missingScope: scopeMatch?.[1],
            url,
            method,
        })
    }

    if (errorData?.type === 'validation_error') {
        return new PostHogValidationError({
            detail: errorData.detail || errorData.code || 'unknown',
            attr: errorData.attr ?? undefined,
            code: errorData.code ?? undefined,
            extra: (errorData.extra ?? undefined) as Record<string, unknown> | undefined,
            url,
            method,
        })
    }

    return new PostHogApiError({
        status: response.status,
        statusText: response.statusText,
        body,
        url,
        method,
    })
}
