import { getPostHogClient } from '@/lib/analytics'
import { mapErrorToAuthResponse, mapKnownErrorMessage, validateBearerToken } from '@/lib/auth-errors'
import { extractClientInfoFromBody } from '@/lib/mcp-client-info'
import {
    parseRequestProperties,
    type RequestProperties,
    type Transport,
} from '@/lib/request-properties'
import { getRegionFromRequest } from '@/lib/routing'

import type { HonoCtx } from './types'

// Auth + request parsing -----------------------------------------------------

export async function authenticateAndParse(
    c: HonoCtx,
    transport: Transport
): Promise<{ props: RequestProperties } | { error: Response }> {
    const token = c.req.header('Authorization')?.split(' ')[1]
    const effectiveRegion = getRegionFromRequest(c.req.raw)

    const tokenError = validateBearerToken(token, c.req.raw, effectiveRegion)
    if (tokenError) {
        return { error: tokenError }
    }
    const clientInfo = await extractClientInfoFromBody(c.req.raw)
    return { props: parseRequestProperties(c.req.raw, clientInfo, transport) }
}

// Error / response shaping ---------------------------------------------------

function reportInternalError(error: unknown, props: RequestProperties): void {
    try {
        if (error instanceof Error) {
            getPostHogClient().captureException(error, props.userHash, {
                team: 'posthog_ai',
                source: 'mcp_hono_request',
                mcp_transport: props.transport,
            })
        }
    } catch {
        // Never let observability break the request.
    }
}

export function handleCatchError(error: unknown, props: RequestProperties): Response {
    const authResponse = mapErrorToAuthResponse(error)
    if (authResponse) {
        return authResponse
    }
    if (process.env.DEBUG_MCP === '1') {
        console.error('[MCP catch]', error)
    }
    reportInternalError(error, props)
    return new Response('Internal server error', { status: 500 })
}

// Re-shape responses whose body announces a known PostHog auth error so the
// MCP client sees a 401 instead of an opaque success-with-error-body.
export async function passThrough(response: Response): Promise<Response> {
    if (response.ok) {
        return response
    }
    const body = await response.clone().text()
    return mapKnownErrorMessage(body) ?? response
}
