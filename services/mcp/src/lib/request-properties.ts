// Shared request-properties extraction. Both runtimes parse the same headers
// and query params into the same shape, so the logic lives here.

import { hash, parseMcpMode, sanitizeHeaderValue, type McpMode } from './utils'

export type Transport = 'streamable-http' | 'sse'

export type RequestProperties = {
    userHash: string
    apiToken: string
    sessionId?: string | undefined
    features?: string[] | undefined
    tools?: string[] | undefined
    region?: string | undefined
    version?: number | undefined
    organizationId?: string | undefined
    projectId?: string | undefined
    clientUserAgent?: string | undefined
    mcpConsumer?: string | undefined
    mcpClientName?: string | undefined
    mcpClientVersion?: string | undefined
    mcpProtocolVersion?: string | undefined
    readOnly?: boolean | undefined
    mode?: McpMode | undefined
    transport?: Transport | undefined
    requestStartTime?: number | undefined
}

export type ClientInfo = {
    clientName?: string | undefined
    clientVersion?: string | undefined
    protocolVersion?: string | undefined
}

function header(request: Request, name: string): string | undefined {
    return request.headers.get(name) || undefined
}

function splitCsv(value: string | null): string[] | undefined {
    if (!value) {
        return undefined
    }
    const parts = value.split(',').filter(Boolean)
    return parts.length > 0 ? parts : undefined
}

export function parseRequestProperties(
    request: Request,
    clientInfo: ClientInfo,
    transport?: Transport
): RequestProperties {
    const url = new URL(request.url)
    const params = url.searchParams

    const token = request.headers.get('Authorization')?.split(' ')[1] ?? ''
    const readOnlyRaw = header(request, 'x-posthog-readonly') || params.get('readonly')

    return {
        apiToken: token,
        userHash: hash(token),
        sessionId: params.get('sessionId') || undefined,
        organizationId: header(request, 'x-posthog-organization-id') || params.get('organization_id') || undefined,
        projectId: header(request, 'x-posthog-project-id') || params.get('project_id') || undefined,
        features: splitCsv(params.get('features')),
        tools: splitCsv(params.get('tools')),
        region: params.get('region') || undefined,
        version: Number(header(request, 'x-posthog-mcp-version') || params.get('v')) || 1,
        readOnly: readOnlyRaw === 'true' || readOnlyRaw === '1' || undefined,
        clientUserAgent: sanitizeHeaderValue(header(request, 'User-Agent')),
        mcpConsumer: sanitizeHeaderValue(header(request, 'x-posthog-mcp-consumer')),
        mcpClientName: clientInfo.clientName,
        mcpClientVersion: clientInfo.clientVersion,
        mcpProtocolVersion: clientInfo.protocolVersion,
        mode: parseMcpMode(header(request, 'x-posthog-mcp-mode') || params.get('mode')),
        transport,
        requestStartTime: Date.now(),
    }
}
