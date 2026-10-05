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
import type { WebMCPExecRequestApi, WebMCPExecResultApi, WebMCPExecToolApi } from './api.schemas'

export const getWebmcpExecCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/webmcp/exec/`
}

/**
 * @summary Run an exec command on the PostHog MCP server
 */
export const webmcpExecCreate = async (
    projectId: string,
    webMCPExecRequestApi: WebMCPExecRequestApi,
    options?: RequestInit
): Promise<WebMCPExecResultApi> => {
    return apiMutator<WebMCPExecResultApi>(getWebmcpExecCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(webMCPExecRequestApi),
    })
}

export const getWebmcpToolRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/webmcp/tool/`
}

/**
 * @summary Get the exec tool definition to register with WebMCP
 */
export const webmcpToolRetrieve = async (projectId: string, options?: RequestInit): Promise<WebMCPExecToolApi> => {
    return apiMutator<WebMCPExecToolApi>(getWebmcpToolRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
