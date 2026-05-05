export const MCP_CONTEXT_FIELD = '_mcp_context'
export const MCP_CONTEXT_MAX_LENGTH = 2_000
export const MCP_CONTEXT_DESCRIPTION =
    "Optional: briefly explain why you're calling this tool and how it helps the user's current task. Do not include secrets, credentials, or raw customer data."

export function extractMcpContext(params: unknown): string | undefined {
    if (!params || typeof params !== 'object') {
        return undefined
    }

    const value = (params as Record<string, unknown>)[MCP_CONTEXT_FIELD]
    return typeof value === 'string' ? value.slice(0, MCP_CONTEXT_MAX_LENGTH) : undefined
}

export function stripMcpContext(params: unknown): Record<string, unknown> {
    if (!params || typeof params !== 'object') {
        return {}
    }

    const { [MCP_CONTEXT_FIELD]: _mcpContext, ...cleanedParams } = params as Record<string, unknown>
    return cleanedParams
}
