import { getPostHogClient } from '@/lib/analytics'
import { mapErrorToAuthResponse, mapKnownErrorMessage, validateBearerToken } from '@/lib/auth-errors'
import {
    type ClientInfo,
    parseRequestProperties,
    type RequestProperties,
    type Transport,
} from '@/lib/request-properties'
import { getRegionFromRequest } from '@/lib/routing'
import { sanitizeHeaderValue } from '@/lib/utils'

import type { HonoCtx } from './types'

function parseClientInfoFromText(text: string): ClientInfo {
    try {
        const parsed: unknown = JSON.parse(text)
        const messages = Array.isArray(parsed) ? parsed : [parsed]
        for (const msg of messages) {
            if (!msg || typeof msg !== 'object' || (msg as { method?: unknown }).method !== 'initialize') {
                continue
            }
            const params = (
                msg as { params?: { clientInfo?: { name?: unknown; version?: unknown }; protocolVersion?: unknown } }
            ).params
            if (!params) {
                continue
            }
            return {
                clientName: sanitizeHeaderValue(
                    typeof params.clientInfo?.name === 'string' ? params.clientInfo.name : undefined
                ),
                clientVersion: sanitizeHeaderValue(
                    typeof params.clientInfo?.version === 'string' ? params.clientInfo.version : undefined
                ),
                protocolVersion: sanitizeHeaderValue(
                    typeof params.protocolVersion === 'string' ? params.protocolVersion : undefined
                ),
            }
        }
    } catch {}
    return {}
}

export async function authenticateAndParse(
    c: HonoCtx,
    transport: Transport
): Promise<{ props: RequestProperties } | { error: Response }> {
    const raw = c.req.raw
    const token = c.req.header('Authorization')?.split(' ')[1]
    const effectiveRegion = getRegionFromRequest(raw)

    const tokenError = validateBearerToken(token, raw, effectiveRegion)
    if (tokenError) {
        return { error: tokenError }
    }

    const hasBody = raw.method !== 'GET' && raw.method !== 'HEAD' && raw.method !== 'DELETE'
    const bodyText = hasBody ? await raw.text() : null

    // Rebuild c.req.raw so downstream (transport.handleRequest) can still read the body.
    if (bodyText !== null) {
        const fresh = new Request(raw.url, { method: raw.method, headers: raw.headers, body: bodyText })
        Object.defineProperty(c.req, 'raw', { value: fresh, writable: true })
    }

    const clientInfo = bodyText ? parseClientInfoFromText(bodyText) : {}
    const props = parseRequestProperties(raw, clientInfo, transport)

    const mcpSessionId = sanitizeHeaderValue(c.req.header('mcp-session-id') || undefined)
    const mcpConversationId = sanitizeHeaderValue(c.req.header('mcp-conversation-id') || undefined)
    const url = new URL(c.req.url)
    const viaSseRedirect = url.searchParams.get('_deprecated') === 'sse'

    Object.assign(props, {
        ...(mcpSessionId ? { mcpSessionId } : {}),
        ...(mcpConversationId ? { mcpConversationId } : {}),
        ...(viaSseRedirect ? { viaSseRedirect: true } : {}),
    })

    return { props }
}

export function handleCatchError(error: unknown, props: RequestProperties): Response {
    const authResponse = mapErrorToAuthResponse(error)
    if (authResponse) {
        return authResponse
    }
    try {
        if (error instanceof Error) {
            getPostHogClient().captureException(error, props.userHash, {
                team: 'posthog_ai',
                source: 'mcp_hono_request',
                mcp_transport: props.transport,
            })
        }
    } catch {}
    return new Response('Internal server error', { status: 500 })
}

export async function passThrough(response: Response): Promise<Response> {
    if (response.ok) {
        return response
    }
    const body = await response.clone().text()
    return mapKnownErrorMessage(body) ?? response
}
