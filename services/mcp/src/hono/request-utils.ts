import { z } from 'zod'

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

const InitializeParamsSchema = z.object({
    clientInfo: z
        .object({
            name: z.string().optional(),
            version: z.string().optional(),
        })
        .optional(),
    protocolVersion: z.string().optional(),
})

const JsonRpcMessageSchema = z.object({
    method: z.string(),
    params: z.unknown().optional(),
})

function parseClientInfo(bodyText: string): ClientInfo {
    try {
        const parsed = JSON.parse(bodyText)
        const messages = Array.isArray(parsed) ? parsed : [parsed]

        for (const msg of messages) {
            const rpc = JsonRpcMessageSchema.safeParse(msg)
            if (!rpc.success || rpc.data.method !== 'initialize') {
                continue
            }
            const params = InitializeParamsSchema.safeParse(rpc.data.params)
            if (!params.success) {
                continue
            }
            return {
                clientName: sanitizeHeaderValue(params.data.clientInfo?.name),
                clientVersion: sanitizeHeaderValue(params.data.clientInfo?.version),
                protocolVersion: sanitizeHeaderValue(params.data.protocolVersion),
            }
        }
    } catch {}
    return {}
}

function rebuildRequest(c: HonoCtx, bodyText: string): void {
    const raw = c.req.raw
    const fresh = new Request(raw.url, { method: raw.method, headers: raw.headers, body: bodyText })
    Object.defineProperty(c.req, 'raw', { value: fresh, writable: true, configurable: true })
}

export async function authenticateAndParse(
    c: HonoCtx,
    transport: Transport
): Promise<{ props: RequestProperties } | { error: Response }> {
    const raw = c.req.raw
    const token = c.req.header('Authorization')?.split(' ')[1]

    const tokenError = validateBearerToken(token, raw, getRegionFromRequest(raw))
    if (tokenError) {
        return { error: tokenError }
    }

    const hasBody = raw.method === 'POST' || raw.method === 'PUT' || raw.method === 'PATCH'
    const bodyText = hasBody ? await raw.text() : null

    if (bodyText !== null) {
        rebuildRequest(c, bodyText)
    }

    const clientInfo = bodyText ? parseClientInfo(bodyText) : {}
    const props = parseRequestProperties(raw, clientInfo, transport)

    const mcpSessionId = sanitizeHeaderValue(c.req.header('mcp-session-id') || undefined)
    const mcpConversationId = sanitizeHeaderValue(c.req.header('mcp-conversation-id') || undefined)
    const viaSseRedirect = new URL(c.req.url).searchParams.get('_deprecated') === 'sse'

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
