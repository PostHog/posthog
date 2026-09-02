/**
 * Third-party MCP tools, reachable through the PostHog MCP.
 *
 * The MCP gateway (`products/mcp_store`) already holds the credentials, per-tool policy
 * and audit trail for the servers a team has connected. This module surfaces those tools
 * to `exec` so an external agent can search and call them without authenticating each
 * vendor separately.
 *
 * Tools resolved here are deliberately kept out of `ResolvedState.allTools`: the
 * instructions builder looks every entry up in the static tool-definition registry, and
 * a vendor tool has no definition there. They ride a separate channel into `exec`
 * instead (see `createExecTool`'s `gatewayToolsProvider`).
 */

import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ExecCommandError } from '@/lib/errors'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

/** Separates the server slug from the upstream tool name. PostHog's own tool names are
 *  kebab-case and never contain `__`, so a namespaced name can't collide with one. */
export const GATEWAY_TOOL_SEPARATOR = '__'

/** Analytics category for proxied tools. Matches the sentence case of the catalog's own
 *  categories, since both land in the same `$mcp_tool_category` breakdown. */
export const THIRD_PARTY_TOOL_CATEGORY = 'Third-party tools'

type AvailableServer = Schemas.AvailableServer
type AvailableTool = Schemas.AvailableTool

/** Where a namespaced tool name routes to, resolved once per session. */
interface GatewayToolTarget {
    installationId: string
    serverName: string
    toolName: string
}

export function gatewayToolName(slug: string, toolName: string): string {
    return `${slug}${GATEWAY_TOOL_SEPARATOR}${toolName}`
}

/** Whether a tool name came from a connected third-party server rather than PostHog. */
export function isGatewayToolName(name: string): boolean {
    return name.includes(GATEWAY_TOOL_SEPARATOR)
}

/** The server slug a namespaced tool name routes to, or undefined for a PostHog tool. */
export function gatewayServerSlug(name: string): string | undefined {
    if (!isGatewayToolName(name)) {
        return undefined
    }
    return name.slice(0, name.indexOf(GATEWAY_TOOL_SEPARATOR))
}

/**
 * Upstream tools declare their contract as JSON Schema, which the upstream server also
 * enforces. Validating a second time here would only add a way for us to reject a call
 * the vendor would have accepted, so the Zod schema stays permissive and the real schema
 * travels on `rawInputSchema` for `exec info` to render.
 */
const PERMISSIVE_ARGS_SCHEMA = z.looseObject({})

function annotationsFor(tool: AvailableTool): Tool['annotations'] {
    const declared = (tool.annotations ?? {}) as Record<string, unknown>
    // Absent hints take the MCP spec's defaults, which are also the cautious reading:
    // a tool is assumed destructive and non-read-only until it says otherwise. Inverting
    // that would let a server that declares nothing look safer than one that does.
    return {
        destructiveHint: declared['destructiveHint'] !== false,
        idempotentHint: declared['idempotentHint'] === true,
        openWorldHint: declared['openWorldHint'] !== false,
        readOnlyHint: declared['readOnlyHint'] === true,
    }
}

function describeTool(server: AvailableServer, tool: AvailableTool): string {
    const base = tool.description?.trim() || `Tool exposed by ${server.name}.`
    if (tool.approval_state === 'needs_approval') {
        return `${base}\n\n[Not yet approved: calling this will fail until someone approves it in PostHog under Settings → MCP servers.]`
    }
    return `${base}\n\n[Runs on ${server.name} via your PostHog MCP connection.]`
}

function extractText(content: Record<string, unknown>[]): string {
    const parts = content
        .filter((block) => block['type'] === 'text' && typeof block['text'] === 'string')
        .map((block) => block['text'] as string)
    return parts.join('\n')
}

async function callGatewayTool(
    context: Context,
    projectId: string,
    target: GatewayToolTarget,
    args: Record<string, unknown>
): Promise<unknown> {
    let response: Schemas.CallToolResponse
    try {
        response = await context.api.request<Schemas.CallToolResponse>({
            method: 'POST',
            path: `/api/projects/${projectId}/mcp_server_installations/${target.installationId}/call_tool/`,
            body: { tool_name: target.toolName, arguments: args },
        })
    } catch (error) {
        // The gateway refuses a call with a typed reason (needs approval, disabled by
        // policy, removed upstream). Surface that verbatim: it tells the agent whether
        // to stop or to ask the user for something, which a bare HTTP error does not.
        const refusal = parseRefusal(error)
        if (refusal) {
            throw new ExecCommandError(refusal, 'unknown_tool')
        }
        throw error
    }

    const content = (response.content ?? []) as Record<string, unknown>[]
    const text = extractText(content)
    if (response.is_error) {
        // The tool ran and reported failure. Not an exec-level error — hand the reason
        // back so the agent can fix its arguments and retry.
        return { error: text || `${target.toolName} reported an error`, server: target.serverName }
    }
    if (response.structured_content) {
        return response.structured_content
    }
    return text || content
}

/** Pull the gateway's `{detail, reason}` body out of an API error, if that's what it is. */
function parseRefusal(error: unknown): string | undefined {
    const body = (error as { body?: unknown } | undefined)?.body
    if (typeof body !== 'string') {
        return undefined
    }
    try {
        const parsed = JSON.parse(body) as { detail?: unknown; reason?: unknown }
        if (typeof parsed.detail === 'string' && typeof parsed.reason === 'string') {
            return parsed.detail
        }
    } catch {
        return undefined
    }
    return undefined
}

/**
 * Turn the gateway's `available_tools` payload into callable `Tool`s.
 *
 * Names are namespaced by the server slug the backend assigned, which is stable across
 * requests and unique within a payload — so a name resolved by `exec search` still routes
 * correctly when `exec call` runs later in the session.
 */
export function buildGatewayTools(
    payload: Schemas.AvailableToolsResponse,
    context: Context,
    projectId: string
): Tool<ZodObjectAny>[] {
    const tools: Tool<ZodObjectAny>[] = []

    for (const server of payload.servers ?? []) {
        for (const tool of server.tools ?? []) {
            const target: GatewayToolTarget = {
                installationId: String(server.installation_id),
                serverName: server.name,
                toolName: tool.name,
            }
            tools.push({
                name: gatewayToolName(server.slug, tool.name),
                title: `${server.name}: ${tool.name}`,
                description: describeTool(server, tool),
                schema: PERMISSIVE_ARGS_SCHEMA,
                rawInputSchema: (tool.input_schema ?? {}) as Record<string, unknown>,
                scopes: [],
                annotations: annotationsFor(tool),
                handler: (_ctx, params) =>
                    callGatewayTool(context, projectId, target, params as Record<string, unknown>),
            })
        }
    }

    return tools
}

/**
 * Resolve the caller's third-party tools, cached per project for a short window so a
 * newly connected server shows up without a session restart. Never throws: a gateway
 * that is unreachable or disabled must not take PostHog's own tools down with it.
 */
export async function resolveGatewayTools(context: Context, projectId: string): Promise<Tool<ZodObjectAny>[]> {
    const payload = await context.stateManager.getOrFetchGatewayTools(projectId)
    if (!payload) {
        return []
    }
    return buildGatewayTools(payload, context, projectId)
}
