// Shared request-properties extraction. Both runtimes parse the same headers
// and query params into the same shape, so the logic lives here.

import { resolveEffectiveClientName } from './client-detection'
import { extractBearerToken, hash, parseMcpMode, sanitizeHeaderValue, type McpMode } from './utils'

export type Transport = 'streamable-http' | 'sse'

export type RequestProperties = {
    userHash: string
    apiToken: string
    sessionId?: string | undefined
    features?: string[] | undefined
    tools?: string[] | undefined
    region?: string | undefined
    organizationId?: string | undefined
    projectId?: string | undefined
    clientUserAgent?: string | undefined
    mcpConsumer?: string | undefined
    mcpClientName?: string | undefined
    mcpClientVersion?: string | undefined
    mcpProtocolVersion?: string | undefined
    mcpVendorClient?: string | undefined
    readOnly?: boolean | undefined
    mode?: McpMode | undefined
    transport?: Transport | undefined
    mcpSessionId?: string | undefined
    mcpConversationId?: string | undefined
    viaSseRedirect?: boolean | undefined
    requestStartTime?: number | undefined
    // Sandbox-provisioned task id: forwarded to the PostHog API as `X-PostHog-Task-Id` on every
    // call so writes can be attributed to the agent's task (validated server-side per team).
    taskId?: string | undefined
    // Dev/test-only per-request feature-flag overrides — a JSON object string from
    // `?flag_overrides=` or the `x-posthog-flag-overrides` header. Parsed and gated
    // to NODE_ENV development/test (fail-closed) in `resolveFeatureFlagOverrides`.
    featureFlagOverrides?: string | undefined
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

    const token = extractBearerToken(request) ?? ''
    const readOnlyRaw = header(request, 'x-posthog-read-only') || params.get('readonly')
    const vendorClient = sanitizeHeaderValue(header(request, 'x-anthropic-client'))

    return {
        apiToken: token,
        userHash: hash(token),
        sessionId: params.get('sessionId') || undefined,
        organizationId: header(request, 'x-posthog-organization-id') || params.get('organization_id') || undefined,
        projectId: header(request, 'x-posthog-project-id') || params.get('project_id') || undefined,
        features: splitCsv(params.get('features')),
        tools: splitCsv(params.get('tools')),
        region: params.get('region') || undefined,
        readOnly: readOnlyRaw === 'true' || readOnlyRaw === '1' || undefined,
        clientUserAgent: sanitizeHeaderValue(header(request, 'User-Agent')),
        mcpConsumer: sanitizeHeaderValue(
            header(request, 'x-posthog-mcp-consumer') || params.get('consumer') || undefined
        ),
        mcpClientName: resolveEffectiveClientName(clientInfo.clientName, vendorClient),
        mcpClientVersion: clientInfo.clientVersion,
        mcpProtocolVersion: clientInfo.protocolVersion,
        mcpVendorClient: vendorClient,
        mode: parseMcpMode(header(request, 'x-posthog-mcp-mode') || params.get('mode')),
        taskId: sanitizeHeaderValue(header(request, 'x-posthog-task-id')),
        transport,
        requestStartTime: Date.now(),
        featureFlagOverrides: header(request, 'x-posthog-flag-overrides') || params.get('flag_overrides') || undefined,
    }
}
