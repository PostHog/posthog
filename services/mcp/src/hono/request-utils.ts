import { z } from 'zod'

import { mapErrorToAuthResponse, validateBearerToken } from '@/lib/auth-errors'
import { getPostHogClient } from '@/lib/posthog'
import {
    type ClientInfo,
    parseRequestProperties,
    type RequestProperties,
    type Transport,
} from '@/lib/request-properties'
import { getRegionFromRequest } from '@/lib/routing'
import { extractBearerToken, sanitizeHeaderValue } from '@/lib/utils'

import { authFailuresTotal } from './metrics'
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

function authenticate(c: HonoCtx): Response | null {
    const token = extractBearerToken(c.req.raw)
    const error = validateBearerToken(token, c.req.raw, getRegionFromRequest(c.req.raw))
    if (error) {
        const reason = !token ? 'missing_token' : 'invalid_token'
        authFailuresTotal.inc({ reason })
    }
    return error
}

async function preserveBody(c: HonoCtx): Promise<string> {
    const raw = c.req.raw
    const bodyText = await raw.text()
    const fresh = new Request(raw.url, { method: raw.method, headers: raw.headers, body: bodyText })
    Object.defineProperty(c.req, 'raw', { value: fresh, writable: true, configurable: true })
    return bodyText
}

export async function authenticateAndParse(
    c: HonoCtx,
    transport: Transport
): Promise<{ props: RequestProperties } | { error: Response }> {
    const error = authenticate(c)
    if (error) {
        return { error }
    }

    const bodyText = await preserveBody(c)
    const props = parseRequestProperties(c.req.raw, parseClientInfo(bodyText), transport)

    props.mcpSessionId = sanitizeHeaderValue(c.req.header('mcp-session-id') || undefined)
    props.mcpConversationId = sanitizeHeaderValue(c.req.header('mcp-conversation-id') || undefined)
    props.region = props.region || getRegionFromRequest(c.req.raw) || undefined
    if (new URL(c.req.url).searchParams.get('_deprecated') === 'sse') {
        props.viaSseRedirect = true
    }

    return { props }
}

export function handleCatchError(error: unknown, props: RequestProperties): Response {
    console.error('[handleCatchError]', error)
    const authResponse = mapErrorToAuthResponse(error)
    if (authResponse) {
        const reason = authResponse.status === 403 ? 'insufficient_scope' : 'invalid_token'
        authFailuresTotal.inc({ reason })
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
