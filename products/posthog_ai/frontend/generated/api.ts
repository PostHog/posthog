/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'

/**
 * Invoke an MCP tool by name.

This endpoint allows MCP callers to invoke Max AI tools directly
without going through the full LangChain conversation flow.

Scopes are resolved dynamically per tool via dangerously_get_required_scopes.
 */
export const getMcpToolsCreateUrl = (projectId: string, toolName: string) => {
    return `/api/environments/${projectId}/mcp_tools/${toolName}/`
}

export const mcpToolsCreate = async (projectId: string, toolName: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getMcpToolsCreateUrl(projectId, toolName), {
        ...options,
        method: 'POST',
    })
}
