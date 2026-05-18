import { getPostHogClient } from '@/lib/analytics'
import { mapErrorToAuthResponse, mapKnownErrorMessage, validateBearerToken } from '@/lib/auth-errors'
import { extractClientInfoFromBody } from '@/lib/mcp-client-info'
import { parseRequestProperties, type RequestProperties, type Transport } from '@/lib/request-properties'
import { getRegionFromRequest } from '@/lib/routing'
import { sanitizeHeaderValue } from '@/lib/utils'

import type { HonoCtx } from './types'

// Auth + request parsing -----------------------------------------------------

export async function authenticateAndParse(
    c: HonoCtx,
    transport: Transport
): Promise<{ props: RequestProperties } | { error: Response }> {
    const token = c.req.header('Authorization')?.split(' ')[1]
    const raw = c.req.raw
    const effectiveRegion = getRegionFromRequest(raw)

    const tokenError = validateBearerToken(token, raw, effectiveRegion)
    if (tokenError) {
        return { error: tokenError }
    }

    const hasBody = raw.method !== 'GET' && raw.method !== 'HEAD' && raw.method !== 'DELETE'
    const bodyText = hasBody ? await raw.text() : null
    const freshRequest = new Request(raw.url, {
        method: raw.method,
        headers: raw.headers,
        ...(bodyText ? { body: bodyText } : {}),
    })
    Object.defineProperty(c.req, 'raw', { value: freshRequest, writable: true })

    const clientInfo = hasBody
        ? await extractClientInfoFromBody(
              new Request(raw.url, {
                  method: raw.method,
                  headers: raw.headers,
                  body: bodyText,
              })
          )
        : {}
    const props = parseRequestProperties(freshRequest, clientInfo, transport)

    // Fields the CF worker extracts in index.ts that the shared parser doesn't
    // handle yet. Assigned at runtime so the Hono MCP server can read them via
    // its own extended type.
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
