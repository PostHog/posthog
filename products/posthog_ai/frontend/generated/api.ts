import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type { DocsSearchRequestApi, DocsSearchResponseApi, McpToolsCreate200 } from './api.schemas'

/**
 * Invoke an MCP tool by name.

This endpoint allows MCP callers to invoke Max AI tools directly
without going through the full LangChain conversation flow.

Scopes are resolved dynamically per tool via dangerously_get_required_scopes.
 */
export const getMcpToolsCreateUrl = (projectId: string, toolName: string) => {
    return `/api/environments/${projectId}/mcp_tools/${toolName}/`
}

export const mcpToolsCreate = async (
    projectId: string,
    toolName: string,
    options?: RequestInit
): Promise<McpToolsCreate200> => {
    return apiMutator<McpToolsCreate200>(getMcpToolsCreateUrl(projectId, toolName), {
        ...options,
        method: 'POST',
    })
}

/**
 * Run a hybrid (semantic + full-text) RAG search over the PostHog documentation via Inkeep. Returns a markdown body with title, URL, and excerpt for each match for the agent to cite back to the user.
 * @summary Search PostHog documentation
 */
export const getDocsSearchUrl = (projectId: string) => {
    return `/api/environments/${projectId}/mcp_tools/docs_search/`
}

export const docsSearch = async (
    projectId: string,
    docsSearchRequestApi: DocsSearchRequestApi,
    options?: RequestInit
): Promise<DocsSearchResponseApi> => {
    return apiMutator<DocsSearchResponseApi>(getDocsSearchUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(docsSearchRequestApi),
    })
}
