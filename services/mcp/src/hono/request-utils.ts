import { z } from 'zod'

import { classifyAuthFailure, mapErrorToAuthResponse, validateBearerToken } from '@/lib/auth-errors'
import { getPostHogClient } from '@/lib/posthog'
import {
    type ClientInfo,
    parseRequestProperties,
    type RequestProperties,
    type Transport,
} from '@/lib/request-properties'
import { getRegionFromRequest } from '@/lib/routing'
import { parseRequestProtocolMeta } from '@/lib/stateless-protocol'
import { extractBearerToken, sanitizeHeaderValue } from '@/lib/utils'

import { trackAuthFailure } from './analytics'
import { authFailuresTotal } from './metrics'
import type { RequestCharge } from './rate-limiter'
import { classifyRequestCharge } from './request-cost'
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

interface ParsedBody {
    clientInfo: ClientInfo
    /** Every JSON-RPC method the body carries, in order. Empty when unparseable. */
    methods: string[]
}

function parseBody(bodyText: string): ParsedBody {
    const methods: string[] = []
    try {
        const parsed = JSON.parse(bodyText)
        const messages = Array.isArray(parsed) ? parsed : [parsed]
        // 2026-07-28 stateless clients never send `initialize` — their identity
        // rides in each request's `_meta`. Prefer an initialize payload when
        // present (legacy dialect), else fall back to the first `_meta` match.
        let initializeInfo: ClientInfo | undefined
        let metaFallback: ClientInfo | undefined
        for (const msg of messages) {
            const rpc = JsonRpcMessageSchema.safeParse(msg)
            if (!rpc.success) {
                continue
            }
            methods.push(rpc.data.method)
            if (rpc.data.method === 'initialize') {
                const params = InitializeParamsSchema.safeParse(rpc.data.params)
                if (!params.success || initializeInfo) {
                    continue
                }
                initializeInfo = {
                    clientName: sanitizeHeaderValue(params.data.clientInfo?.name),
                    clientVersion: sanitizeHeaderValue(params.data.clientInfo?.version),
                    protocolVersion: sanitizeHeaderValue(params.data.protocolVersion),
                }
                continue
            }
            if (!metaFallback) {
                const meta = parseRequestProtocolMeta(rpc.data.params)
                if (meta.protocolVersion || meta.clientName) {
                    metaFallback = {
                        clientName: sanitizeHeaderValue(meta.clientName),
                        clientVersion: sanitizeHeaderValue(meta.clientVersion),
                        protocolVersion: sanitizeHeaderValue(meta.protocolVersion),
                    }
                }
            }
        }
        return { clientInfo: initializeInfo ?? metaFallback ?? {}, methods }
    } catch {}
    return { clientInfo: {}, methods: [] }
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
): Promise<{ props: RequestProperties; charge: RequestCharge } | { error: Response }> {
    const error = authenticate(c)
    if (error) {
        return { error }
    }

    const bodyText = await preserveBody(c)
    const body = parseBody(bodyText)
    const props = parseRequestProperties(c.req.raw, body.clientInfo, transport)

    props.mcpSessionId = sanitizeHeaderValue(c.req.header('mcp-session-id') || undefined)
    props.mcpConversationId = sanitizeHeaderValue(c.req.header('mcp-conversation-id') || undefined)
    props.region = props.region || getRegionFromRequest(c.req.raw) || undefined
    if (new URL(c.req.url).searchParams.get('_deprecated') === 'sse') {
        props.viaSseRedirect = true
    }

    return { props, charge: classifyRequestCharge(body.methods) }
}

export function handleCatchError(error: unknown, props: RequestProperties): Response {
    console.error('[handleCatchError]', error)
    const authResponse = mapErrorToAuthResponse(error)
    if (authResponse) {
        const reason = authResponse.status === 403 ? 'insufficient_scope' : 'invalid_token'
        authFailuresTotal.inc({ reason })
        trackAuthFailure(props, classifyAuthFailure(error))
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
