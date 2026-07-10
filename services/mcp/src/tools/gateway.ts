/**
 * Client for the MCP gateway REST endpoints (`products/mcp_store`'s
 * `mcp_gateway` viewset), which expose the tools of external MCP servers a
 * team connected via the PostHog MCP store. The exec tool routes names
 * containing `/` (`<server_slug>/<tool_name>`) here; see `ExecToolOptions.gateway`.
 *
 * Every request rides the caller's own bearer through the shared `ApiClient` —
 * this service never holds upstream server secrets; the Django execution plane
 * is the only place they are decrypted.
 */
import { PostHogApiError } from '@/lib/errors'

import type { Context } from './types'

/** Namespaced gateway tool names are `<server_slug>/<tool_name>`; `/` never
 *  appears in PostHog's own kebab-case tool names, so it is the routing signal. */
export function isGatewayToolName(name: string): boolean {
    return name.includes('/')
}

export interface GatewayServerInfo {
    slug: string
    display_name: string
    installation_id: string
    scope: 'personal' | 'shared'
}

export type GatewayToolApprovalState = 'approved' | 'needs_approval' | 'do_not_use'

export interface GatewayTool {
    /** Namespaced `<server_slug>/<tool_name>`. */
    name: string
    server: GatewayServerInfo
    tool_name: string
    description: string
    input_schema: Record<string, unknown>
    approval_state: GatewayToolApprovalState
}

export interface GatewayCallContentBlock {
    type: string
    text?: string
    [key: string]: unknown
}

/** Mirrors the MCP CallToolResult plus gateway call metadata. */
export interface GatewayCallResult {
    content: GatewayCallContentBlock[]
    is_error: boolean
    structured_content?: Record<string, unknown>
    server_slug: string
    tool_name: string
    duration_ms: number
}

/** Surface the exec tool talks to; `createGatewayClient` is the API-backed
 *  implementation, tests substitute their own. */
export interface GatewayClient {
    searchTools(query: string): Promise<GatewayTool[]>
    getTool(name: string): Promise<GatewayTool | undefined>
    callTool(name: string, args: Record<string, unknown>): Promise<GatewayCallResult>
}

/** Caps how many connected-server tools a single `exec search` merges in, so a
 *  broad query can't crowd out the PostHog results. */
const GATEWAY_SEARCH_LIMIT = 10

export function unknownGatewayToolMessage(name: string): string {
    return `Unknown connected-server tool: "${name}". Run "search <words>" to find tools from connected MCP servers.`
}

// The list endpoint is DRF-paginated in the default configuration but the
// contract only pins the item shape — accept both a bare array and a
// `{ results: [...] }` envelope.
type GatewayToolListResponse = GatewayTool[] | { results?: GatewayTool[] }

function toToolList(response: GatewayToolListResponse): GatewayTool[] {
    if (Array.isArray(response)) {
        return response
    }
    return response.results ?? []
}

function parseErrorBody(body: string): Record<string, unknown> | undefined {
    try {
        const parsed: unknown = JSON.parse(body)
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>)
            : undefined
    } catch {
        return undefined
    }
}

/**
 * Map a gateway `POST call/` failure to an actionable message. Re-thrown as a
 * `PostHogApiError` with the same status so error classification and the
 * 4xx/5xx capture split in `handleToolError` keep working; only the message is
 * replaced with something the agent (and the user) can act on.
 */
function mapGatewayCallError(name: string, error: unknown): unknown {
    if (!(error instanceof PostHogApiError)) {
        return error
    }
    const body = parseErrorBody(error.body)
    const code = typeof body?.code === 'string' ? body.code : undefined

    let message: string | undefined
    if (error.status === 403 && code === 'tool_needs_approval') {
        const approvalUrl = typeof body?.approval_url === 'string' ? body.approval_url : undefined
        message =
            `Tool "${name}" needs approval before it can be called. ` +
            `Ask the user to approve it in their PostHog MCP server settings${approvalUrl ? `: ${approvalUrl}` : '.'}`
    } else if (error.status === 403 && code === 'tool_blocked') {
        message = `Tool "${name}" is blocked ("do not use") in this project's MCP server settings and cannot be called.`
    } else if (error.status === 404) {
        message = unknownGatewayToolMessage(name)
    } else if (error.status === 502) {
        const detail = typeof body?.detail === 'string' ? body.detail : error.body
        message = `The connected MCP server failed while executing "${name}": ${detail}`
    }

    if (!message) {
        return error
    }
    return new PostHogApiError({
        status: error.status,
        statusText: error.statusText,
        body: error.body,
        url: error.url,
        method: error.method,
        message,
    })
}

/** Render a gateway CallToolResult's content for the agent: text blocks joined,
 *  non-text blocks noted by type, structured content as a JSON fallback. */
export function renderGatewayCallContent(result: GatewayCallResult): string {
    const parts = (result.content ?? []).map((block) =>
        block.type === 'text' && typeof block.text === 'string' ? block.text : `[${block.type} content omitted]`
    )
    const text = parts.join('\n').trim()
    if (text) {
        return text
    }
    if (result.structured_content) {
        return JSON.stringify(result.structured_content)
    }
    return '(empty result)'
}

export function createGatewayClient(context: Context, consumer?: string): GatewayClient {
    const listTools = async (query: Record<string, unknown>): Promise<GatewayTool[]> => {
        const projectId = await context.stateManager.getProjectId()
        const response = await context.api.request<GatewayToolListResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/mcp_gateway/tools/`,
            query,
        })
        return toToolList(response)
    }

    return {
        async searchTools(query: string): Promise<GatewayTool[]> {
            return listTools({ search: query, limit: GATEWAY_SEARCH_LIMIT })
        },

        async getTool(name: string): Promise<GatewayTool | undefined> {
            const tools = await listTools({ name })
            return tools.find((t) => t.name === name) ?? tools[0]
        },

        async callTool(name: string, args: Record<string, unknown>): Promise<GatewayCallResult> {
            const projectId = await context.stateManager.getProjectId()
            try {
                return await context.api.request<GatewayCallResult>({
                    method: 'POST',
                    path: `/api/projects/${encodeURIComponent(projectId)}/mcp_gateway/call/`,
                    body: {
                        tool: name,
                        arguments: args,
                        ...(consumer ? { consumer } : {}),
                    },
                })
            } catch (error) {
                throw mapGatewayCallError(name, error)
            }
        },
    }
}
